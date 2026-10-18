"""GENESIS responsive product UI: navigation/data safety contract."""
from __future__ import annotations
from html.parser import HTMLParser
from pathlib import Path
import unittest

HTML = Path(__file__).resolve().parents[1]/"genesis/web/genesis_dashboard.html"

class Inspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=[]
        self.tabs=[]
        self.panels=[]
        self.external=[]
        self.scripts=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if "id" in a: self.ids.append(a["id"])
        if "data-tab" in a: self.tabs.append(a["data-tab"])
        if "data-panel" in a: self.panels.append(a["data-panel"])
        if tag=="script":
            self.scripts+=1
            if "src" in a: self.external.append(a["src"])
        if tag=="link" and "href" in a: self.external.append(a["href"])

class DashboardUITests(unittest.TestCase):
    def test_navigation_is_accessible_and_stays_inside_research(self):
        p=Inspector();p.feed(HTML.read_text())
        self.assertEqual(p.tabs,["overview","models","investigations","history","hive","system"])
        self.assertEqual(p.tabs,p.panels)
        self.assertEqual(len(p.ids),len(set(p.ids)))
        self.assertEqual(p.scripts,1)
        self.assertFalse(p.external)
        for required in (
            "kpi-cycles","kpi-heater","model-leaderboard","model-scores",
            "mission-title","history-list","history-details",
            "health-badge","connection","refresh",
        ):
            self.assertIn(required,p.ids)
    def test_no_vehicle_actions_or_raw_sample_exposure(self):
        html=HTML.read_text()
        self.assertIn("/api/genesis/overview",html)
        self.assertIn("/api/genesis/health",html)
        self.assertNotIn("fetch(\"https://",html)
        self.assertNotIn("eval(",html)
        self.assertNotIn(".innerHTML",html)
        self.assertNotIn("Tesla API token",html)
        self.assertNotIn("onclick=",html)
        self.assertIn("manual cycle",html.lower())

if __name__=="__main__":
    unittest.main()
