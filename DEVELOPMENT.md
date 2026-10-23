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
| AUTO-011 | UDA identity mode using trusted user and group headers; Basic remains the standalone default | Implemented in source; live UDA smoke check pending |

The 45 rows in the source workbook are deliberately not committed. The original notebook may contain API key configuration, so it was not copied into Git. The remote DVLA key and authorised Gmail SMTP credentials must be deployed privately.

## Evidence rule

Code committed != CI tested != Ubuntu deployed != DVLA check successful != email delivered. Record each result separately after inspection.

| AUTO-012 | Excel upload HTTP 500 investigation | Added synthetic 45-vehicle full .xlsx upload regression; reported missing openpyxl, storage errors and invalid ZIP as actionable HTTP responses. Live UDA server not inspected; verify after deployment. |

| AUTO-013 | Group the dashboard and register by company | Source implementation: API company summaries, filter scoped dashboard KPIs, collapsible register headings, suggestions on vehicle form; CI and live Ubuntu validation to be recorded separately. |

| AUTO-014 | Suppress MOT due/overdue warnings for SORN vehicles | Source change and regression tests for MOT/tax badges, fleet/company counts, notification suppression and restoration after SORN ends. CI and live Ubuntu check separate. |

| AUTO-015 | Acquisition and disposal dates | Nullable SQLite lifecycle fields with idempotent schema migration; per-vehicle date inputs, grouped register columns, imports, disposed compliance/reminder handling and synthetic migration/API tests. Live Ubuntu rollout still requires deployment and smoke testing. |
