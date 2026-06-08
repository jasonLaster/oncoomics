import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils


class UtilsTest(unittest.TestCase):
    def test_csv_roundtrip_quotes_special_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            utils.write_csv(path, [{"sample": "A", "note": "BRCA1, BRCA2\nok", "empty": None}], ["sample", "note", "empty"])
            self.assertEqual(utils.parse_csv(utils.read_text(path)), [{"sample": "A", "note": "BRCA1, BRCA2\nok", "empty": ""}])

    def test_fastq_validation(self):
        self.assertEqual(
            utils.validate_fastq_record(["@r1/2 lane=1", "ACGT", "+", "IIII"], "sample", 1),
            {"id": "r1", "sequence": "ACGT", "quality": "IIII"},
        )
        with self.assertRaisesRegex(ValueError, "sequence/quality length mismatch"):
            utils.validate_fastq_record(["@r1", "ACGT", "+", "III"], "sample", 1)

    def test_file_non_empty_rejects_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "value.txt"
            path.write_text("x")
            self.assertTrue(utils.file_non_empty(path))
            self.assertFalse(utils.file_non_empty(Path(tmp)))

    def test_run_command_writes_heartbeat_for_long_command(self):
        output = StringIO()
        with (
            patch.dict(utils.os.environ, {"DIANA_OMICS_COMMAND_HEARTBEAT_SECONDS": "1"}),
            patch("sys.stdout", output),
        ):
            self.assertEqual(utils.run_command("sleep 2; printf done"), "done")

        self.assertIn("[heartbeat] command still running", output.getvalue())
        self.assertIn("sleep 2; printf done", output.getvalue())

    def test_run_command_honors_max_buffer(self):
        self.assertEqual(utils.run_command("printf 123456", max_buffer=3), "456")

    def test_math_and_clinical_helpers(self):
        self.assertEqual(utils.to_number("4.5"), 4.5)
        self.assertIsNone(utils.to_number("bad"))
        self.assertEqual(utils.mean([1, None, 3]), 2)
        sd = utils.standard_deviation([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertIsNotNone(sd)
        self.assertAlmostEqual(sd or 0, 2.138089935, places=6)
        self.assertEqual(utils.quantile([10, 0, 20], 0.5), 10)
        self.assertEqual(
            utils.pivot_clinical(
                [
                    {"sampleId": "S2", "clinicalAttributeId": "SUBTYPE", "value": "Basal"},
                    {"sampleId": "S1", "clinicalAttributeId": "SUBTYPE", "value": "LumA"},
                    {"clinicalAttributeId": "IGNORED", "value": "missing id"},
                ],
                "sampleId",
            ),
            [{"sampleId": "S1", "SUBTYPE": "LumA"}, {"sampleId": "S2", "SUBTYPE": "Basal"}],
        )


if __name__ == "__main__":
    unittest.main()
