"""Independent Hive-only module upgrade must not touch customized GHOST Home."""
from __future__ import annotations
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("hive_update",ROOT/"scripts/ghost_hive_update.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class HiveModuleUpdateTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.live=self.root/"live"
        self.backup=self.root/"backup"
        (self.live/"ghost_tesla_ai").mkdir(parents=True)
        (self.live/"web/templates").mkdir(parents=True)
        self.home=self.live/"web/templates/index.html"
        self.server=self.live/"ghost_tesla_ai/server.py"
        self.home.write_text("ORIGINAL CUSTOM HOME")
        self.server.write_text("ORIGINAL CLASSIC SERVER")
        self.old={}
        for path in mod.FILES:
            file=self.live/path
            self.old[path]=(("# OLD REVIEWED VERSION\n" if path.endswith(".py") else "<!-- OLD REVIEWED VERSION -->")).encode()
            file.write_bytes(self.old[path])
        self.patches={path:hashlib.sha256(blob).hexdigest()[:16]
                      for path,blob in self.old.items()}

    def test_guarded_upgrade_and_rollback(self):
        with patch.dict(mod.BASE_HASH_PREFIX,self.patches,clear=True):
            mod.apply(self.live,ROOT,self.backup,dry_run=True)
            self.assertFalse(self.backup.exists())
            mod.apply(self.live,ROOT,self.backup,dry_run=False)
            self.assertEqual(self.home.read_text(),"ORIGINAL CUSTOM HOME")
            self.assertEqual(self.server.read_text(),"ORIGINAL CLASSIC SERVER")
            self.assertTrue((self.backup/"latest.json").exists())
            for file in mod.FILES:
                self.assertEqual((self.live/file).read_bytes(),(ROOT/file).read_bytes())
            mod.rollback(self.live,self.backup)
            for file in mod.FILES:
                self.assertEqual((self.live/file).read_bytes(),self.old[file])
            self.assertEqual(self.home.read_text(),"ORIGINAL CUSTOM HOME")

    def test_postinstall_user_edits_block_rollback(self):
        with patch.dict(mod.BASE_HASH_PREFIX,self.patches,clear=True):
            mod.apply(self.live,ROOT,self.backup,dry_run=False)
            f=self.live/"web/templates/hive.html"
            f.write_text(f.read_text()+"\nPRIVATE POST-INSTALL CUSTOMIZATION")
            with self.assertRaisesRegex(ValueError,"modified since update"):
                mod.rollback(self.live,self.backup)
            self.assertIn("PRIVATE POST-INSTALL",f.read_text())


if __name__=="__main__":
    unittest.main()
