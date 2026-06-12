import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_known_answer_asset_acquisition as verify


class KnownAnswerAssetAcquisitionTest(unittest.TestCase):
    def test_acquisition_plan_covers_planned_assets_but_blocks_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan_row()
            acquisitions = [
                _acquisition_row("input_asset_acquisition", plan["input_manifest_path"], "input", plan["dataset_id"]),
                _acquisition_row("truth_asset_acquisition", plan["truth_asset_manifest"], "truth", plan["dataset_id"]),
            ]
            utils.write_csv(root / verify.PLAN_MANIFEST_PATH, [plan])
            utils.write_csv(root / verify.ACQUISITION_MANIFEST_PATH, acquisitions)
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["asset_group_count"], 2)
        self.assertEqual(summary["summary"]["approved_count"], 0)
        self.assertEqual(summary["summary"]["execution_allowed_count"], 0)
        self.assertEqual(summary["summary"]["raw_data_upload_allowed_count"], 0)
        self.assertEqual(summary["summary"]["benchmark_execution_ready"], "no")

    def test_acquisition_plan_requires_every_unique_manifest(self):
        plan = _plan_row()
        missing_truth = _acquisition_row("input_asset_acquisition", plan["input_manifest_path"], "input", plan["dataset_id"])
        planned_paths = {
            plan["input_manifest_path"]: {"asset_kind": "input", "dataset_id": plan["dataset_id"]},
            plan["truth_asset_manifest"]: {"asset_kind": "truth", "dataset_id": plan["dataset_id"]},
        }
        errors = verify.validate_acquisition_plan(planned_paths, [missing_truth])
        self.assertIn("missing acquisition planning", "\n".join(errors))

    def test_acquisition_plan_rejects_execution_or_raw_upload(self):
        plan = _plan_row()
        row = _acquisition_row("input_asset_acquisition", plan["input_manifest_path"], "input", plan["dataset_id"])
        row["execution_allowed"] = "yes"
        row["raw_data_upload_allowed"] = "yes"
        planned_paths = {plan["input_manifest_path"]: {"asset_kind": "input", "dataset_id": plan["dataset_id"]}}
        errors = verify.validate_acquisition_plan(planned_paths, [row])
        joined = "\n".join(errors)
        self.assertIn("raw_data_upload_allowed=no", joined)
        self.assertIn("execution_allowed=no", joined)


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


def _acquisition_row(acquisition_id: str, manifest_path: str, asset_kind: str, dataset_id: str) -> dict[str, str]:
    return {
        "acquisition_id": acquisition_id,
        "manifest_path": manifest_path,
        "asset_kind": asset_kind,
        "dataset_id": dataset_id,
        "approval_status": "not_requested",
        "acquisition_mode": "metadata_only_until_approval",
        "estimated_cost_class": "high",
        "raw_data_upload_allowed": "no",
        "execution_allowed": "no",
        "checksum_required_before_use": "yes",
        "clinical_use_allowed": "no",
        "owner_review_required": "yes",
        "next_action": "Prepare exact source URLs checksums and cost notes for owner approval.",
    }


if __name__ == "__main__":
    unittest.main()
