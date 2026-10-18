"""Only reviewed current Hive + PIN gateway files may be patched and rolled back."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("ghost_hive_owner_update",
                                           ROOT/"scripts/hive_owner_gateway_update.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class GatewayOwnerReleaseTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.live=self.root/"live"
        self.source=self.root/"source"
        self.backup=self.root/"rollback"
        for root in (self.live,self.source):
            (root/"ghost_tesla_ai").mkdir(parents=True)
            (root/"web/templates").mkdir(parents=True)
        self.home=self.live/"web/templates/index.html"
        self.home.write_text("ORIGINAL OWNER CLASSIC HOME")
        self.server=self.live/"ghost_tesla_ai/server.py"
        self.server.write_text("ORIGINAL OWNER SERVER")
        self.old={}
        for file in mod.FILES:
            if file=="ghost_tesla_ai/hive_owner_proof.py":
                value=None
            elif file.endswith(".py"):
                value=b"answer=1\n"
            else:
                value=b"<div>Prior Hive UI</div>"
            self.old[file]=value
            if value is not None:
                (self.live/file).write_bytes(value)
            (self.source/file).write_bytes(b"answer=2\n" if file.endswith(".py") else b"<div>PIN owner HTTPS</div>")
        self.allow={k:({mod.blob(v)} if v is not None else set())
                    for k,v in self.old.items()}

    def test_previous_approved_fleet_map_is_exact_allowlisted_version(self):
        # Reviewed Git blob from installed v1.4 map/dashboard commit 133c93e;
        # unknown live changes continue to block all production upgrades.
        approved=mod.OLD_GIT_BLOBS["web/templates/hive.html"]
        self.assertIn("a7d458777775607f2db464791a4c1476ed986cd3",approved)
        self.assertNotIn(mod.blob(b"UNREVIEWED LOCAL MAP EDIT"),approved)

    def test_preflight_is_read_only_upgrade_and_rollback(self):
        with patch.dict(mod.OLD_GIT_BLOBS,self.allow,clear=True):
            mod.apply(self.live,self.source,self.backup,dry_run=True)
            self.assertFalse(self.backup.exists())
            mod.apply(self.live,self.source,self.backup,dry_run=False)
            self.assertTrue((self.backup/"latest.json").exists())
            self.assertEqual(self.home.read_text(),"ORIGINAL OWNER CLASSIC HOME")
            self.assertEqual(self.server.read_text(),"ORIGINAL OWNER SERVER")
            for name in mod.FILES:
                self.assertEqual((self.live/name).read_bytes(),
                                 (self.source/name).read_bytes())
            mod.rollback(self.live,self.backup)
            self.assertFalse((self.live/"ghost_tesla_ai/hive_owner_proof.py").exists())
            for name in mod.FILES:
                if self.old[name] is not None:
                    self.assertEqual((self.live/name).read_bytes(),self.old[name])
            self.assertEqual(self.home.read_text(),"ORIGINAL OWNER CLASSIC HOME")

    def test_unknown_existing_or_post_install_change_blocks(self):
        with patch.dict(mod.OLD_GIT_BLOBS,self.allow,clear=True):
            (self.live/"ghost_tesla_ai/funnel_gateway.py").write_text("UNREVIEWED OWNER EDIT")
            with self.assertRaisesRegex(ValueError,"Unreviewed"):
                mod.apply(self.live,self.source,self.backup,dry_run=True)
            self.assertFalse(self.backup.exists())
            (self.live/"ghost_tesla_ai/funnel_gateway.py").write_bytes(
                self.old["ghost_tesla_ai/funnel_gateway.py"])
            mod.apply(self.live,self.source,self.backup,dry_run=False)
            (self.live/"web/templates/hive.html").write_text("USER EDIT AFTER INSTALL")
            with self.assertRaisesRegex(ValueError,"unknown installed"):
                mod.rollback(self.live,self.backup)
            self.assertEqual(self.home.read_text(),"ORIGINAL OWNER CLASSIC HOME")

if __name__=="__main__":unittest.main()
