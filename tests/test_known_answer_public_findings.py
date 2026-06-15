import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_known_answer_public_findings as verify


class KnownAnswerPublicFindingsTest(unittest.TestCase):
    def test_main_documents_unconfirmed_locked_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_csv(root / verify.PULL_PLAN_PATH, _pull_rows())
            utils.write_csv(root / verify.CHECK_MANIFEST_PATH, _check_rows())
            utils.write_json(root / verify.DRY_RUN_SUMMARY_JSON_PATH, {"rows": _dry_run_rows()})
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
            markdown = utils.read_text(root / verify.SUMMARY_MD_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["target_count"], 10)
        self.assertEqual(summary["summary"]["confirmed_count"], 0)
        self.assertEqual(summary["summary"]["not_run_pending_approval_count"], 9)
        self.assertEqual(summary["summary"]["blocked_request_or_purchase_count"], 1)
        self.assertEqual(summary["summary"]["dry_run_ready_count"], 8)
        self.assertIn("Known-Answer Public Finding Confirmation", markdown)

    def test_validation_requires_every_pull_target_once(self):
        pulls = _pull_rows()
        checks = _check_rows()[:-1]
        checks[0]["pull_id"] = checks[1]["pull_id"]
        errors = "\n".join(verify.validate_checks(pulls, checks))
        self.assertIn("multiple checks", errors)
        self.assertIn("missing a public finding check", errors)

    def test_gap_artifacts_are_reported_as_gap_identified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pulls = _pull_rows()
            checks = _check_rows()
            utils.write_csv(root / verify.PULL_PLAN_PATH, pulls)
            utils.write_csv(root / verify.CHECK_MANIFEST_PATH, checks)
            utils.write_json(root / verify.DRY_RUN_SUMMARY_JSON_PATH, {"rows": _dry_run_rows()})
            for check in checks:
                artifact_status = (
                    "blocked_request_or_purchase"
                    if check["pull_id"] == "seraseq_ctdna_mrd_panel"
                    else "not_confirmed_truth_assets_verified"
                )
                utils.write_json(root / check["analysis_artifact_path"], {"status": artifact_status})
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["summary"]["gap_identified_count"], 9)
        self.assertEqual(summary["summary"]["blocked_request_or_purchase_count"], 1)
        self.assertEqual(summary["summary"]["not_run_pending_approval_count"], 0)

    def test_bounded_non_dry_artifacts_do_not_unlock_strict_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pulls = _pull_rows()
            checks = _check_rows()
            utils.write_csv(root / verify.PULL_PLAN_PATH, pulls)
            utils.write_csv(root / verify.CHECK_MANIFEST_PATH, checks)
            utils.write_json(root / verify.DRY_RUN_SUMMARY_JSON_PATH, {"rows": _dry_run_rows()})
            for index, check in enumerate(checks):
                if check["pull_id"] == "seraseq_ctdna_mrd_panel":
                    artifact_status = "blocked_request_or_purchase"
                elif index < 3:
                    artifact_status = "bounded_non_dry_passed"
                elif index == 3:
                    artifact_status = "bounded_non_dry_partial"
                else:
                    artifact_status = "bounded_non_dry_gap_identified"
                utils.write_json(root / check["analysis_artifact_path"], {"status": artifact_status})
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["summary"]["confirmed_count"], 0)
        self.assertEqual(summary["summary"]["bounded_non_dry_confirmed_count"], 3)
        self.assertEqual(summary["summary"]["bounded_non_dry_partial_count"], 1)
        self.assertEqual(summary["summary"]["clinical_use_allowed_count"], 0)


