"""Tests for the public, read-only V2 release inventory helper."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('v2_release_inventory', ROOT / 'scripts/v2_release_inventory.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

class ReleaseInventoryTests(unittest.TestCase):
    def test_sources_are_hashed_but_not_secret_or_binary_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = root / 'watchdog.py'
            f.write_text('print("safe")\n')
            self.assertEqual(len(helper.sha_source(f)), 64)
            self.assertIsNone(helper.sha_source(root / 'tessie.token'))
            self.assertIsNone(helper.sha_source(root / 'model.gguf'))
            self.assertIsNone(helper.sha_source(root / 'intelligence.sqlite3'))

    def test_status_does_not_require_root_or_contact_a_model(self):
        seen = []
        def fake_systemd(args):
            seen.append(args)
            if args[:2] == ['systemctl', 'show']:
                return 'ExecStart=... Qwen3.5-4B-Q4_K_M.gguf'
            return 'active'
        with tempfile.TemporaryDirectory() as td:
            result = helper.inventory(Path(td), systemd=fake_systemd)
        self.assertEqual(result['deployed_model_family'], 'qwen3.5-4b')
        self.assertFalse(result['release_ready'])
        self.assertEqual(len(result['systemd_active']), len(helper.UNITS))
        self.assertTrue(all(args[0] == 'systemctl' for args in seen))
        self.assertNotIn('vehicle', str(result).lower())

    def test_no_operational_side_effects(self):
        source = (ROOT / 'scripts/v2_release_inventory.py').read_text()
        for forbidden in ('systemctl restart', 'systemctl stop', 'requests.post', 'urllib.request', 'sqlite3.connect', 'chmod(', 'chown('):
            self.assertNotIn(forbidden, source)

if __name__ == '__main__':
    unittest.main()
