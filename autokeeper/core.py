"""DVLA vehicle checks, persistence and email reminders.

Secrets are environment variables; no live vehicle data belongs in Git.
"""
import os
import re
import sqlite3
import smtplib
from datetime import date, datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import requests

DVLA_URL = "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"
VEHICLE_COLUMNS = ("registration", "owner", "company", "email", "make", "model", "colour")


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def open_db(path=None):
    path = path or os.environ.get("AUTOKEEPER_DB_PATH", "data/autokeeper.db")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may construct the request-scoped DB dependency in a worker
    # thread, then execute an async upload handler on the event-loop thread.
    # Each request gets its own connection; permit that controlled handoff.
    db = sqlite3.connect(path, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS vehicles (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          registration TEXT NOT NULL UNIQUE,
          owner TEXT NOT NULL DEFAULT '',
          company TEXT NOT NULL DEFAULT '',
          email TEXT NOT NULL DEFAULT '',
          make TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL DEFAULT '',
          colour TEXT NOT NULL DEFAULT '',
          acquisition_date TEXT,
          disposal_date TEXT,
          fuel_type TEXT NOT NULL DEFAULT '',
          year_of_manufacture INTEGER,
          mot_status TEXT NOT NULL DEFAULT '',
          mot_expiry_date TEXT,
          tax_status TEXT NOT NULL DEFAULT '',
          tax_due_date TEXT,
          last_checked_at TEXT,
          last_error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS checks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
          checked_at TEXT NOT NULL,
          success INTEGER NOT NULL,
          mot_expiry_date TEXT,
          tax_due_date TEXT,
          error TEXT
        );
        CREATE TABLE IF NOT EXISTS notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
          kind TEXT NOT NULL,
          due_date TEXT NOT NULL,
          stage TEXT NOT NULL,
          recipient TEXT NOT NULL,
          sent_at TEXT NOT NULL,
          UNIQUE(vehicle_id, kind, due_date, stage, recipient)
        );
    """)
    # Add nullable lifecycle fields to existing installations without replacing
    # or deleting any vehicle records, notification history or DVLA checks.
    existing_columns = {row["name"] for row in db.execute("PRAGMA table_info(vehicles)")}
    for field in ("acquisition_date", "disposal_date"):
        if field not in existing_columns:
            db.execute(f"ALTER TABLE vehicles ADD COLUMN {field} TEXT")
    db.commit()


def registration(value):
    value = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    if not re.fullmatch(r"[A-Z0-9]{2,10}", value):
        raise ValueError("Enter a vehicle registration using 2–10 letters/numbers.")
    return value


def email_address(value):
    value = str(value or "").strip().lower()
    if value and (len(value) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value)):
        raise ValueError("Invalid recipient email address.")
    return value


def normalise_lifecycle_date(value):
    """Optional ISO or UK-style date. Excel date/datetime cells are supported."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Invalid lifecycle date. Use YYYY-MM-DD or DD/MM/YYYY.")


def is_disposed(vehicle, today=None):
    """A future disposal is scheduled, not yet complete."""
    disposal = iso_date(vehicle.get("disposal_date"))
    return bool(disposal and disposal <= (today or date.today()))


