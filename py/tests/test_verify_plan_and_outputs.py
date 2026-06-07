import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_outputs, verify_plan


class VerifyPlanAndOutputsTest(unittest.TestCase):
    def test_command_version_treats_missing_command_as_none(self):
        self.assertIsNone(verify_plan.command_version("definitely-not-a-real-command", ["--version"]))

    def test_require_columns_reports_missing_column(self):
        errors: list[str] = []
        verify_outputs.require_columns(errors, "x.csv", [{"a": "1"}], ["a", "b"])
        self.assertEqual(errors, ["x.csv is missing required column b."])

    def test_require_rows_reports_missing_and_small_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            errors: list[str] = []
            with patch.object(verify_outputs, "path_from_root", lambda relative: root / relative):
                self.assertEqual(verify_outputs.require_rows(errors, "missing.csv", 1), [])
                utils.write_csv(root / "tiny.csv", [{"a": "1"}])
                rows = verify_outputs.require_rows(errors, "tiny.csv", 2)
            self.assertEqual(rows, [{"a": "1"}])
            self.assertIn("Missing missing.csv", errors)
            self.assertIn("tiny.csv has 1 rows; expected at least 2.", errors)


if __name__ == "__main__":
    unittest.main()
