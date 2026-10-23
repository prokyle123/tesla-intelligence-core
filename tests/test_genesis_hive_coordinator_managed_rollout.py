"""Offline test: server handoff DB copy is transactional and never deletes data."""
from __future__ import annotations
from contextlib import closing
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
spec=importlib.util.spec_from_file_location("rollout",ROOT/"scripts/hive_coordinator_managed_rollout.py")
rollout=importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollout)

class HiveCoordinatorManagedRolloutTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.p=Path(t.name)
        os.chmod(self.p,0o700)
        self.original=self.p/"live.sqlite3"
        with closing(sqlite3.connect(self.original)) as con:
            con.executescript("""
                CREATE TABLE participants(id INTEGER PRIMARY KEY, enabled INTEGER);
                CREATE TABLE monthly_research(participant INTEGER, month TEXT);
                CREATE TABLE region_consents(participant INTEGER,
                    region_code TEXT,enabled INTEGER);
                INSERT INTO participants VALUES(1,1);
                INSERT INTO monthly_research VALUES(1,'2026-10');
                INSERT INTO region_consents VALUES(1,'NORTH_AMERICA_WEST',1);
            """)
            con.commit()

    def test_sqlite_online_backup_and_rollback_preserve_all_rows(self):
        backup=self.p/"before.sqlite3"
        rollout._online_backup(self.original,backup)
        self.assertEqual(backup.stat().st_mode&0o777,0o600)
        self.assertEqual(rollout._db_counts(backup)["enrolled"],1)
        with closing(sqlite3.connect(self.original)) as con:
            con.execute("ALTER TABLE region_consents ADD COLUMN public_listing INTEGER NOT NULL DEFAULT 0")
            con.execute("UPDATE participants SET enabled=0")
            con.commit()
        rollout._restore_backup(backup,self.original)
        self.assertEqual(rollout._db_counts(self.original),
                         rollout._db_counts(backup))
        self.assertFalse(rollout._db_counts(self.original)["public_schema"])
        self.assertEqual(rollout._db_counts(self.original)["monthly"],1)

    def test_unit_uses_loopback_fixed_port_and_private_db(self):
        release=rollout.STAGED/"0123456789abcdef"
        unit=rollout.unit_text(release,"ghost")
        self.assertIn("User=ghost",unit)
        self.assertIn("--port 8778 serve",unit)
        self.assertIn("ReadWritePaths=",unit)
        self.assertIn("NoNewPrivileges=yes",unit)
        self.assertIn("ProtectHome=read-only",unit)
        with self.assertRaises(ValueError):
            rollout.unit_text(Path("/tmp/arbitrary"),"ghost")

if __name__=="__main__":
    unittest.main()
