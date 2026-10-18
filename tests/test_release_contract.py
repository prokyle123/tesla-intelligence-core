"""Source-level v1 integration checks; no vehicle credentials or network required."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

from ghost_tesla_ai import quality_runner, trip_shadow_runner

ROOT = Path(__file__).resolve().parent.parent


class PortableReleaseContract(unittest.TestCase):
    def test_quality_runner_has_versioned_sources(self):
        for kind, script in (("forecast", "evaluate_v2.py"), ("trip", "evaluate_v32.py")):
            cmd = quality_runner.command(kind)
            self.assertEqual(Path(cmd[1]).name, script)
            self.assertTrue(Path(cmd[1]).is_file())
            self.assertIn("--db", cmd)
            self.assertIn("--out", cmd)
            # The checkout may legitimately live under /home/ghost on the
            # developer's Pi. Verify the resolved script belongs to THIS
            # checkout, not whether the runtime path contains that home.
            self.assertEqual(Path(cmd[1]).resolve().parent,
                             (ROOT / "release-sidecars").resolve())
        self.assertNotIn("/home/ghost", Path(quality_runner.__file__).read_text())

    def test_quality_paths_do_not_force_pi_user(self):
        for filename in (
            "ghost_tesla_ai/forecast_quality_v2_api.py",
            "ghost_tesla_ai/trip_quality_v3_api.py",
            "ghost_tesla_ai/vehicle_sensors_v1.py",
        ):
            self.assertNotIn("/home/ghost/", (ROOT / filename).read_text())

    def test_installer_deploys_quality_stack(self):
        installer = (ROOT / "install.sh").read_text()
        self.assertIn('$SUDO cp -a "$ROOT/release-sidecars" "$INSTALL_DIR/"', installer)
        self.assertIn("ghost-trip-quality-v32.timer", installer)
        self.assertIn("ghost-forecast-quality-v2.timer", installer)
        for name in ("ghost-forecast-quality-v2", "ghost-trip-quality-v32"):
            service = (ROOT / f"systemd/templates/{name}.service.in").read_text()
            timer = (ROOT / f"systemd/templates/{name}.timer.in").read_text()
            self.assertIn("ghost_tesla_ai.quality_runner", service)
            self.assertIn(f"Unit={name}.service", timer)

    def test_endpoint_templates_exist(self):
        for name in ("forecast_quality_v2.html", "trip_quality_v31.html", "ghost_vehicle_sensors.html"):
            self.assertTrue((ROOT / "web" / "templates" / name).is_file())

    def test_shadow_pipeline_contract(self):
        stages = trip_shadow_runner.commands(ROOT / "fixture.sqlite3", ROOT / "private")
        self.assertEqual(len(stages), 6)
        self.assertEqual([name for name, _ in stages],
                         ["sequence_v1", "location_v2", "outcomes_v3",
                          "feedback_v4", "coverage_v5", "relationships_v6"])
        # The input paths supplied by the caller are deliberately absolute:
        # do not mistake a checkout installed in /home/ghost for hardcoding.
        db_path = str(ROOT / "fixture.sqlite3")
        out_path = str(ROOT / "private")
        for name, cmd in stages:
            self.assertEqual(cmd[:3], [sys.executable, "-m",
                                      "ghost_tesla_ai." + dict(
                                          sequence_v1="trip_sequence_shadow",
                                          location_v2="trip_location_context",
                                          outcomes_v3="trip_outcome_v3",
                                          feedback_v4="trip_feedback_v4",
                                          coverage_v5="trip_coverage_v5",
                                          relationships_v6="trip_relationship_v6")[name]])
            if "--db" in cmd:
                self.assertEqual(cmd[cmd.index("--db") + 1], db_path)
            if "--live-db" in cmd:
                self.assertEqual(cmd[cmd.index("--live-db") + 1], db_path)
            if "--root" in cmd:
                self.assertEqual(cmd[cmd.index("--root") + 1], out_path)
            if "--out" in cmd:
                self.assertEqual(cmd[cmd.index("--out") + 1], out_path)
        self.assertNotIn("/home/ghost", Path(trip_shadow_runner.__file__).read_text())
        installer = (ROOT / "install.sh").read_text()
        self.assertIn("ghost-trip-shadow.timer", installer)
        for filename in ("ghost-trip-shadow.service.in", "ghost-trip-shadow.timer.in"):
            self.assertTrue((ROOT / "systemd" / "templates" / filename).is_file())

    def test_six_shadow_module_regressions(self):
        modules = [
            "trip_sequence_shadow", "trip_location_context", "trip_outcome_v3",
            "trip_feedback_v4", "trip_coverage_v5", "trip_relationship_v6",
            "trip_energy_preview_v1",
        ]
        for module in modules:
            with self.subTest(module=module):
                run = subprocess.run(
                    [sys.executable, "-m", "ghost_tesla_ai." + module, "--self-test"],
                    cwd=ROOT, capture_output=True, text=True, timeout=35,
                )
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn("PASS", run.stdout)

    def test_shadow_trip_regressions(self):
        for script in ("evaluate_v31.py", "evaluate_v32.py"):
            run = subprocess.run(
                [sys.executable, str(ROOT / "release-sidecars" / script), "--self-test"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("PASS", run.stdout)


if __name__ == "__main__":
    unittest.main()
