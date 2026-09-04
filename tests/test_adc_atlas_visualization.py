import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/rosalind/visualizations/pan-cancer-adc-atlas-v1.html"


class PanCancerAdcAtlasVisualizationTest(unittest.TestCase):
    def test_page_is_standalone_and_evidence_bounded(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertIn("Pan-cancer ADC Atlas", html)
        self.assertIn("Target × cancer RNA landscape", html)
        self.assertIn("All candidates: partial evidence", html)
        self.assertIn("not an exact patient percentile", html)
        self.assertIn("directional Diana RNA bridge", html)
        self.assertIn("Directional Diana-to-BRCA RNA bridge", html)
        self.assertIn("Diana RNA-to-protein follow-up queue", html)
        self.assertIn("not a therapeutic ranking", html)
        self.assertIn("TCGA primary tumors", html)
        self.assertNotIn("<iframe", html)
        self.assertNotIn('src="http', html)

    def test_page_has_responsive_and_interactive_controls(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertIn("@media(max-width:900px)", html)
        self.assertIn("min-width:0", html)
        self.assertIn("max-width:100%", html)
        self.assertIn('id="search"', html)
        self.assertIn('id="tier"', html)
        self.assertIn('id="atlas-data"', html)


if __name__ == "__main__":
    unittest.main()
