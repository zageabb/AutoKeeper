# AutoKeeper development register

Reference: private zageabb/Application-Standard template. Implementation branch: feature/initial-autokeeper-app.

| ID | Scope | Status |
|---|---|---|
| AUTO-001 | Vehicle CRUD / unique registration / recipient email | Implemented in source; tests included |
| AUTO-002 | Read Master spreadsheet and CSV import | Implemented; real workbook not imported to server |
| AUTO-003 | DVLA individual / fleet check | Implemented; live credentials not verified |
| AUTO-004 | Dashboard statistics and responsive UI | Implemented; live browser QA pending |
| AUTO-005 | Stage-based SMTP mail reminders, dedup and SORN rule | Implemented; real Gmail delivery not verified |
| AUTO-006 | Weekly systemd timer example | Documented only; not enabled |
| AUTO-007 | Protected API and Caddy prefix | Implemented; live UDA deployment not verified |
| AUTO-008 | GitHub CI tests | Pending workflow result |
| AUTO-009 | Security / visibility / real-data review | Pending |
| AUTO-010 | Extended MOT history and mileage/insurance stats | Backlog |

The 45 rows in the source workbook are deliberately not committed. The original notebook may contain API key configuration, so it was not copied into Git. The remote DVLA key and authorised Gmail SMTP credentials must be deployed privately.

## Evidence rule

Code committed != CI tested != Ubuntu deployed != DVLA check successful != email delivered. Record each result separately after inspection.
