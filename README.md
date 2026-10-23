# AutoKeeper

**Your vehicles. Your records. Your reminders.**

A self-hosted UK vehicle register for Ubuntu/UDA. AutoKeeper stores cars, owners and per-vehicle email recipients, checks DVLA vehicle details, displays MOT/tax expiry statistics and sends due-date reminders.

## Capabilities

- Add, edit, delete and search vehicles; record registration, owner, company, recipient email, make/model and colour.
- Import the supplied Master Car List-ga.xlsx (sheet Master) or CSV, including Employee Name and Email Address.
- Individual and fleet-wide DVLA Vehicle Enquiry Service checks; regular checks using systemd.
- Dashboard counts for vehicles, MOT due, road tax due, overdue and missing emails.
- SMTP reminders at 30, 14, 7 days and overdue; per-vehicle recipient, persistent deduplication log; SORN tax excluded.
- HTTP Basic authentication, read/write API separation and unit/API tests.

**Important:** The uploaded 45-vehicle list and DVLA notebook are not in Git. Keep the real workbook, recipient addresses, DVLA key and Gmail credentials off GitHub. This repository was public when the initial code was committed. Private visibility is recommended.

## Getting started

Python 3.11+ is recommended.

~~~bash
git clone https://github.com/zageabb/AutoKeeper.git
cd AutoKeeper
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Privately edit .env with a strong APP_ADMIN_PASSWORD and other credentials
set -a; . ./.env; set +a
uvicorn autokeeper.server:app --host 127.0.0.1 --port 5064
~~~

Open http://127.0.0.1:5064/ using the HTTP Basic username/password from the environment. For localhost use AUTOKEEPER_ROOT_PATH empty; for the UDA/Caddy prefix set AUTOKEEPER_ROOT_PATH=/apps/autokeeper and follow docs/UBUNTU_DEPLOYMENT.md.

Upload Master Car List-ga.xlsx using **Import vehicles**. Existing VRMs are updated, not duplicated. Real employee details remain in the private SQLite store, not in version control. The app imports the master vehicle and recipient columns; it then retrieves authoritative statuses from DVLA if credentials are configured. A second DVLA results import is not required.

Use **Check DVLA** to refresh all vehicles or use the circular refresh button against one car. The API key must be placed in DVLA_API_KEY, not in source files. Some DVLA records do not provide MOT expiry data; those dates are shown as unknown.

**Preview reminders** in the footer evaluates due reminders but does not send mail. The weekly worker is:

~~~bash
python -m autokeeper.worker --dry-run
python -m autokeeper.worker
~~~

The second command can send actual emails, but only after SMTP is configured and the sender has been authorised.

## Deployment and security

See docs/UBUNTU_DEPLOYMENT.md for a loopback Uvicorn service, authenticated UDA/Caddy reverse proxy and weekly systemd timer (default Monday 08:00 Europe/London). A GitHub commit does not deploy the service, set up the DVLA key or authorise Gmail email delivery.

Use APP_ADMIN_PASSWORD for app access; DVLA_API_KEY for VES; SMTP_APP_PASSWORD plus SMTP_USER and SMTP_FROM for email. A connected Gmail account in ChatGPT does not configure Ubuntu SMTP.

Tests: python -m compileall -q autokeeper tests && python -m pytest tests -q.

## Reference and project controls

- DEVELOPMENT.md — scope and evidence.
- DID.md — architecture and decisions.
- AGENTS.md — development safeguards.
- docs/UBUNTU_DEPLOYMENT.md — install, Caddy, systemd timer, backup.
- examples/vehicles_sample.csv — entirely synthetic test data.
- DVLA VES API: https://developer-portal.driver-vehicle-licensing.api.gov.uk/apis/vehicle-enquiry-service/vehicle-enquiry-service-description.html

DVLA Vehicle Enquiry is separate from the optional DVSA MOT History API. For critical compliance decisions, confirm against official GOV.UK services.
