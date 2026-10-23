"""Safe coordinator upgrade gate: no unverified PID, DB, or endpoint."""
from __future__ import annotations
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location(
    "hive_coordinator_rollout_probe",
    ROOT/"scripts/hive_coordinator_rollout_probe.py")
probe=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

class CoordinatorProcessGateTests(unittest.TestCase):
    def test_recognizes_only_exact_loopback_coordinator_command(self):
        with TemporaryDirectory() as folder:
            db=Path(folder)/"private.sqlite3"
            argv=["/opt/ghost-tesla-ai/venv/bin/python",
                  "-m","genesis.hive_server","--db",str(db),
                  "--port","8778","serve"]
            self.assertEqual(probe.parse_argv(argv,db)["command"],"serve")
            for changed in (
                [*argv[:-1],"enroll"],
                [*argv[:argv.index("8778")],"8779","serve"],
                ["/usr/bin/node",*argv[1:]],
                [*argv[:argv.index(str(db))],"/tmp/wrong.sqlite3",*argv[argv.index(str(db))+1:]],
                [*argv,"--token","secret"],
            ):
                with self.subTest(argv=changed),self.assertRaises(ValueError):
                    probe.parse_argv(changed,db)

    def test_systemd_or_manual_supervisor_detection(self):
        self.assertEqual(probe.supervisor(
          "0::/system.slice/ghost-hive-coordinator.service"),
          "ghost-hive-coordinator.service")
        self.assertEqual(probe.supervisor(
          "0::/user.slice/user-1000.slice/session-2.scope"),
          "NOT_IDENTIFIED")

if __name__=="__main__":
    unittest.main()
