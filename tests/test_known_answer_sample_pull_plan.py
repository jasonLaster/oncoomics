import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_known_answer_sample_pull_plan as verify


class KnownAnswerSamplePullPlanTest(unittest.TestCase):
    def test_main_writes_ten_target_pull_plan_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_csv(root / verify.MANIFEST_PATH, _suite_rows())
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["pull_target_count"], 10)
        self.assertEqual(summary["summary"]["sample_input_count"], 7)
        self.assertEqual(summary["summary"]["truth_asset_count"], 3)
        self.assertEqual(summary["summary"]["execution_allowed_count"], 0)
        self.assertEqual(summary["summary"]["ready_for_sample_acquisition"], "no")

    def test_pull_plan_rejects_premature_execution_and_shrinking_suite(self):
        rows = _suite_rows()[:-1]
        rows[0]["execution_allowed"] = "yes"
        errors = "\n".join(verify.validate_pull_plan(rows))
        self.assertIn("at least 10 pull targets", errors)
        self.assertIn("execution_allowed=no", errors)


def _suite_rows() -> list[dict[str, str]]:
    return [
        _row("hg008_tumor_wgs", "1", "giab_hg008", "HG008-T", "tumor", "tumor_normal_wgs"),
        _row("hg008_normal_wgs", "1", "giab_hg008", "HG008-N-D", "normal", "tumor_normal_wgs"),
        _row("hg008_tumor_rna", "2", "giab_hg008", "HG008-T_bulk", "tumor_rna", "tumor_rna_seq"),
        _row(
            "hg008_small_variant_truth",
            "1",
            "giab_hg008",
            "HG008-T_somatic_smvar_v0.3",
            "truth_small_variant",
            "tumor_normal_wgs",
        ),
        _row("hg008_sv_cnv_truth", "1", "giab_hg008", "HG008-T_somatic_stvar_cnv_v0.5", "truth_sv_cnv", "tumor_normal_wgs"),
        _row("colo829_tumor_wgs", "2", "colo829", "COLO829", "tumor", "tumor_normal_wgs"),
        _row("colo829_normal_wgs", "2", "colo829", "COLO829BL", "normal", "tumor_normal_wgs"),
        _row("colo829_sv_cna_truth", "2", "colo829", "COLO829_sv_cna_truth", "truth_sv_cnv", "tumor_normal_wgs"),
        _row(
            "colo829_purity_series",
            "3",
            "colo829_purity_series",
            "COLO829_purity_selected_levels",
            "dilution_series",
            "tumor_normal_wgs_dilution",
        ),
        _row(
            "seraseq_ctdna_mrd_panel",
            "4",
            "seraseq_ctdna_mrd",
            "Seraseq_ctDNA_MRD_Panel_Mix",
            "ctdna_reference",
            "ctdna_mrd_reference",
            source_access="request_or_purchase",
            planned_pull_mode="contact_or_purchase_required",
            estimated_transfer_cost_class="request_or_purchase",
        ),
    ]


def _row(
    pull_id: str,
    priority: str,
    dataset_id: str,
    sample_or_asset_id: str,
    asset_role: str,
    modality: str,
    source_access: str = "yes",
    planned_pull_mode: str = "metadata_only_until_approval",
    estimated_transfer_cost_class: str = "high",
) -> dict[str, str]:
    return {
        "pull_id": pull_id,
        "priority": priority,
        "dataset_id": dataset_id,
        "sample_or_asset_id": sample_or_asset_id,
        "asset_role": asset_role,
        "modality": modality,
        "source_access": source_access,
        "source_url": "https://example.test/source",
        "expected_answer": "known answer",
        "first_validation_gate": "first gate",
        "planned_pull_mode": planned_pull_mode,
        "estimated_transfer_cost_class": estimated_transfer_cost_class,
        "checksum_required_before_use": "yes",
        "owner_review_required": "yes",
        "execution_allowed": "no",
        "clinical_use_allowed": "no",
        "no_call_if_unavailable": "yes",
        "caveat": "not clinical",
    }


if __name__ == "__main__":
    unittest.main()
