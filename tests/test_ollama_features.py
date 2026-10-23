"""Ollama knowledge, Markdown and AI record-update security tests."""
import json
import os
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from autokeeper import core, knowledge, ollama, record_ai
from autokeeper.server import create_app


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "knowledge.md"

    def tearDown(self):
        self.directory.cleanup()

    def test_knowledge_persistence_revision_and_edit(self):
        initial = knowledge.read_knowledge(self.path)
        self.assertIn("AutoKeeper", initial["content"])
        content = "# Revised rules\n\n| Type | Value |\n| --- | --- |\n| A | B |\n"
        saved = knowledge.save_knowledge(self.path, content, initial["revision"])
        self.assertEqual(saved["content"], content)
        self.assertEqual(knowledge.read_knowledge(self.path), saved)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            knowledge.save_knowledge(self.path, "bad overwrite", initial["revision"])
        self.assertEqual(knowledge.read_knowledge(self.path), saved)

    def test_full_gfm_preview_and_safe_html(self):
        source = (
            "# Heading\n\n**bold** ~~strike~~ [safe](https://example.org)\n\n"
            "| A | B |\n| - | - |\n| One | Two |\n\n"
            "- [x] checked\n- [ ] not checked\n\n"
            "~~~python\nprint('hi')\n~~~\n\n"
            "> quote\n\nA note[^1].\n\n[^1]: Footnote here.\n\n"
            "<script>alert('oops')</script>\n"
            "[XSS](javascript:alert(1))\n"
        )
        html = knowledge.markdown_html(source)
        self.assertIn("<table", html)
        self.assertIn("<s>", html)
        self.assertIn("<pre>", html)
        self.assertIn("checkbox", html)
        self.assertIn("footnote", html)
        self.assertIn("Heading", html)
        self.assertIn('href="https://example.org"', html)
        self.assertNotIn("<script>", html)
        self.assertNotIn('href="javascript:', html)
        with self.assertRaises(ValueError):
            knowledge.markdown_html("x" * (knowledge.MAX_PREVIEW_CHARS + 1))


