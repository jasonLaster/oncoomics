import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import run_known_answer_benchmark as run


class KnownAnswerBenchmarkDryRunTest(unittest.TestCase):
    def test_write_dry_run_materializes_expected_paths_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan_row()
            with patch.object(run, "path_from_root", lambda relative: root / relative):
                run.write_dry_run(plan)
            dry_run_plan = utils.read_json(root / run.DRY_RUN_ROOT / plan["benchmark_id"] / "dry_run_plan.json")
            output_rows = utils.parse_csv(
                utils.read_text(root / run.DRY_RUN_ROOT / plan["benchmark_id"] / "expected_outputs_manifest.csv")
            )
            summary = utils.read_json(root / run.DRY_RUN_SUMMARY_JSON_PATH)
        self.assertEqual(dry_run_plan["status"], "passed")
        self.assertEqual(dry_run_plan["mode"], "dry_run_only")
        self.assertEqual(dry_run_plan["executionAllowed"], "no")
        self.assertEqual(dry_run_plan["clinicalUseAllowed"], "no")
        self.assertEqual(len(output_rows), 2)
        self.assertTrue(all(row["planned_path"].endswith(row["output_name"]) for row in output_rows))
        self.assertEqual(summary["summary"]["dry_run_count"], 1)
        self.assertEqual(summary["summary"]["ready_for_benchmark_execution"], "no")

    def test_select_plan_rejects_unknown_fixture(self):
        with self.assertRaises(SystemExit):
            run.select_plan([_plan_row()], "missing_fixture")


def _plan_row() -> dict[str, str]:
    return {
        "benchmark_id": "hg008_small_variant_dry_run",
        "fixture_id": "hg008_small_variants",
        "dataset_id": "giab_hg008",
        "runner_mode": "tumor_normal_wgs",
        "input_manifest_path": "manifests/benchmarks/hg008_wgs_inputs.csv",
        "truth_asset_manifest": "manifests/benchmarks/hg008_truth_assets.csv",
        "planned_command": "benchmark:known-answer --fixture hg008_small_variants --dry-run",
        "required_outputs": "summary.json;summary.csv",
        "cache_namespace": "known_answer/hg008/small_variants",
        "execution_status": "dry_run_only",
        "approval_required": "yes",
        "cost_class": "high",
        "clinical_use_allowed": "no",
        "no_call_policy": "No-call if required truth files are unavailable.",
    }


if __name__ == "__main__":
    unittest.main()
