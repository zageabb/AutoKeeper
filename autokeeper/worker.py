"""Weekly scheduled task: python -m autokeeper.worker [--dry-run]."""
import argparse
import json
from .core import init_db, open_db, refresh_all, reminders


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Do not send email")
    p.add_argument("--reminders-only", action="store_true")
    args = p.parse_args()
    db = open_db()
    try:
        init_db(db)
        checks = None if args.reminders_only else refresh_all(db)
        notifications = reminders(db, dry_run=args.dry_run)
        print(json.dumps({"checks": checks, "reminders": notifications}, indent=2))
        return 1 if (checks and checks["failed"]) or (
            notifications["failed"] or notifications["not_configured"]) else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