class OllamaAdapterTests(unittest.TestCase):
    def test_model_listing_and_stream(self):
        response = Mock()
        response.json.return_value = {
            "models": [
                {"name":"qwen3:4b", "size":123,
                 "details":{"parameter_size":"4B"}},
                {"name":"llama3:8b", "size":234},
            ]
        }
        response.raise_for_status.return_value = None
        upstream = Mock()
        upstream.raise_for_status.return_value = None
        upstream.iter_lines.return_value = [
            b'{"message":{"content":"Hello "},"done":false}',
            b'{"message":{"content":"**world**"},"done":false}',
            b'{"message":{},"done":true}'
        ]
        session = Mock()
        session.get.return_value = response
        session.post.return_value = upstream
        models = ollama.list_models(session)
        self.assertEqual([m["name"] for m in models],
                         ["llama3:8b", "qwen3:4b"])
        returned = ollama.open_chat(
            "qwen3:4b", [{"role":"user","content":"Hello"}],
            system_context="**Knowledge context**", session=session
        )
        kwargs = session.post.call_args.kwargs
        self.assertEqual(kwargs["json"]["model"], "qwen3:4b")
        self.assertIn("Knowledge context",
                      kwargs["json"]["messages"][1]["content"])
        self.assertTrue(kwargs["json"]["stream"])
        chunks = list(ollama.stream_deltas(returned))
        self.assertEqual(json.loads(chunks[0]), {"delta":"Hello "})
        self.assertEqual(json.loads(chunks[1]), {"delta":"**world**"})
        self.assertEqual(json.loads(chunks[2]), {"done":True})
        upstream.close.assert_called_once()

    def test_unknown_model_rejected(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {"models":[{"name":"allowed:1b"}]}
        session.get.return_value = response
        with self.assertRaises(ValueError):
            ollama.open_chat("uninstalled:8b", [{"role":"user","content":"x"}],
                             session=session)
        session.post.assert_not_called()

    def test_structured_proposal_request(self):
        session = Mock()
        listing = Mock()
        listing.json.return_value = {"models":[{"name":"local:4b"}]}
        completion = Mock()
        completion.json.return_value = {
            "message": {"content": '{"proposals":[],"explanation":"ok"}'}
        }
        session.get.return_value = listing
        session.post.return_value = completion
        result = ollama.structured_completion(
            "local:4b", "system", "user", record_ai.PROPOSAL_SCHEMA,
            session=session
        )
        self.assertEqual(result["proposals"], [])
        self.assertFalse(session.post.call_args.kwargs["json"]["stream"])
        self.assertIsInstance(session.post.call_args.kwargs["json"]["format"], dict)


class AiChangesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = core.open_db(str(Path(self.directory.name) / "vehicles.db"))
        core.init_db(self.db)
        record_ai.init_proposals(self.db)
        self.vehicle = core.save_vehicle(self.db, {
            "registration":"AA00AAA", "company":"Example",
            "owner":"Test Person", "email":"test@example.org",
        })

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def test_change_needs_confirmation_is_owner_bound_and_one_shot(self):
        fake = {"proposals":[{"registration":"AA00AAA",
                "updates":{"company":"Updated Company"}}],
                "explanation":"Company correction"}
        with patch("autokeeper.record_ai.ollama.structured_completion",
                   return_value=fake):
            ready = record_ai.prepare_changes(
                self.db, "admin1", "test:4b",
                "Set AA00AAA company to Updated Company", "# Rules"
            )
        self.assertEqual(self.db.execute(
            "SELECT company FROM vehicles WHERE id=?",
            (self.vehicle["id"],)).fetchone()[0], "Example")
        proposal = ready["proposals"][0]
        self.assertEqual(proposal["before"]["company"], "Example")
        self.assertEqual(proposal["after"]["company"], "Updated Company")
        with self.assertRaises(LookupError):
            record_ai.apply_change(self.db, "someone-else", proposal["id"])
        answer = record_ai.apply_change(self.db, "admin1", proposal["id"])
        self.assertEqual(answer["changed_fields"]["company"], "Updated Company")
        self.assertEqual(core.get_vehicle(self.db, self.vehicle["id"])["company"],
                         "Updated Company")
        with self.assertRaisesRegex(ValueError, "already been applied"):
            record_ai.apply_change(self.db, "admin1", proposal["id"])

    def test_change_rejected_when_record_modified(self):
        with patch("autokeeper.record_ai.ollama.structured_completion",
                   return_value={"proposals":[{
                       "registration":"AA00AAA", "updates":{"company":"Different"}
                   }],"explanation":"Change"}):
            prepared = record_ai.prepare_changes(
                self.db,"admin","local","Make a change", "# Rules"
            )
        core.save_vehicle(self.db, {
            "registration":"AA00AAA","company":"Edited externally",
        }, self.vehicle["id"])
        with self.assertRaisesRegex(ValueError, "data changed"):
            record_ai.apply_change(self.db,"admin",prepared["proposals"][0]["id"])
        self.assertEqual(core.get_vehicle(self.db, self.vehicle["id"])["company"],
                         "Edited externally")

    def test_model_cannot_propose_prohibited_field(self):
        with patch("autokeeper.record_ai.ollama.structured_completion",
                   return_value={"proposals":[{
                       "registration":"AA00AAA",
                       "updates":{"mot_expiry_date":"2030-12-01"}
                   }],"explanation":"bad"}):
            with self.assertRaises(ValueError):
                record_ai.prepare_changes(self.db,"admin","local","fake MOT", "#")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM ai_change_proposals").fetchone()[0], 0)

    def test_readonly_context_contains_current_record_and_knowledge(self):
        prompt = record_ai.system_context(
            self.db, "## Workflow", "Which company owns AA00AAA?"
        )
        self.assertIn("AA00AAA", prompt)
        self.assertIn("Example", prompt)
        self.assertIn("Workflow", prompt)
        self.assertIn("cannot", prompt.lower())


class WebChatTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environ = patch.dict(os.environ, {
            "APP_ADMIN_USERNAME":"admin",
            "APP_ADMIN_PASSWORD":"test-secret",
            "AUTOKEEPER_AUTH_MODE":"basic",
            "AUTOKEEPER_DB_PATH":str(Path(self.directory.name)/"vehicles.db"),
        })
        self.environ.start()
        self.client = TestClient(create_app(
            str(Path(self.directory.name)/"vehicles.db")))
        self.client.__enter__()
        self.auth = ("admin", "test-secret")
        self.write = {"X-AutoKeeper-Request":"same-origin"}

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.environ.stop()
        self.directory.cleanup()

    def test_chat_and_knowledge_routes_require_auth_write_header(self):
        self.assertEqual(self.client.get("/api/knowledge").status_code,401)
        self.assertEqual(self.client.get("/api/knowledge",
                                        auth=self.auth).status_code,200)
        self.assertEqual(self.client.post("/api/markdown/render", auth=self.auth,
                                         json={"content":"# H"}).status_code,403)
        good = self.client.post("/api/markdown/render", auth=self.auth,
                                headers=self.write, json={"content":"# H"})
        self.assertEqual(good.status_code,200)
        self.assertIn("<h1>",good.json()["html"])
        doc = self.client.get("/api/knowledge", auth=self.auth).json()
        saved = self.client.put("/api/knowledge",auth=self.auth,headers=self.write,
                                json={"content":"# Updated","revision":doc["revision"]})
        self.assertEqual(saved.status_code,200,saved.text)
        conflict = self.client.put("/api/knowledge",auth=self.auth,headers=self.write,
                                json={"content":"old","revision":doc["revision"]})
        self.assertEqual(conflict.status_code,409)
        page = self.client.get("/",auth=self.auth).text
        self.assertIn('id="ollama-toggle"',page)
        self.assertIn('id="knowledge-source"',page)
        self.assertIn('id="ollama-propose"',page)
        asset = self.client.get("/static/ollama-chat.js")
        self.assertEqual(asset.status_code,200)
        self.assertIn("javascript",asset.headers["content-type"])

    def test_models_and_chat_proxy_mocked(self):
        with patch("autokeeper.server.ollama.list_models", return_value=[
            {"name":"test:4b","parameter_size":"4B","size_bytes":12},
        ]):
            listing = self.client.get("/api/ollama/models",auth=self.auth)
            self.assertEqual(listing.status_code,200)
            self.assertEqual(listing.json()["models"][0]["name"],"test:4b")
        upstream = Mock()
        with patch("autokeeper.server.ollama.open_chat",
                   return_value=upstream) as start, patch(
                       "autokeeper.server.ollama.stream_deltas",
                       return_value=iter(['{"delta":"Hello"}\n','{"done":true}\n'])):
            response = self.client.post("/api/ollama/chat",auth=self.auth,
                                        headers=self.write,json={
                                            "model":"test:4b",
                                            "messages":[{"role":"user","content":"Fleet"}],
                                        })
            self.assertEqual(response.status_code,200,response.text)
            self.assertIn("Hello",response.text)
            self.assertIn("AutoKeeper",start.call_args.kwargs["system_context"])
        self.assertEqual(self.client.post("/api/ollama/chat",auth=self.auth,
            headers=self.write,json={"model":"m","messages":[{
                "role":"user","content":"x"}]*21}).status_code,422)

    def test_change_proposal_approval_endpoints(self):
        created = self.client.post("/api/vehicles",auth=self.auth,
            headers=self.write,json={"registration":"AA00AAA","company":"Old"})
        self.assertEqual(created.status_code,200)
        fake = {"proposals":[{"registration":"AA00AAA",
                "updates":{"company":"New"}}],"explanation":"Change"}
        with patch("autokeeper.record_ai.ollama.structured_completion",
                   return_value=fake):
            proposed = self.client.post("/api/ollama/propose",auth=self.auth,
                headers=self.write,json={"model":"local:4b",
                  "instruction":"Change AA00AAA company to New"})
        self.assertEqual(proposed.status_code,200,proposed.text)
        record_id = proposed.json()["proposals"][0]["id"]
        dashboard = self.client.get("/api/dashboard",auth=self.auth).json()
        self.assertEqual(dashboard["vehicles"][0]["company"],"Old")
        approved = self.client.post("/api/ollama/apply",auth=self.auth,
                                    headers=self.write,json={"id":record_id})
        self.assertEqual(approved.status_code,200,approved.text)
        after = self.client.get("/api/dashboard",auth=self.auth).json()
        self.assertEqual(after["vehicles"][0]["company"],"New")
