"""Excel/CSV importer for the uploaded Master Car List layout."""
import csv
import io
import sqlite3

from .core import registration, save_vehicle

MAX_IMPORT = 6 * 1024 * 1024


def value(row, *names):
    lookup = {str(k).strip().casefold(): v for k, v in row.items() if k is not None}
    for name in names:
        cell = lookup.get(name.casefold())
        if cell is not None and str(cell).strip():
            return str(cell).strip()
    return ""


def read_import(data, filename):
    if len(data) > MAX_IMPORT:
        raise ValueError("Import files are limited to 6 MB.")
    if filename.lower().endswith(".csv"):
        return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    if filename.lower().endswith(".xlsx"):
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            sheet = book["Master"] if "Master" in book.sheetnames else book.active
            lines = sheet.iter_rows(values_only=True)
            try:
                header = [str(c or "").strip() for c in next(lines)]
            except StopIteration as exc:
                raise ValueError("Spreadsheet is empty") from exc
            return [dict(zip(header, line)) for line in lines]
        finally:
            book.close()
    raise ValueError("Please select a .xlsx or .csv file.")


def import_vehicles(db, rows):
    result = {"created": 0, "updated": 0, "skipped": 0, "errors": []}
    for row_number, row in enumerate(rows, start=2):
        vrm = value(row, "Registration No", "registrationNumber", "Registration", "VRM")
        if not vrm:
            result["skipped"] += 1
            continue
        try:
            vrm = registration(vrm)
            incoming = {
                "registration": vrm,
                "owner": value(row, "Employee Name", "Owner", "Driver"),
                "company": value(row, "Company"),
                "email": value(row, "Email Address", "Email", "Recipient"),
                "make": value(row, "Make", "dvla_make"),
                "model": value(row, "Model", "dvla_Model"),
                "colour": value(row, "Colour"),
            }
            current = db.execute("SELECT * FROM vehicles WHERE registration=?",
                                 (vrm,)).fetchone()
            if current:
                # Blank import cells must not discard existing driver/contact data.
                merged = dict(current)
                merged.update({k: v for k, v in incoming.items() if v})
                save_vehicle(db, merged, current["id"])
                result["updated"] += 1
            else:
                save_vehicle(db, incoming)
                result["created"] += 1
        except (ValueError, sqlite3.IntegrityError) as exc:
            result["skipped"] += 1
            if len(result["errors"]) < 20:
                result["errors"].append({"row": row_number, "reason": str(exc)})
    return result