def save_vehicle(db, body, vehicle_id=None):
    current = get_vehicle(db, vehicle_id) if vehicle_id is not None else None
    if vehicle_id is not None and current is None:
        raise LookupError("Vehicle not found")
    values = {k: str(body.get(k) or "").strip()[:140] for k in VEHICLE_COLUMNS}
    values["registration"] = registration(values["registration"])
    values["email"] = email_address(values["email"])
    # Older API clients omitting these new optional fields must preserve values.
    for field in ("acquisition_date", "disposal_date"):
        supplied = body[field] if field in body else (current.get(field) if current else None)
        values[field] = normalise_lifecycle_date(supplied)
    if (values["acquisition_date"] and values["disposal_date"]
            and values["disposal_date"] < values["acquisition_date"]):
        raise ValueError("Disposal date cannot be before acquisition date.")
    stamp = utcnow()
    if vehicle_id is None:
        cursor = db.execute("""
            INSERT INTO vehicles(registration, owner, company, email, make, model, colour,
                                 acquisition_date, disposal_date, created_at, updated_at)
            VALUES(:registration, :owner, :company, :email, :make, :model, :colour,
                   :acquisition_date, :disposal_date, :created, :updated)
        """, {**values, "created": stamp, "updated": stamp})
        vehicle_id = cursor.lastrowid
    else:
        db.execute("""
            UPDATE vehicles SET registration=:registration, owner=:owner, company=:company,
              email=:email, make=:make, model=:model, colour=:colour,
              acquisition_date=:acquisition_date, disposal_date=:disposal_date,
              updated_at=:updated
            WHERE id=:id
        """, {**values, "updated": stamp, "id": vehicle_id})
    db.commit()
    return get_vehicle(db, vehicle_id)


def get_vehicle(db, vehicle_id):
    row = db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    return dict(row) if row else None


