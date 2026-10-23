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


if __name__ == "__main__":
    unittest.main()
