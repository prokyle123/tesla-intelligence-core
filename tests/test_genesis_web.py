"""Read-only Genesis web endpoints, tested in an isolated Flask application."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import os

from flask import Flask
from genesis.api import blueprint

class GenesisWebTests(unittest.TestCase):
    def test_page_is_separate_and_api_has_no_mutating_method(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"GHOST_GENESIS_DATA_DIR": folder,
                                         "GHOST_HIVEMIND_MODE": "contribute"}):
                app = Flask("genesis-web-regression")
                app.register_blueprint(blueprint)
                client = app.test_client()
                r = client.get("/genesis")
                self.assertEqual(r.status_code, 200)
                self.assertIn(b"GENESIS", r.data)
                self.assertEqual(r.headers["Cache-Control"], "no-store")
                self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")
                self.assertEqual(r.headers["X-Frame-Options"], "DENY")
                api = client.get("/api/genesis/overview")
                self.assertEqual(api.status_code, 200)
                data = api.get_json()
                self.assertEqual(data["runs"], [])
                self.assertEqual(data["findings"], [])
                self.assertFalse(data["production_changes"])
                self.assertFalse(data["network"]["outbound_uploads"])
                self.assertEqual(data["network"]["mode"], "contribute")
                self.assertEqual(client.post("/api/genesis/overview").status_code, 405)
                self.assertEqual(client.post("/genesis").status_code, 405)
                self.assertFalse((Path(folder) / "research.sqlite3").exists())

if __name__ == "__main__":
    unittest.main()