def iso_date(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except (ValueError, TypeError):
        return None


def status(expiry, today=None):
    today = today or date.today()
    value = iso_date(expiry)
    if not value:
        return {"state": "unknown", "days": None}
    days = (value - today).days
    return {"state": "overdue" if days < 0 else "due" if days <= 30 else "ok",
            "days": days}


def is_sorn(tax_status):
    """Use DVLA's tax state to identify vehicles declared off the road."""
    return str(tax_status or "").strip().casefold() == "sorn"


def view_vehicle(row, today=None):
    item = dict(row)
    item["company_key"] = company_key(item.get("company"))
    item["mot"] = status(item["mot_expiry_date"], today)
    item["tax"] = status(item["tax_due_date"], today)
    item["lifecycle_state"] = ("disposed" if is_disposed(item, today) else
                               "scheduled" if iso_date(item.get("disposal_date")) else "active")
    if item["lifecycle_state"] == "disposed":
        # Keep the underlying DVLA dates for historical reporting.
        item["mot"] = {"state": "disposed", "days": None}
        item["tax"] = {"state": "disposed", "days": None}
    elif is_sorn(item["tax_status"]):
        # SORN does not extend or cancel the underlying MOT expiry date.
        # Pause the dashboard's due/overdue warning while kept off road,
        # then resume the ordinary MOT rule when DVLA no longer reports SORN.
        item["mot"] = {"state": "sorn", "days": None}
        item["tax"] = {"state": "sorn", "days": None}
    return item


def company_key(value):
    """Company grouping ignores surrounding whitespace and letter case."""
    return str(value or "").strip().casefold()


def fleet_stats(rows):
    """One source of truth for both fleet-wide and company KPIs."""
    active_rows = [v for v in rows if v["lifecycle_state"] != "disposed"]
    return {
        "active": len(active_rows),
        "disposed": len(rows) - len(active_rows),
        "clear": sum(
            v["mot"]["state"] == "ok" and v["tax"]["state"] in ("ok", "sorn")
            for v in active_rows
        ),
        "unknown": sum(
            v["mot"]["state"] == "unknown" or v["tax"]["state"] == "unknown"
            for v in active_rows
        ),
        "total": len(rows),
        "mot_due": sum(v["mot"]["state"] == "due" for v in rows),
        "tax_due": sum(v["tax"]["state"] == "due" for v in rows),
        "mot_overdue": sum(v["mot"]["state"] == "overdue" for v in rows),
        "tax_overdue": sum(v["tax"]["state"] == "overdue" for v in rows),
        "attention": sum(
            v["mot"]["state"] in ("due", "overdue")
            or v["tax"]["state"] in ("due", "overdue")
            for v in rows
        ),
        "unchecked": sum(not v["last_checked_at"] for v in active_rows),
        "errors": sum(bool(v["last_error"]) for v in active_rows),
        "missing_email": sum(not v["email"] for v in active_rows),
    }


def company_groups(rows):
    """Return sorted company groups with per-company stats.

    Missing names belong to an explicit Unassigned group (key "").
    Group keys are case-insensitive, but displayed names retain original casing.
    """
    grouped = {}
    for vehicle in rows:
        raw_name = str(vehicle["company"] or "").strip()
        key = company_key(raw_name)
        if key not in grouped:
            grouped[key] = {
                "key": key,
                "name": raw_name or "Unassigned",
                "vehicles": [],
            }
        grouped[key]["vehicles"].append(vehicle)
    return [
        {
            "key": grouped[key]["key"],
            "name": grouped[key]["name"],
            "stats": fleet_stats(grouped[key]["vehicles"]),
        }
        for key in sorted(grouped, key=lambda k: (not bool(k), k))
    ]


def get_dashboard(db, today=None):
    rows = [view_vehicle(r, today) for r in db.execute(
        "SELECT * FROM vehicles ORDER BY registration").fetchall()]
    return {
        "vehicles": rows,
        "as_of": (today or date.today()).isoformat(),
        "stats": fleet_stats(rows),
        "companies": company_groups(rows),
        "dvla_configured": bool(os.environ.get("DVLA_API_KEY")),
        "smtp_configured": smtp_ready(),
    }


def dvla_query(vrm, key=None, client=requests):
    key = key if key is not None else os.environ.get("DVLA_API_KEY")
    if not key:
        raise RuntimeError("DVLA_API_KEY is not configured")
    try:
        response = client.post(
            DVLA_URL,
            json={"registrationNumber": registration(vrm)},
            headers={"x-api-key": key, "Accept": "application/json",
                     "Content-Type": "application/json"},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected DVLA response")
        return payload
    except requests.RequestException as exc:
        code = getattr(getattr(exc, "response", None), "status_code", None)
        raise RuntimeError("DVLA HTTP " + str(code or "network error")) from exc


def refresh_vehicle(db, vehicle_id, key=None, client=requests):
    vehicle = get_vehicle(db, vehicle_id)
    if not vehicle:
        raise LookupError("Vehicle not found")
    checked = utcnow()
    try:
        payload = dvla_query(vehicle["registration"], key, client)
    except (RuntimeError, ValueError) as exc:
        error = str(exc)[:160]
        db.execute("UPDATE vehicles SET last_checked_at=?, last_error=? WHERE id=?",
                   (checked, error, vehicle_id))
        db.execute("INSERT INTO checks(vehicle_id,checked_at,success,error) VALUES(?,?,0,?)",
                   (vehicle_id, checked, error))
        db.commit()
        return {"success": False, "error": error}
    mot_date = str(payload.get("motExpiryDate")) if iso_date(payload.get("motExpiryDate")) else None
    tax_date = str(payload.get("taxDueDate")) if iso_date(payload.get("taxDueDate")) else None
    db.execute("""
        UPDATE vehicles SET make=?, colour=?, fuel_type=?, year_of_manufacture=?,
            mot_status=?, mot_expiry_date=?, tax_status=?, tax_due_date=?,
            last_checked_at=?, last_error=NULL, updated_at=?
        WHERE id=?
    """, (str(payload.get("make") or vehicle["make"])[:140],
          str(payload.get("colour") or vehicle["colour"])[:140],
          str(payload.get("fuelType") or "")[:80],
          payload.get("yearOfManufacture") if isinstance(payload.get("yearOfManufacture"), int) else None,
          str(payload.get("motStatus") or "")[:80], mot_date,
          str(payload.get("taxStatus") or "")[:80], tax_date,
          checked, checked, vehicle_id))
    db.execute("""
        INSERT INTO checks(vehicle_id,checked_at,success,mot_expiry_date,tax_due_date)
        VALUES(?,?,1,?,?)
    """, (vehicle_id, checked, mot_date, tax_date))
    db.commit()
    return {"success": True}


def refresh_all(db, key=None, client=requests):
    result = {"total": 0, "success": 0, "failed": 0, "skipped_disposed": 0}
    for row in db.execute("SELECT * FROM vehicles ORDER BY registration").fetchall():
        if is_disposed(dict(row)):
            result["skipped_disposed"] += 1
            continue
        result["total"] += 1
        checked = refresh_vehicle(db, row["id"], key=key, client=client)
        result["success" if checked["success"] else "failed"] += 1
    return result


def reminder_stage(expiry, today=None):
    parsed = iso_date(expiry)
    if not parsed:
        return None
    days = (parsed - (today or date.today())).days
    return ("overdue" if days < 0 else "7-days" if days <= 7 else
            "14-days" if days <= 14 else "30-days" if days <= 30 else None)


def smtp_ready(env=None):
    env = os.environ if env is None else env
    return all(env.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_APP_PASSWORD", "SMTP_FROM"))


def smtp_send(recipient, subject, body, env=None):
    env = os.environ if env is None else env
    if not smtp_ready(env):
        raise RuntimeError("SMTP is not configured")
    msg = EmailMessage()
    msg["From"] = env["SMTP_FROM"]
    msg["To"] = email_address(recipient)
    msg["Subject"] = subject
    msg.set_content(body)
    host = env["SMTP_HOST"]
    port = int(env.get("SMTP_PORT", "587"))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
            smtp.login(env["SMTP_USER"], env["SMTP_APP_PASSWORD"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(env["SMTP_USER"], env["SMTP_APP_PASSWORD"])
            smtp.send_message(msg)


def reminders(db, today=None, dry_run=False, send=smtp_send, env=None):
    today = today or date.today()
    env = os.environ if env is None else env
    stats = {"sent": 0, "would_send": 0, "already_sent": 0,
             "missing_email": 0, "not_configured": 0, "failed": 0}
    for row in db.execute("SELECT * FROM vehicles").fetchall():
        v = dict(row)
        # Do not email about MOT or tax renewal while the vehicle is SORN.
        # Expiry dates remain stored, so reminders resume when it is taxed.
        if is_sorn(v["tax_status"]) or is_disposed(v, today):
            continue
        for kind, due in (("MOT", v["mot_expiry_date"]), ("Tax", v["tax_due_date"])):
            stage = reminder_stage(due, today)
            if not stage:
                continue
            if not v["email"]:
                stats["missing_email"] += 1
                continue
            present = db.execute("""
                SELECT 1 FROM notifications
                WHERE vehicle_id=? AND kind=? AND due_date=? AND stage=? AND recipient=?
            """, (v["id"], kind, due, stage, v["email"])).fetchone()
            if present:
                stats["already_sent"] += 1
                continue
            if dry_run:
                stats["would_send"] += 1
                continue
            if not smtp_ready(env):
                stats["not_configured"] += 1
                continue
            subject = "AutoKeeper: " + kind + " reminder for " + v["registration"]
            description = "expired on" if stage == "overdue" else "is due on"
            body = (
                "AutoKeeper vehicle reminder\n\n"
                "Registration: " + v["registration"] + "\n"
                "Vehicle: " + v["make"] + " " + v["model"] + "\n"
                + kind + " " + description + " " + due + ".\n\n"
                "Please verify the current record using the official GOV.UK service.\n"
                "This message is based on AutoKeeper's latest recorded check.\n"
            )
            try:
                send(v["email"], subject, body, env=env)
            except Exception:
                stats["failed"] += 1
                continue
            db.execute("""
                INSERT INTO notifications(vehicle_id,kind,due_date,stage,recipient,sent_at)
                VALUES(?,?,?,?,?,?)
            """, (v["id"], kind, due, stage, v["email"], utcnow()))
            db.commit()
            stats["sent"] += 1
    return stats
