"""Simulate real customized GHOST deployment; preserve Home byte-for-byte."""
from __future__ import annotations
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("gh_hive_patcher",ROOT/"scripts/ghost_hive_integrate.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


class HiveIncrementalUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        self.live=base/"live"
        (self.live/"ghost_tesla_ai").mkdir(parents=True)
        (self.live/"web/templates").mkdir(parents=True)
        self.backup=base/"private-backup"
        self.backup.mkdir(mode=0o700)
        self.server=self.live/"ghost_tesla_ai/server.py"
        self.index=self.live/"web/templates/index.html"
        self.server.write_text(
            "from flask import Flask\napp=Flask(__name__)\n"
            +patcher.SERVER_ANCHOR+"\n"
            +"# LIVE USER CUSTOMIZATION MUST SURVIVE\n")
        self.index.write_text(
            "<html><body><h1>PRIVATE LIVE HOME</h1>\n"
            +patcher.TAB_ANCHOR+"\n"
            +"<section id='view-morning'>Original home untouched</section>"
            +"</body></html>\n")
        self.previous={p:p.read_bytes() for p in (self.server,self.index)}

    def test_check_does_not_write_and_apply_preserves_live_home(self):
        patcher.apply(self.live,ROOT,self.backup,dry_run=True)
        for path,value in self.previous.items():
            self.assertEqual(path.read_bytes(),value)
        self.assertFalse((self.backup/"latest.json").exists())
        patcher.apply(self.live,ROOT,self.backup)
        self.assertIn("LIVE USER CUSTOMIZATION MUST SURVIVE",self.server.read_text())
        self.assertIn("PRIVATE LIVE HOME",self.index.read_text())
        self.assertIn("Original home untouched",self.index.read_text())
        self.assertEqual(self.index.read_text().count('href="/hive"'),1)
        self.assertEqual(self.server.read_text().count("ghost_hive_local_bp"),2)
        self.assertTrue((self.live/"web/templates/hive.html").exists())
        self.assertTrue((self.live/"ghost_tesla_ai/hive_local.py").exists())
        self.assertEqual(self.backup.stat().st_mode & 0o777,0o700)
        self.assertEqual((self.backup/"latest.json").stat().st_mode & 0o777,0o600)
        with self.assertRaisesRegex(ValueError,"already integrated"):
            patcher.apply(self.live,ROOT,self.backup)

    def test_rollback_checksums_and_removes_only_added_files(self):
        patcher.apply(self.live,ROOT,self.backup)
        patcher.rollback(self.live,self.backup)
        for path,value in self.previous.items():
            self.assertEqual(path.read_bytes(),value)
        self.assertFalse((self.live/"web/templates/hive.html").exists())
        self.assertFalse((self.live/"ghost_tesla_ai/hive_local.py").exists())

    def test_refuse_unrecognized_source_and_modified_postinstall(self):
        self.server.write_text("from flask import Flask\n# CUSTOM SERVER")
        with self.assertRaisesRegex(ValueError,"differs"):
            patcher.apply(self.live,ROOT,self.backup,dry_run=True)
        self.server.write_bytes(self.previous[self.server])
        patcher.apply(self.live,ROOT,self.backup)
        self.index.write_text(self.index.read_text()+"\nPOST INSTALL CUSTOM CHANGE")
        with self.assertRaisesRegex(ValueError,"changed after install"):
            patcher.rollback(self.live,self.backup)

if __name__=="__main__":
    unittest.main()
