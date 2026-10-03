import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VISUALIZATION = REPO_ROOT / "docs" / "rosalind" / "visualizations" / "trop2-rna-evidence.html"


class Trop2VisualizationTest(unittest.TestCase):
    def test_checked_in_visualization_is_standalone_and_responsive(self):
        document = VISUALIZATION.read_text(encoding="utf-8")

        self.assertTrue(document.startswith("<!doctype html>"))
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1"', document)
        self.assertIn("data-visualize-standalone", document)
        self.assertIn('title="Corrected TROP-2 RNA evidence"', document)
        self.assertIn("width:100%", document)
        self.assertIn("Corrected TROP-2 RNA evidence", document)
        self.assertIn("minimum 131×", document)


if __name__ == "__main__":
    unittest.main()
