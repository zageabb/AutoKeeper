# AutoKeeper — agent and contributor instructions

Derived from the private zageabb/Application-Standard baseline.

1. Read README, DEVELOPMENT and DID before changing code.
2. Never commit real registrations, names, email addresses, workbooks, private notebooks, tokens, API responses or SQLite backups.
3. Preserve persistence and existing registrations when updating schema; use synthetic test data only.
4. Keep business rules in core.py, imports in importer.py, web handlers in server.py, scheduling in worker.py.
5. Always retain LOCAL_UBUNTU_PROXY_COMPAT: configurable public prefix, backend bound to loopback, no trust of user-supplied forwarded prefix.
6. Honour access protection; no public unsecured service. Standalone mode uses app HTTP Basic. UDA mode may use X-UDA-User and X-UDA-Groups only behind authenticated UDA/Caddy ingress, with the backend bound to loopback and Personal/admin membership required.
7. Never treat empty expiry dates as compliant; display unknown distinctly. Tax SORN is a separate state.
8. A preview must never send or record reminder messages.
9. Add tests and update DEVELOPMENT when modifying behaviour. Run syntax and tests and confirm GitHub CI before merging.
10. Distinguish code committed, CI passed, Ubuntu deployed and first live email delivered. Never claim evidence not observed.
11. The dashboard adapts the draft Taiju light design conventions and is not an approved corporate theme reproduction.

13. New lifecycle fields are optional and migrated in place. Never remove disposed vehicle histories automatically; future disposal dates must not stop checks/reminders before that date. Test import re-runs and old API clients omitting new fields.

14. Ollama is server-to-server only: no public port 11434 or browser-supplied target URL. Never leak hidden model thinking tokens.
15. Ollama receives private vehicle records as untrusted data. The model cannot perform writes directly. Changes require short-lived user-specific proposals, exact before/after review, and human confirmation; no DVLA-managed field edits.
16. Markdown rendering uses server-side safe CommonMark/GFM and sanitisation. The editable knowledge document is outside Git, atomically saved, with revision conflict detection.