def _pull_rows() -> list[dict[str, str]]:
    return [
        _pull("hg008_tumor_wgs", "giab_hg008", "HG008-T", "tumor", "yes"),
        _pull("hg008_normal_wgs", "giab_hg008", "HG008-N-D", "normal", "yes"),
        _pull("hg008_tumor_rna", "giab_hg008", "HG008-T_bulk", "tumor_rna", "yes"),
        _pull("hg008_small_variant_truth", "giab_hg008", "HG008-T_somatic_smvar_v0.3", "truth_small_variant", "yes"),
        _pull("hg008_sv_cnv_truth", "giab_hg008", "HG008-T_somatic_stvar_cnv_v0.5", "truth_sv_cnv", "yes"),
        _pull("colo829_tumor_wgs", "colo829", "COLO829", "tumor", "yes"),
        _pull("colo829_normal_wgs", "colo829", "COLO829BL", "normal", "yes"),
        _pull("colo829_sv_cna_truth", "colo829", "COLO829_sv_cna_truth", "truth_sv_cnv", "yes"),
        _pull("colo829_purity_series", "colo829_purity_series", "COLO829_purity_selected_levels", "dilution_series", "yes"),
        _pull("seraseq_ctdna_mrd_panel", "seraseq_ctdna_mrd", "Seraseq_ctDNA_MRD_Panel_Mix", "ctdna_reference", "request_or_purchase"),
    ]


def _pull(pull_id: str, dataset_id: str, sample_or_asset_id: str, asset_role: str, source_access: str) -> dict[str, str]:
    return {
        "pull_id": pull_id,
        "priority": "1",
        "dataset_id": dataset_id,
        "sample_or_asset_id": sample_or_asset_id,
        "asset_role": asset_role,
        "modality": "tumor_normal_wgs",
        "source_access": source_access,
        "source_url": "https://example.test/source",
        "expected_answer": "known public finding",
        "first_validation_gate": "first gate",
        "planned_pull_mode": "metadata_only_until_approval",
        "estimated_transfer_cost_class": "high",
        "checksum_required_before_use": "yes",
        "owner_review_required": "yes",
        "execution_allowed": "no",
        "clinical_use_allowed": "no",
        "no_call_if_unavailable": "yes",
        "caveat": "not clinical",
    }


def _check_rows() -> list[dict[str, str]]:
    return [
        _check("hg008_tumor_wgs_input", "hg008_tumor_wgs", "giab_hg008", "hg008_small_variants"),
        _check("hg008_normal_wgs_input", "hg008_normal_wgs", "giab_hg008", "hg008_small_variants"),
        _check("hg008_tumor_rna_qc", "hg008_tumor_rna", "giab_hg008", ""),
        _check("hg008_small_variant_concordance", "hg008_small_variant_truth", "giab_hg008", "hg008_small_variants"),
        _check("hg008_sv_cnv_concordance", "hg008_sv_cnv_truth", "giab_hg008", "hg008_sv_cnv"),
        _check("colo829_tumor_wgs_input", "colo829_tumor_wgs", "colo829", "colo829_driver_signature"),
        _check("colo829_normal_wgs_input", "colo829_normal_wgs", "colo829", "colo829_driver_signature"),
        _check("colo829_sv_cna_concordance", "colo829_sv_cna_truth", "colo829", "colo829_sv_cna"),
        _check("colo829_purity_monotonicity", "colo829_purity_series", "colo829_purity_series", "colo829_purity_series"),
        _check("seraseq_mrd_positive_negative", "seraseq_ctdna_mrd_panel", "seraseq_ctdna_mrd", ""),
    ]


def _check(check_id: str, pull_id: str, dataset_id: str, fixture_id: str) -> dict[str, str]:
    return {
        "check_id": check_id,
        "pull_id": pull_id,
        "dataset_id": dataset_id,
        "fixture_id": fixture_id,
        "public_finding": "public finding",
        "source_url": "https://example.test/source",
        "analysis_command": "benchmark command",
        "analysis_artifact_path": f"results/{check_id}.json",
        "pass_gate": "status passed",
        "no_call_policy": "No-call until inputs are approved and run.",
    }


def _dry_run_rows() -> list[dict[str, str]]:
    return [
        {"fixture_id": "hg008_small_variants", "dry_run_status": "passed"},
        {"fixture_id": "hg008_sv_cnv", "dry_run_status": "passed"},
        {"fixture_id": "colo829_driver_signature", "dry_run_status": "passed"},
        {"fixture_id": "colo829_sv_cna", "dry_run_status": "passed"},
        {"fixture_id": "colo829_purity_series", "dry_run_status": "passed"},
    ]


if __name__ == "__main__":
    unittest.main()
