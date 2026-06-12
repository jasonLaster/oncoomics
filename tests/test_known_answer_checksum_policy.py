import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_known_answer_checksum_policy as verify


class KnownAnswerChecksumPolicyTest(unittest.TestCase):
    def test_checksum_policy_covers_planned_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_csv(root / verify.PLAN_MANIFEST_PATH, [_plan_row()])
            utils.write_csv(root / verify.POLICY_MANIFEST_PATH, [_policy_row("inputs.csv", "input"), _policy_row("truth.csv", "truth")])
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["policy_count"], 2)
        self.assertEqual(summary["summary"]["checksum_pending_count"], 2)
        self.assertEqual(summary["summary"]["benchmark_execution_ready"], "no")

    def test_checksum_policy_rejects_execution_allowed(self):
        row = _policy_row("inputs.csv", "input")
        row["execution_allowed"] = "yes"
        errors = verify.validate_policy({"inputs.csv": "input"}, [row])
        self.assertIn("must keep execution_allowed=no", "\n".join(errors))


def _plan_row() -> dict[str, str]:
    return {
        "benchmark_id": "hg008_small_variant_dry_run",
        "fixture_id": "hg008_small_variants",
        "dataset_id": "giab_hg008",
        "runner_mode": "tumor_normal_wgs",
        "input_manifest_path": "inputs.csv",
        "truth_asset_manifest": "truth.csv",
        "planned_command": "benchmark:known-answer --fixture hg008_small_variants --dry-run",
        "required_outputs": "summary.json;summary.csv",
        "cache_namespace": "known_answer/hg008/small_variants",
        "execution_status": "dry_run_only",
        "approval_required": "yes",
        "cost_class": "high",
        "clinical_use_allowed": "no",
        "no_call_policy": "No-call if required truth files are unavailable.",
    }


def _policy_row(manifest_path: str, asset_kind: str) -> dict[str, str]:
    return {
        "policy_id": f"{asset_kind}_policy",
        "manifest_path": manifest_path,
        "asset_kind": asset_kind,
        "checksum_source_status": "checksum_not_captured",
        "accepted_checksum_types": "sha256;md5",
        "capture_required_before_execution": "yes",
        "execution_allowed": "no",
        "clinical_use_allowed": "no",
        "no_call_if_unverified": "yes",
        "next_action": "Record checksums after approved asset acquisition.",
    }


if __name__ == "__main__":
    unittest.main()
