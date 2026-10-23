# AutoKeeper

**Your vehicles. Your records. Your reminders.**

A self-hosted UK vehicle register for Ubuntu/UDA. AutoKeeper stores cars, owners and per-vehicle email recipients, checks DVLA vehicle details, displays MOT/tax expiry statistics and sends due-date reminders.

## Capabilities

- Add, edit, delete and search vehicles; record registration, owner, company, recipient email, make/model and colour.
- Import the supplied Master Car List-ga.xlsx (sheet Master) or CSV, including Employee Name and Email Address.
- Individual and fleet-wide DVLA Vehicle Enquiry Service checks; regular checks using systemd.
- Dashboard counts for vehicles, MOT due, road tax due, overdue and missing emails.
- SMTP reminders at 30, 14, 7 days and overdue; per-vehicle recipient, persistent deduplication log; SORN tax excluded.
- HTTP Basic authentication for standalone installs, or UDA user and group authentication behind the authenticated reverse proxy; read/write API separation and unit/API tests.

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
# Keep AUTOKEEPER_AUTH_MODE=basic and set a strong APP_ADMIN_PASSWORD for standalone use
set -a; . ./.env; set +a
uvicorn autokeeper.server:app --host 127.0.0.1 --port 5064
~~~

For standalone use, open http://127.0.0.1:5064/ with the HTTP Basic credentials from the environment. For UDA, set AUTOKEEPER_AUTH_MODE=uda and AUTOKEEPER_ROOT_PATH=/apps/autokeeper; Caddy supplies the authenticated X-UDA-User and X-UDA-Groups headers after checking the user's UDA access. The app accepts users in Personal and UDA admins. Keep Uvicorn bound to loopback and follow docs/UBUNTU_DEPLOYMENT.md.

Upload Master Car List-ga.xlsx using **Import vehicles**. Existing VRMs are updated, not duplicated. Real employee details remain in the private SQLite store, not in version control. The app imports the master vehicle and recipient columns; it then retrieves authoritative statuses from DVLA if credentials are configured. The optional dvla check.xlsx Results sheet can also be imported to show historical MOT/tax dates as an unverified snapshot; a later live DVLA check supersedes it.

Use **Check DVLA** to refresh all vehicles or use the circular refresh button against one car. The API key must be placed in DVLA_API_KEY, not in source files. Some DVLA records do not provide MOT expiry data; those dates are shown as unknown.

**Preview reminders** in the footer evaluates due reminders but does not send mail. The weekly worker is:

~~~bash
python -m autokeeper.worker --dry-run
python -m autokeeper.worker
~~~

The second command can send actual emails, but only after SMTP is configured and the sender has been authorised.

## Deployment and security

See docs/UBUNTU_DEPLOYMENT.md for a loopback Uvicorn service, authenticated UDA/Caddy reverse proxy and weekly systemd timer (default Monday 08:00 Europe/London). A GitHub commit does not deploy the service, set up the DVLA key or authorise Gmail email delivery.

Use AUTOKEEPER_AUTH_MODE=uda behind UDA or AUTOKEEPER_AUTH_MODE=basic for standalone access. APP_ADMIN_PASSWORD is required in basic mode; DVLA_API_KEY is for VES; SMTP_APP_PASSWORD plus SMTP_USER and SMTP_FROM for the privately configured sender email. A connected Gmail account in ChatGPT does not configure Ubuntu SMTP.

Tests: python -m compileall -q autokeeper tests && python -m pytest tests -q.

## Reference and project controls

- DEVELOPMENT.md — scope and evidence.
- DID.md — architecture and decisions.
- AGENTS.md — development safeguards.
- docs/UBUNTU_DEPLOYMENT.md — install, Caddy, systemd timer, backup.
- examples/vehicles_sample.csv — entirely synthetic test data.
- DVLA VES API: https://developer-portal.driver-vehicle-licensing.api.gov.uk/apis/vehicle-enquiry-service/vehicle-enquiry-service-description.html

DVLA Vehicle Enquiry is separate from the optional DVSA MOT History API. For critical compliance decisions, confirm against official GOV.UK services.


