"""Source-level v1 integration checks; no vehicle credentials or network required."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

from ghost_tesla_ai import quality_runner

ROOT = Path(__file__).resolve().parent.parent


class PortableReleaseContract(unittest.TestCase):
    def test_quality_runner_has_versioned_sources(self):
        for kind, script in (("forecast", "evaluate_v2.py"), ("trip", "evaluate_v32.py")):
            cmd = quality_runner.command(kind)
            self.assertEqual(Path(cmd[1]).name, script)
            self.assertTrue(Path(cmd[1]).is_file())
            self.assertIn("--db", cmd)
            self.assertIn("--out", cmd)
            self.assertNotIn("/home/ghost", " ".join(cmd))

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
