"""Regression: one map projection, all evidence from first actual observation."""
import unittest
from pathlib import Path
from genesis.hive_regions import REGIONS

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=(ROOT/"web/templates/hive.html").read_text()
PUBLIC=(ROOT/"docs/hive/index.html").read_text()

class FleetFirstMemberPresentationTests(unittest.TestCase):
    def test_svg_land_and_pins_use_one_identical_coordinate_system(self):
        for html in (PRIVATE,PUBLIC):
            self.assertNotIn('<img class="world-map-photo"',html)
            self.assertIn('class="world-fallback"',html)
            self.assertIn('id="hive-region-pins"',html)
            self.assertIn('viewBox="0 0 760 330"',html)
            self.assertEqual(html.count('viewBox="0 0 760 330"'),2)
            self.assertIn('r.visibility==="EXPLICIT_PUBLIC_OPT_IN"',html)
        # Fixed coarse markers lie in their intended schematic landmasses,
        # not in another world-projection raster/remote asset.
        self.assertEqual(REGIONS["NORTH_AMERICA_WEST"][1:3],(128,111))
        self.assertEqual(REGIONS["NORTH_AMERICA_EAST"][1:3],(180,110))

    def test_west_vs_midwest_region_is_not_confused(self):
        self.assertIn("Western North America (Pacific/Rocky Mountain)",PRIVATE)
        self.assertIn("Eastern North America (Midwest/Great Lakes/East)",PRIVATE)
        self.assertIn('Your selected broad region (private view)',PRIVATE)

    def test_one_real_contributor_is_not_suppressed_by_graph(self):
        self.assertIn('window.hiveReporting=Number.isInteger(fleet.participating_vehicles)',PRIVATE)
        self.assertIn('Overall enrollment · not a monthly count',PRIVATE)
        self.assertIn('r.visibility==="EXPLICIT_PUBLIC_OPT_IN"',PUBLIC)

if __name__=="__main__":
    unittest.main()