UDA service port: 5092 on 127.0.0.1. Direct LAN access to port 5092 is intentionally disabled in UDA authentication mode. Use the authenticated /apps/autokeeper/ URL. See docs/UBUNTU_DEPLOYMENT.md.


### Troubleshooting Excel import

For an import error, update the server venv dependencies: `cd /opt/autokeeper && .venv/bin/python -m pip install -r requirements.txt` then `sudo systemctl restart autokeeper.service`. The real path is the service `WorkingDirectory`/`ExecStart` in `sudo systemctl cat autokeeper.service`. An Excel file with a `Master` worksheet, normal registration/email columns and optional historical DVLA dates should upload successfully. If an error persists, inspect `sudo journalctl -u autokeeper.service -n 100 --no-pager`, redacting emails and tokens before sharing logs. A repeat import updates matching registrations, not duplicates.


## Company grouping

The dashboard starts on **All companies** and groups the vehicle table under collapsible Company headings, each with the number of vehicles, MOT and tax renewals due/overdue, and those needing attention. Select a company above the summary cards to view company-only dashboard statistics and vehicle records. The search and compliance filters continue working inside that company; return to All companies to see the full fleet. Company matching is case-insensitive and ignores leading/trailing spaces. Blank company values are shown under **Unassigned**, and the Add Vehicle dialog offers existing company names for consistency. DVLA refresh-all and the weekly reminder worker still act on every registered vehicle, regardless of the screen filter. This is grouping/filtering, **not company-based access control**.


### SORN and MOT display

When DVLA reports a vehicle as **SORN**, the dashboard and company register
show **SORN** for both MOT and tax, rather than due or overdue warnings.
The actual MOT expiry date and DVLA MOT status remain stored and visible as
reference; SORN does **not** renew or validate an expired MOT. Such vehicles
are not counted as road-ready in the fleet health percentage. The weekly
reminder worker also suppresses MOT and tax expiry emails while SORN. As soon
as a later DVLA check reports the vehicle is no longer SORN, MOT and tax
expiry warnings and reminders follow their normal rules again. Check the
vehicle has a valid MOT before returning it to road use.


## Acquisition and disposal dates

Every vehicle now has optional Acquisition Date and Disposal Date fields (stored in ISO YYYY-MM-DD format; the browser uses native date pickers). The vehicle register shows both dates and a Disposed badge for vehicles already disposed of; the filters include Active vehicles and Disposed vehicles. A future disposal date appears as Scheduled and has no effect until that date.

- A disposed vehicle remains in its company group for history; it is not deleted.
- Fleet and company summaries show active and disposed counts; MOT/tax warnings and missing-recipient alerts cover only active vehicles.
- The weekly DVLA sweep and reminder worker skip disposed vehicles; individual historical DVLA data is retained. Manual DVLA refresh remains possible.
- Reopen a vehicle by clearing its disposal date in Edit.
- CSV/Excel import recognises Acquisition Date, Acquired Date, Date Acquired, Disposal Date, Disposed Date and Date Disposed, including ISO and UK date formats. Blank cells do not erase existing dates, and disposal before acquisition is rejected.
- Existing SQLite files are migrated automatically: two nullable date columns are added on startup without replacing rows. Back up the database before upgrading.

This records ownership history only. It does not change DVLA keeper data or submit disposal paperwork to DVLA.


## DVLA checks after vehicle disposal

Disposed vehicles can still be checked against the DVLA Vehicle Enquiry Service. Use the circular refresh icon beside one disposed registration or click **Check disposed** to look up all disposed registrations. **Check active** continues to check active vehicles only, and the weekly systemd worker remains active-only. The register displays the latest MOT expiry/status and tax due/status for disposed registrations, with the raw DVLA status beneath each date. Ownership/disposal dates are never modified by a DVLA lookup. The vehicle stays marked Disposed and is excluded from MOT/tax compliance alert totals, automatic weekly checks and emailed reminders. Failed lookups retain previous results and show a check error. A record of a taxed vehicle or valid MOT is not evidence that it was physically on the road; it only reports DVLA status as of the lookup. Use the Disposed vehicles filter to review them.
