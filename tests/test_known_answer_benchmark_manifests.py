import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_known_answer_benchmark_manifests as verify


class KnownAnswerBenchmarkManifestTest(unittest.TestCase):
    def test_schema_rows_require_metadata_only_inputs_and_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan_row()
            utils.write_csv(root / verify.PLAN_MANIFEST_PATH, [plan])
            utils.write_csv(root / plan["input_manifest_path"], [_input_row("tumor"), _input_row("normal")])
            utils.write_csv(root / plan["truth_asset_manifest"], [_truth_row()])
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["benchmark_count"], 1)
        self.assertEqual(summary["summary"]["benchmark_execution_ready"], "no")

    def test_input_manifest_rejects_local_path_requirement(self):
        row = _input_row("tumor")
        row["local_path_required"] = "yes"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "inputs.csv"
            utils.write_csv(path, [row, _input_row("normal")])
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                errors = verify.validate_input_manifest("inputs.csv", "giab_hg008")
        self.assertIn("must keep local_path_required=no", "\n".join(errors))

    def test_truth_manifest_requires_no_call_if_missing(self):
        row = _truth_row()
        row["no_call_if_missing"] = "no"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "truth.csv"
            utils.write_csv(path, [row])
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                errors = verify.validate_truth_manifest("truth.csv", "giab_hg008", "hg008_small_variants")
        self.assertIn("must set no_call_if_missing=yes", "\n".join(errors))


def _plan_row() -> dict[str, str]:
    return {
        "benchmark_id": "hg008_small_variant_dry_run",
        "fixture_id": "hg008_small_variants",
        "dataset_id": "giab_hg008",
        "runner_mode": "tumor_normal_wgs",
        "input_manifest_path": "manifests/benchmarks/hg008_wgs_inputs.csv",
        "truth_asset_manifest": "manifests/benchmarks/hg008_small_variant_truth_assets.csv",
        "planned_command": "benchmark:known-answer --fixture hg008_small_variants --dry-run",
        "required_outputs": "summary.json;summary.csv",
        "cache_namespace": "known_answer/hg008/small_variants",
        "execution_status": "dry_run_only",
        "approval_required": "yes",
        "cost_class": "high",
        "clinical_use_allowed": "no",
        "no_call_policy": "No-call if required truth files are unavailable.",
    }


def _input_row(role: str) -> dict[str, str]:
    return {
        "input_id": f"hg008_{role}",
        "dataset_id": "giab_hg008",
        "sample_id": f"HG008-{role}",
        "sample_role": role,
        "sample_pair": "HG008-T/HG008-N-D",
        "reference_build": "GRCh38",
        "source_status": "planned_not_downloaded",
        "local_path_required": "no",
        "source_url": "https://example.test/input",
        "expected_file_type": "bam_or_fastq",
        "clinical_use_allowed": "no",
        "caveat": "metadata only",
    }


def _truth_row() -> dict[str, str]:
    return {
        "truth_asset_id": "hg008_truth",
        "dataset_id": "giab_hg008",
        "fixture_id": "hg008_small_variants",
        "truth_scope": "small_variant_snv_indel",
        "reference_build": "GRCh38",
        "asset_status": "planned_not_downloaded",
        "source_url": "https://example.test/truth",
        "expected_file_type": "vcf",
        "required_for_execution": "yes",
        "clinical_use_allowed": "no",
        "no_call_if_missing": "yes",
        "caveat": "metadata only",
    }


if __name__ == "__main__":
    unittest.main()
