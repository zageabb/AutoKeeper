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

    def test_registration_normalisation(self):
        self.assertEqual(core.registration("aa 00 aaa"), "AA00AAA")
        with self.assertRaises(ValueError):
            core.registration("@!!")

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
        one = core.reminders(self.db, today=date(2026, 10, 23),
                             send=fake_send, env=config)
        two = core.reminders(self.db, today=date(2026, 10, 23),
                             send=fake_send, env=config)
        self.assertEqual(one["sent"], 1)
        self.assertEqual(two["already_sent"], 1)
        self.assertEqual(len(sent), 1)

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
