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

if __name__ == "__main__":
    unittest.main()
