"""Web authentication and write safety checks."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from autokeeper.server import create_app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"APP_ADMIN_USERNAME": "admin",
                                            "APP_ADMIN_PASSWORD": "unit-test-only"},
                              clear=False)
        self.env.start()
        self.client = TestClient(create_app(str(Path(self.temp.name) / "db.sqlite")))
        self.client.__enter__()
        self.auth = ("admin", "unit-test-only")

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        self.temp.cleanup()

    def test_read_requires_auth(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        self.assertEqual(self.client.get("/api/dashboard", auth=self.auth).status_code, 200)

    def test_mutations_require_custom_header(self):
        row = {"registration": "AA00AAA", "email": "test@example.org"}
        self.assertEqual(self.client.post("/api/vehicles", auth=self.auth,
                                          json=row).status_code, 403)
        response = self.client.post("/api/vehicles", auth=self.auth, json=row,
                                    headers={"X-AutoKeeper-Request": "same-origin"})
        self.assertEqual(response.status_code, 200)
        dashboard = self.client.get("/api/dashboard", auth=self.auth).json()
        self.assertEqual(dashboard["stats"]["total"], 1)
        self.assertEqual(dashboard["stats"]["unchecked"], 1)

    def test_dashboard_includes_company_summaries(self):
        headers = {"X-AutoKeeper-Request": "same-origin"}
        for reg, company in [
            ("AA00AAA", "Company A"),
            ("BB11BBB", "company a"),
            ("CC22CCC", "Company B"),
            ("DD33DDD", ""),
        ]:
            r = self.client.post(
                "/api/vehicles", auth=self.auth, headers=headers,
                json={"registration": reg, "company": company}
            )
            self.assertEqual(r.status_code, 200, r.text)
        data = self.client.get("/api/dashboard", auth=self.auth).json()
        self.assertEqual(data["stats"]["total"], 4)
        self.assertEqual([x["key"] for x in data["companies"]],
                         ["company a", "company b", ""])
        self.assertEqual([x["stats"]["total"] for x in data["companies"]],
                         [2, 1, 1])
        self.assertEqual(data["companies"][-1]["name"], "Unassigned")
        self.assertEqual(sum(x["stats"]["unknown"] for x in data["companies"]), 4)

    def test_sorn_mot_state_and_dashboard_counts(self):
        from autokeeper import core
        headers = {"X-AutoKeeper-Request": "same-origin"}
        r = self.client.post("/api/vehicles", auth=self.auth, headers=headers,
                             json={"registration": "AA00AAA", "company": "Demo",
                                   "email": "example@example.org"})
        self.assertEqual(r.status_code, 200)
        with core.open_db(str(Path(self.temp.name) / "db.sqlite")) as db:
            db.execute("""
                UPDATE vehicles SET tax_status='SORN',
                  mot_expiry_date='2026-01-01',
                  tax_due_date='2026-01-01' WHERE registration='AA00AAA'
            """)
        data = self.client.get("/api/dashboard", auth=self.auth).json()
        self.assertEqual(data["vehicles"][0]["mot"]["state"], "sorn")
        self.assertEqual(data["vehicles"][0]["mot_expiry_date"], "2026-01-01")
        self.assertEqual(data["stats"]["mot_overdue"], 0)
        self.assertEqual(data["stats"]["attention"], 0)
        self.assertEqual(data["companies"][0]["stats"]["mot_overdue"], 0)


    def test_lifecycle_fields_roundtrip_and_validation(self):
        headers = {"X-AutoKeeper-Request": "same-origin"}
        created = self.client.post("/api/vehicles", auth=self.auth, headers=headers,
                                   json={"registration": "XY55XYZ",
                                         "acquisition_date": "2022-05-09",
                                         "disposal_date": "2026-09-14"})
        self.assertEqual(created.status_code, 200, created.text)
        v = created.json()
        self.assertEqual(v["lifecycle_state"], "disposed")
        self.assertEqual(v["acquisition_date"], "2022-05-09")
        dashboard = self.client.get("/api/dashboard", auth=self.auth).json()
        self.assertEqual(dashboard["stats"]["active"], 0)
        self.assertEqual(dashboard["stats"]["disposed"], 1)
        updated = self.client.put("/api/vehicles/" + str(v["id"]),
                                  auth=self.auth, headers=headers,
                                  json={"registration": "XY55XYZ", "company": "History"})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["disposal_date"], "2026-09-14")
        bad = self.client.put("/api/vehicles/" + str(v["id"]),
                              auth=self.auth, headers=headers,
                              json={"registration": "XY55XYZ",
                                    "acquisition_date": "2026-11-03",
                                    "disposal_date": "2026-01-01"})
        self.assertEqual(bad.status_code, 422)
        clear = self.client.put("/api/vehicles/" + str(v["id"]),
                                auth=self.auth, headers=headers,
                                json={"registration": "XY55XYZ", "disposal_date": ""})
        self.assertEqual(clear.status_code, 200, clear.text)
        self.assertIsNone(clear.json()["disposal_date"])
        self.assertEqual(clear.json()["acquisition_date"], "2022-05-09")

    def test_static_assets_and_prefix_links(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"AUTOKEEPER_ROOT_PATH": "/apps/autokeeper"}):
            app = create_app(str(Path(self.temp.name) / "prefix.sqlite"))
            with TestClient(app) as client:
                home = client.get("/", auth=self.auth)
                self.assertEqual(home.status_code, 200)
                self.assertIn('href="./static/style.css"', home.text)
                self.assertIn('src="./static/app.js"', home.text)
                css = client.get("/static/style.css")
                js = client.get("/static/app.js")
                self.assertEqual(css.status_code, 200)
                self.assertEqual(js.status_code, 200)
                self.assertIn("text/css", css.headers.get("content-type", ""))
                self.assertIn("javascript", js.headers.get("content-type", ""))
                self.assertIn('id="company-select"', home.text)
                self.assertIn("data-company-key", js.text)
                self.assertIn('id="field-acquisition_date"', home.text)
                self.assertIn('id="field-disposal_date"', home.text)
                self.assertIn('value="disposed"', home.text)
                self.assertIn("acquisition_date", js.text)


    def test_import_generated_workbook_layout(self):
        """Exercise actual multipart Excel parsing + SQLite with synthetic 45 rows."""
        from io import BytesIO
        from openpyxl import Workbook
        wb = Workbook()
        sheet = wb.active
        sheet.title = "Master"
        sheet.append([
            "Registration No", "Employee Name", "Company", "Email Address",
            "Make", "Model", "Colour", "motStatus", "motExpiryDate",
            "taxStatus", "taxDueDate", "Import Note"
        ])
        for i in range(45):
            sheet.append([
                f"ZZ{i:05d}", f"Synthetic owner {i}", "Demo",
                "demo@example.org" if i < 9 else None,
                "Sample", "Model", "Blue", "Valid", "2027-05-17",
                "Taxed", "2027-07-01", "Historical snapshot"
            ])
        info = wb.create_sheet("How to import")
        info["A1"] = "Instructions"
        data = BytesIO()
        wb.save(data)
        wb.close()
        headers = {"X-AutoKeeper-Request": "same-origin"}
        files = {"file": ("AutoKeeper_Existing_Vehicles_Import.xlsx",
                          data.getvalue(),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        result = self.client.post("/api/import", auth=self.auth,
                                  headers=headers, files=files)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["created"], 45)
        self.assertEqual(result.json()["skipped"], 0)
        self.assertEqual(
            self.client.get("/api/dashboard", auth=self.auth).json()["stats"]["total"], 45)
        # Reimport should not create duplicates.
        again = self.client.post("/api/import", auth=self.auth,
                                 headers=headers, files=files)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["updated"], 45)

    def test_invalid_excel_upload_returns_validation_error(self):
        files = {"file": ("broken.xlsx", b"not a ZIP file",
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = self.client.post("/api/import", auth=self.auth,
                             headers={"X-AutoKeeper-Request": "same-origin"}, files=files)
        self.assertEqual(r.status_code, 422)
        self.assertIn("Invalid spreadsheet", r.text)

    def test_missing_excel_dependency_reports_actionable_error(self):
        from unittest.mock import patch
        with patch("autokeeper.server.read_import",
                   side_effect=RuntimeError("Excel import support is not installed.")):
            r = self.client.post("/api/import", auth=self.auth,
                                 headers={"X-AutoKeeper-Request": "same-origin"},
                                 files={"file": ("vehicles.xlsx", b"excel", "application/octet-stream")})
        self.assertEqual(r.status_code, 503)
        self.assertIn("not installed", r.text)

if __name__ == "__main__":
    unittest.main()
