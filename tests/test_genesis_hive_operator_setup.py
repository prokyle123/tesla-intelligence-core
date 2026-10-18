"""Per-install Hive owner controls must initialize privately and idempotently."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"scripts/ghost_hive_operator_init.py"
spec=importlib.util.spec_from_file_location("hive_operator_init",SCRIPT)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class HiveOperatorSetupTests(unittest.TestCase):
    def test_new_install_creates_independent_private_local_key(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)
            left=root/"install-a"
            right=root/"install-b"
            one=module.initialize(left)
            two=module.initialize(right)
            self.assertEqual(one.stat().st_mode & 0o777,0o600)
            self.assertEqual(one.parent.stat().st_mode & 0o777,0o700)
            self.assertEqual(two.stat().st_mode & 0o777,0o600)
            self.assertNotEqual(one.read_text(),two.read_text())
            self.assertGreater(len(one.read_text().strip()),40)
            self.assertEqual(module.initialize(left).read_text(),one.read_text())
            self.assertFalse((left/"real-consent.json").exists())
            self.assertFalse((left/"enrollment.token").exists())

    def test_existing_insecure_keys_and_state_are_refused(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)/"private"
            module.initialize(root)
            key=root/"dashboard-admin.token"
            key.chmod(0o644)
            with self.assertRaisesRegex(ValueError,"private"):
                module.initialize(root)
            key.chmod(0o600)
            root.chmod(0o755)
            with self.assertRaisesRegex(ValueError,"private"):
                module.initialize(root)

if __name__=="__main__":
    unittest.main()
