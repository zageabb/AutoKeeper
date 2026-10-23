# AutoKeeper decision and implementation log

**DID-001 — Small P2 application:** FastAPI with Jinja + vanilla JS, SQLite and systemd timer. The Application-Standard P1 enterprise preference is React/MUI + FastAPI/PostgreSQL, but this is a small self-hosted fleet utility. Upgrade path is open; no enterprise services are falsely presented as available.

**DID-002 — Live data:** DVLA VES POST /vehicle-enquiry/v1/vehicles with x-api-key, never from browser. VES may return MOT expiry/status and tax due/status, but does not supply DVSA MOT test history/advisories. A failed DVLA check retains prior dates with a visible last_error.

**DID-003 — Reminders:** Stage at 30, 14, 7 days and overdue, with unique key (vehicle, kind, due date, stage, recipient); no duplicate within a stage. A weekly run might skip exact calendar threshold days. Tax SORN never triggers an ordinary due reminder.

**DID-004 — Security:** HTTP Basic application gate and a separate UDA/Caddy HTTPS access gate; host backend on 127.0.0.1, never public HTTP. Mutations require same-origin custom header. No role separation in initial single-admin version.

**DID-005 — Data:** Never commit user workbooks or secrets. Persist only necessary vehicle, check and delivery fields to SQLite in a restricted directory. Require a data retention/backup decision before production import.
