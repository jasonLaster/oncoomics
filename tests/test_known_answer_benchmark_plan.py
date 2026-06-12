import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import plan_known_answer_benchmarks as plan


class KnownAnswerBenchmarkPlanTest(unittest.TestCase):
    def test_validate_plan_requires_dry_run_and_approval(self):
        fixtures = [_fixture_row("hg008_small_variants", "giab_hg008")]
        rows = [_plan_row("hg008_small_variant_dry_run", "hg008_small_variants", "giab_hg008")]
        rows[0]["execution_status"] = "ready_to_run"
        rows[0]["approval_required"] = "no"
        rows[0]["clinical_use_allowed"] = "yes"
        rows[0]["planned_command"] = "benchmark:known-answer --fixture hg008_small_variants"
        errors = "\n".join(plan.validate_plan(fixtures, rows))
        self.assertIn("must remain dry_run_only", errors)
        self.assertIn("must require approval", errors)
        self.assertIn("clinical_use_allowed=no", errors)
        self.assertIn("must include --dry-run", errors)

    def test_main_writes_benchmark_plan_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures = [
                _fixture_row("hg008_small_variants", "giab_hg008"),
                _fixture_row("colo829_sv_cna", "colo829"),
            ]
            plans = [
                _plan_row("hg008_small_variant_dry_run", "hg008_small_variants", "giab_hg008"),
                _plan_row("colo829_sv_cna_dry_run", "colo829_sv_cna", "colo829"),
            ]
            utils.write_csv(root / plan.FIXTURE_MANIFEST_PATH, fixtures)
            utils.write_csv(root / plan.PLAN_MANIFEST_PATH, plans)
            with patch.object(plan, "path_from_root", lambda relative: root / relative):
                plan.main()
            summary = utils.read_json(root / plan.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["benchmark_count"], 2)
        self.assertEqual(summary["summary"]["dry_run_only_count"], 2)
        self.assertEqual(summary["summary"]["approval_required_count"], 2)
        self.assertEqual(summary["summary"]["clinical_use_allowed_count"], 0)
        self.assertEqual(summary["summary"]["ready_for_benchmark_execution"], "no")


def _fixture_row(fixture_id: str, dataset_id: str) -> dict[str, str]:
    return {
        "fixture_id": fixture_id,
        "priority": "1",
        "dataset_id": dataset_id,
        "sample_pair": "tumor/normal",
        "modality": "tumor_normal_wgs",
        "truth_scope": "sv_cnv",
        "required_truth_or_expected_answer": "truth files",
        "required_output": "summary",
        "clinicalization_gate": "sv_cnv_feature_validation",
        "current_status": "planned_not_run",
        "threshold_status": "not_locked",
        "source_url": "https://example.test",
        "caveat": "not validated",
    }


def _plan_row(benchmark_id: str, fixture_id: str, dataset_id: str) -> dict[str, str]:
    return {
        "benchmark_id": benchmark_id,
        "fixture_id": fixture_id,
        "dataset_id": dataset_id,
        "runner_mode": "tumor_normal_wgs",
        "input_manifest_path": f"manifests/benchmarks/{dataset_id}_inputs.csv",
        "truth_asset_manifest": f"manifests/benchmarks/{dataset_id}_truth_assets.csv",
        "planned_command": f"benchmark:known-answer --fixture {fixture_id} --dry-run",
        "required_outputs": "summary.json;summary.csv",
        "cache_namespace": f"known_answer/{fixture_id}",
        "execution_status": "dry_run_only",
        "approval_required": "yes",
        "cost_class": "high",
        "clinical_use_allowed": "no",
        "no_call_policy": "No-call if required truth files are unavailable.",
    }


if __name__ == "__main__":
    unittest.main()
