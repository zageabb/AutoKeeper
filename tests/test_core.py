"""Tests use only invented registrations and addresses; no external services."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from autokeeper import core
from autokeeper.importer import import_vehicles


class AutoKeeperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = core.open_db(str(Path(self.temp.name) / "test.sqlite"))
        core.init_db(self.db)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add(self, vrm="AA00AAA", email="synthetic@example.org"):
        return core.save_vehicle(self.db, {
            "registration": vrm, "owner": "Test Driver", "email": email,
            "company": "Demo", "make": "Example", "model": "Car", "colour": "Blue"
        })


    def test_schema_migration_preserves_existing_vehicle(self):
        import sqlite3
        from pathlib import Path
        other = sqlite3.connect(str(Path(self.temp.name) / "old.sqlite"))
        other.row_factory = sqlite3.Row
        try:
            other.execute("""
                CREATE TABLE vehicles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    registration TEXT NOT NULL UNIQUE,
                    company TEXT NOT NULL DEFAULT ''
                )
            """)
            other.execute("INSERT INTO vehicles(registration,company) VALUES(?,?)",
                          ("AA00OLD", "Legacy"))
            other.commit()
            core.init_db(other)
            core.init_db(other)
            columns = {r["name"] for r in other.execute("PRAGMA table_info(vehicles)")}
            self.assertTrue({"acquisition_date", "disposal_date"} <= columns)
            old = other.execute("SELECT * FROM vehicles WHERE registration='AA00OLD'").fetchone()
            self.assertEqual(old["company"], "Legacy")
            self.assertIsNone(old["disposal_date"])
        finally:
            other.close()

    def test_registration_normalisation(self):
        self.assertEqual(core.registration("aa 00 aaa"), "AA00AAA")
        with self.assertRaises(ValueError):
            core.registration("@!!")

    def test_unknown_dates_not_counted_as_clear(self):
        self.add()
        metrics = core.get_dashboard(self.db)["stats"]
        self.assertEqual(metrics["total"], 1)
        self.assertEqual(metrics["unknown"], 1)
        self.assertEqual(metrics["clear"], 0)

    def test_company_groups_and_fleet_totals(self):
        from autokeeper.core import company_groups, view_vehicle
        self.add("AB12ABC")
        self.add("XY34XYZ")
        self.add("CD56CDE")
        self.add("EF78EFG")
        self.db.execute("UPDATE vehicles SET company='  ALPHA ', "
                        "mot_expiry_date='2026-11-05', tax_due_date='2027-05-01' "
                        "WHERE registration='AB12ABC'")
        self.db.execute("UPDATE vehicles SET company='alpha', "
                        "mot_expiry_date='2026-11-09', tax_due_date='2026-10-20' "
                        "WHERE registration='XY34XYZ'")
        self.db.execute("UPDATE vehicles SET company='Beta', "
                        "mot_expiry_date='2027-05-01', tax_due_date='2027-05-01' "
                        "WHERE registration='CD56CDE'")
        self.db.execute("UPDATE vehicles SET company='   ', "
                        "mot_expiry_date=NULL, tax_due_date=NULL "
                        "WHERE registration='EF78EFG'")
        self.db.commit()
        day = date(2026, 10, 23)
        rows = [view_vehicle(r, day) for r in self.db.execute("SELECT * FROM vehicles")]
        companies = company_groups(rows)
        self.assertEqual([group["key"] for group in companies],
                         ["alpha", "beta", ""])
        self.assertEqual(companies[0]["stats"]["total"], 2)
        self.assertEqual(companies[0]["stats"]["mot_due"], 2)
        self.assertEqual(companies[0]["stats"]["tax_overdue"], 1)
        self.assertEqual(companies[-1]["name"], "Unassigned")
        self.assertEqual(companies[-1]["stats"]["unknown"], 1)
        self.assertEqual(sum(c["stats"]["total"] for c in companies), len(rows))


    def test_acquisition_disposal_date_validation_and_edit(self):
        created = core.save_vehicle(self.db, {
            "registration": "AB12XYZ", "company": "Example",
            "acquisition_date": "23/10/2024", "disposal_date": "2027-10-24",
        })
        self.assertEqual(created["acquisition_date"], "2024-10-23")
        self.assertEqual(created["disposal_date"], "2027-10-24")
        self.assertEqual(core.view_vehicle(created, date(2026, 10, 23))["lifecycle_state"],
                         "scheduled")
        unchanged = core.save_vehicle(self.db, {"registration": "AB12XYZ"}, created["id"])
        self.assertEqual(unchanged["acquisition_date"], "2024-10-23")
        self.assertEqual(unchanged["disposal_date"], "2027-10-24")
        cleared = core.save_vehicle(self.db, {
            "registration": "AB12XYZ", "disposal_date": ""
        }, created["id"])
        self.assertIsNone(cleared["disposal_date"])
        self.assertEqual(cleared["acquisition_date"], "2024-10-23")
        with self.assertRaisesRegex(ValueError, "before acquisition"):
            core.save_vehicle(self.db, {
                "registration": "AB12XYZ",
                "acquisition_date": "2025-01-01",
                "disposal_date": "2024-12-01",
            }, created["id"])
        with self.assertRaisesRegex(ValueError, "Invalid lifecycle date"):
            core.save_vehicle(self.db, {
                "registration": "AB12XYZ", "acquisition_date": "31/02/2026"
            }, created["id"])
        self.assertIsNone(core.get_vehicle(self.db, created["id"])["disposal_date"])

    def test_disposed_vehicle_suppresses_notifications_and_refresh(self):
        from unittest.mock import Mock
        vehicle = core.save_vehicle(self.db, {
            "registration": "AA00ABC", "company": "Example",
            "email": "synthetic@example.org", "acquisition_date": "2024-03-01",
            "disposal_date": "2026-10-01"
        })
        core.save_vehicle(self.db, {
            "registration": "BB11ABC", "company": "Example",
            "email": "synthetic@example.org"
        })
        self.db.execute("""
            UPDATE vehicles SET mot_expiry_date='2026-10-01',
               tax_due_date='2026-10-01' WHERE id=?
        """, (vehicle["id"],))
        self.db.commit()
        day = date(2026, 10, 23)
        dashboard = core.get_dashboard(self.db, today=day)
        disposed = next(v for v in dashboard["vehicles"] if v["id"] == vehicle["id"])
        self.assertEqual(disposed["lifecycle_state"], "disposed")
        self.assertEqual(disposed["mot"]["state"], "overdue")
        self.assertEqual(disposed["mot_expiry_date"], "2026-10-01")
        self.assertEqual(dashboard["stats"]["active"], 1)
        self.assertEqual(dashboard["stats"]["disposed"], 1)
        self.assertEqual(dashboard["stats"]["mot_overdue"], 0)
        self.assertEqual(dashboard["stats"]["attention"], 0)
        self.assertEqual(dashboard["companies"][0]["stats"]["disposed"], 1)
        self.assertEqual(core.reminders(self.db, today=day, dry_run=True)["would_send"], 0)
        response = Mock()
        response.json.return_value = {
            "make": "Example", "taxStatus": "Taxed",
            "motExpiryDate": "2027-01-01", "taxDueDate": "2027-06-01",
        }
        response.raise_for_status.return_value = None
        client = Mock()
        client.post.return_value = response
        result = core.refresh_all(self.db, key="test-only", client=client)
        self.assertEqual(result, {"total": 1, "success": 1,
                                  "failed": 0, "skipped_disposed": 1})
        client.post.assert_called_once()
        self.assertEqual(core.get_vehicle(self.db, vehicle["id"])["mot_expiry_date"],
                         "2026-10-01")
        self.db.execute("UPDATE vehicles SET disposal_date=NULL WHERE id=?",
                        (vehicle["id"],))
        self.db.commit()
        self.assertEqual(core.reminders(self.db, today=day, dry_run=True)["would_send"], 2)

    def test_explicit_disposed_batch_refresh_and_active_only_default(self):
        from unittest.mock import Mock
        disposed = core.save_vehicle(self.db, {
            "registration": "ZZ20ZZZ", "company": "Historical",
            "disposal_date": "2025-01-01"
        })
        active = core.save_vehicle(self.db, {
            "registration": "YY21YYY", "company": "Historical"
        })
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "make": "Example", "taxStatus": "Taxed", "motStatus": "Valid",
            "motExpiryDate": "2027-02-01", "taxDueDate": "2027-04-01",
        }
        client = Mock()
        client.post.return_value = response
        manual = core.refresh_all(self.db, key="fake", client=client,
                                  scope="disposed")
        self.assertEqual(manual["total"], 1)
        self.assertEqual(manual["success"], 1)
        self.assertEqual(manual["skipped_active"], 1)
        self.assertEqual(client.post.call_count, 1)
        self.assertEqual(client.post.call_args.kwargs["json"]["registrationNumber"], "ZZ20ZZZ")
        historical = core.view_vehicle(core.get_vehicle(self.db, disposed["id"]),
                                       date(2026, 10, 23))
        self.assertEqual(historical["lifecycle_state"], "disposed")
        self.assertEqual(historical["mot_status"], "Valid")
        self.assertEqual(historical["tax_status"], "Taxed")
        self.assertEqual(historical["mot"]["state"], "ok")
        self.assertEqual(historical["tax"]["state"], "ok")
        self.assertEqual(core.get_vehicle(self.db, active["id"])["last_checked_at"], None)
        self.assertEqual(core.fleet_stats([historical])["attention"], 0)
        self.assertEqual(core.fleet_stats([historical])["clear"], 0)

        weekly = core.refresh_all(self.db, key="fake", client=client)
        self.assertEqual(weekly["total"], 1)
        self.assertEqual(weekly["skipped_disposed"], 1)
        self.assertEqual(client.post.call_count, 2)
        self.assertEqual(client.post.call_args.kwargs["json"]["registrationNumber"], "YY21YYY")
        with self.assertRaisesRegex(ValueError, "scope"):
            core.refresh_all(self.db, scope="bad")

    def test_disposed_overdue_is_visible_but_not_an_active_warning(self):
        record = core.save_vehicle(self.db, {
            "registration": "AA22AAA", "disposal_date": "2025-06-01",
            "email": "test@example.org"
        })
        self.db.execute("""
            UPDATE vehicles SET mot_expiry_date='2025-02-01',
                tax_due_date='2025-03-01', tax_status='Taxed'
            WHERE id=?
        """, (record["id"],))
        self.db.commit()
        snapshot = core.get_dashboard(self.db, date(2026, 10, 23))
        vehicle = snapshot["vehicles"][0]
        self.assertEqual(vehicle["lifecycle_state"], "disposed")
        self.assertEqual(vehicle["mot"]["state"], "overdue")
        self.assertEqual(vehicle["tax"]["state"], "overdue")
        self.assertEqual(snapshot["stats"]["mot_overdue"], 0)
        self.assertEqual(snapshot["stats"]["tax_overdue"], 0)
        self.assertEqual(snapshot["stats"]["attention"], 0)
        self.assertEqual(snapshot["companies"][0]["stats"]["attention"], 0)
        self.assertEqual(core.reminders(self.db, today=date(2026, 10, 23),
                                         dry_run=True)["would_send"], 0)

    def test_lifecycle_import_and_repeat_preserves_existing_dates(self):
        rows = [{
            "Registration No": "ZZ99AAA",
            "Acquisition Date": "01/02/2021",
            "Disposal Date": "2026-10-20 00:00:00",
        }]
        self.assertEqual(import_vehicles(self.db, rows)["created"], 1)
        v = dict(self.db.execute("SELECT * FROM vehicles WHERE registration='ZZ99AAA'").fetchone())
        self.assertEqual(v["acquisition_date"], "2021-02-01")
        self.assertEqual(v["disposal_date"], "2026-10-20")
        self.assertEqual(import_vehicles(self.db, [{
            "Registration No": "ZZ99AAA", "Acquisition Date": "",
            "Disposal Date": "", "Make": "Sample"
        }])["updated"], 1)
        updated = dict(self.db.execute("SELECT * FROM vehicles WHERE registration='ZZ99AAA'").fetchone())
        self.assertEqual(updated["acquisition_date"], "2021-02-01")
        self.assertEqual(updated["disposal_date"], "2026-10-20")
        failed = import_vehicles(self.db, [{
            "Registration No": "AA11BAD", "Acquisition Date": "2024-09-05",
            "Disposal Date": "2024-01-01",
        }])
        self.assertEqual(failed["skipped"], 1)
        self.assertEqual(failed["created"], 0)

    def test_due_dates(self):
        today = date(2026, 10, 23)
        self.assertEqual(core.status("2026-11-02", today)["state"], "due")
        self.assertEqual(core.status("2026-10-20", today)["state"], "overdue")
        self.assertEqual(core.status(None, today)["state"], "unknown")
        self.assertEqual(core.reminder_stage("2026-11-20", today), "30-days")
        self.assertEqual(core.reminder_stage("2026-11-04", today), "14-days")
        self.assertEqual(core.reminder_stage("2026-10-25", today), "7-days")

    def test_dvla_refresh_success(self):
        vehicle = self.add()
        response = Mock()
        response.json.return_value = {
            "make": "EXAMPLE", "motStatus": "Valid",
            "motExpiryDate": "2026-11-22",
            "taxStatus": "Taxed", "taxDueDate": "2027-04-01"
        }
        response.raise_for_status.return_value = None
        client = Mock()
        client.post.return_value = response
        result = core.refresh_vehicle(self.db, vehicle["id"], key="test-key", client=client)
        self.assertTrue(result["success"])
        client.post.assert_called_once()
        self.assertEqual(core.get_vehicle(self.db, vehicle["id"])["mot_expiry_date"],
                         "2026-11-22")

    def test_sorn_suppresses_mot_overdue_without_losing_expiry(self):
        vehicle = self.add()
        self.db.execute("""
            UPDATE vehicles
            SET company='Off Road', mot_status='Expired',
                mot_expiry_date='2026-10-01', tax_status=' SORN ',
                tax_due_date='2026-09-01'
            WHERE id=?
        """, (vehicle["id"],))
        self.db.commit()
        today = date(2026, 10, 23)
        v = core.view_vehicle(core.get_vehicle(self.db, vehicle["id"]), today)
        self.assertEqual(v["mot"]["state"], "sorn")
        self.assertEqual(v["tax"]["state"], "sorn")
        self.assertEqual(v["mot_expiry_date"], "2026-10-01")
        self.assertEqual(v["tax_due_date"], "2026-09-01")
        self.assertEqual(v["mot_status"], "Expired")
        stats = core.fleet_stats([v])
        self.assertEqual(stats["mot_overdue"], 0)
        self.assertEqual(stats["mot_due"], 0)
        self.assertEqual(stats["tax_overdue"], 0)
        self.assertEqual(stats["attention"], 0)
        self.assertEqual(stats["clear"], 0)  # SORN isn't road-ready.
        companies = core.company_groups([v])
        self.assertEqual(companies[0]["stats"]["attention"], 0)

        # A live DVLA update to Taxed restores MOT and tax expiry warnings.
        self.db.execute("UPDATE vehicles SET tax_status='Taxed' WHERE id=?",
                        (vehicle["id"],))
        self.db.commit()
        road = core.view_vehicle(core.get_vehicle(self.db, vehicle["id"]), today)
        self.assertEqual(road["mot"]["state"], "overdue")
        self.assertEqual(road["tax"]["state"], "overdue")
        self.assertEqual(core.fleet_stats([road])["attention"], 1)

    def test_sorn_suppresses_upcoming_mot(self):
        vehicle = self.add()
        self.db.execute("""
            UPDATE vehicles SET tax_status='SORN', mot_expiry_date='2026-11-02'
            WHERE id=?
        """, (vehicle["id"],))
        self.db.commit()
        v = core.view_vehicle(core.get_vehicle(self.db, vehicle["id"]),
                              date(2026, 10, 23))
        self.assertEqual(v["mot"]["state"], "sorn")
        self.assertEqual(core.fleet_stats([v])["mot_due"], 0)

    def test_reminder_dedup_and_sorn(self):
        vehicle = self.add()
        self.db.execute("""
            UPDATE vehicles SET mot_expiry_date='2026-11-15',
                tax_due_date='2026-11-15', tax_status='SORN' WHERE id=?
        """, (vehicle["id"],))
        self.db.commit()
        sent = []

        def fake_send(to, subject, message, env):
            sent.append((to, subject, message))
        config = {"SMTP_HOST": "fake", "SMTP_USER": "fake",
                  "SMTP_APP_PASSWORD": "fake", "SMTP_FROM": "fake@example.org"}
        # SORN suppresses both tax and MOT messages without recording sends.
        one = core.reminders(self.db, today=date(2026, 10, 23),
                             send=fake_send, env=config)
        self.assertEqual(one["sent"], 0)
        self.assertEqual(one["already_sent"], 0)
        self.assertEqual(core.reminders(self.db, today=date(2026, 10, 23),
                                         dry_run=True)["would_send"], 0)
        self.assertEqual(len(sent), 0)

        # On return to taxed status the underlying expiry dates still apply.
        self.db.execute("UPDATE vehicles SET tax_status='Taxed' WHERE id=?",
                        (vehicle["id"],))
        self.db.commit()
        two = core.reminders(self.db, today=date(2026, 10, 23),
                             send=fake_send, env=config)
        three = core.reminders(self.db, today=date(2026, 10, 23),
                               send=fake_send, env=config)
        self.assertEqual(two["sent"], 2)
        self.assertEqual(three["already_sent"], 2)
        self.assertEqual(len(sent), 2)

    def test_import_dvla_snapshot_is_not_a_live_check(self):
        from autokeeper.importer import import_vehicles
        result = import_vehicles(self.db, [{
            "registrationNumber": "CC22CCC", "make": "Example",
            "motStatus": "Valid", "motExpiryDate": "2026-11-25",
            "taxStatus": "Taxed", "taxDueDate": "2027-01-12"
        }])
        self.assertEqual(result["created"], 1)
        row = self.db.execute("SELECT * FROM vehicles WHERE registration='CC22CCC'").fetchone()
        self.assertEqual(row["mot_expiry_date"], "2026-11-25")
        self.assertIsNone(row["last_checked_at"])

    def test_import_master_columns_and_duplicates(self):
        row = {"Registration No": "ZZ99 ZZZ", "Email Address": "test@example.org",
               "Employee Name": "A Driver", "Make ": "Test", "Model": "X"}
        self.assertEqual(import_vehicles(self.db, [row])["created"], 1)
        self.assertEqual(import_vehicles(self.db, [row])["updated"], 1)
        data = self.db.execute("SELECT * FROM vehicles WHERE registration='ZZ99ZZZ'").fetchone()
        self.assertEqual(data["owner"], "A Driver")
        self.assertEqual(data["email"], "test@example.org")


if __name__ == "__main__":
    unittest.main()
