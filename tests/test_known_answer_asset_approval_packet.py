import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_known_answer_asset_approval_packet as verify


class KnownAnswerAssetApprovalPacketTest(unittest.TestCase):
    def test_approval_packet_summarizes_sources_but_blocks_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = "manifests/benchmarks/hg008_wgs_inputs.csv"
            utils.write_csv(root / manifest_path, [_asset_row("https://example.test/a"), _asset_row("https://example.test/a")])
            utils.write_csv(root / verify.ACQUISITION_MANIFEST_PATH, [_acquisition_row(manifest_path)])
            utils.write_csv(root / verify.POLICY_MANIFEST_PATH, [_checksum_row(manifest_path)])
            utils.write_csv(root / verify.APPROVAL_PACKET_PATH, [_packet_row(manifest_path)])
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["packet_row_count"], 1)
        self.assertEqual(summary["summary"]["source_url_count"], 1)
        self.assertEqual(summary["summary"]["access_terms_review_pending_count"], 1)
        self.assertEqual(summary["summary"]["checksum_pending_count"], 1)
        self.assertEqual(summary["summary"]["execution_allowed_count"], 0)
        self.assertEqual(summary["summary"]["approval_packet_ready_for_owner_review"], "yes")

    def test_approval_packet_rejects_source_url_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = "manifests/benchmarks/hg008_wgs_inputs.csv"
            packet = _packet_row(manifest_path)
            packet["source_urls"] = "https://example.test/wrong"
            utils.write_csv(root / manifest_path, [_asset_row("https://example.test/a")])
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                errors = verify.validate_packet([_acquisition_row(manifest_path)], [_checksum_row(manifest_path)], [packet])
        self.assertIn("source_urls must match", "\n".join(errors))

    def test_approval_packet_rejects_execution_or_clinical_use(self):
        manifest_path = "manifests/benchmarks/hg008_wgs_inputs.csv"
        packet = _packet_row(manifest_path)
        packet["execution_allowed"] = "yes"
        packet["clinical_use_allowed"] = "yes"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_csv(root / manifest_path, [_asset_row("https://example.test/a")])
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                errors = verify.validate_packet([_acquisition_row(manifest_path)], [_checksum_row(manifest_path)], [packet])
        joined = "\n".join(errors)
        self.assertIn("execution_allowed=no", joined)
        self.assertIn("clinical_use_allowed=no", joined)


def _asset_row(source_url: str) -> dict[str, str]:
    return {
        "input_id": "hg008_tumor",
        "dataset_id": "giab_hg008",
        "sample_id": "HG008-T",
        "sample_role": "tumor",
        "sample_pair": "HG008-T/HG008-N-D",
        "reference_build": "GRCh38",
        "source_status": "planned_not_downloaded",
        "local_path_required": "no",
        "source_url": source_url,
        "expected_file_type": "bam_or_fastq",
        "clinical_use_allowed": "no",
        "caveat": "metadata only",
    }


def _acquisition_row(manifest_path: str) -> dict[str, str]:
    return {
        "acquisition_id": "hg008_wgs_inputs_acquisition",
        "manifest_path": manifest_path,
        "asset_kind": "input",
        "dataset_id": "giab_hg008",
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


def _checksum_row(manifest_path: str) -> dict[str, str]:
    return {
        "policy_id": "hg008_wgs_input_checksums",
        "manifest_path": manifest_path,
        "asset_kind": "input",
        "checksum_source_status": "checksum_not_captured",
        "accepted_checksum_types": "sha256;md5",
        "capture_required_before_execution": "yes",
        "execution_allowed": "no",
        "clinical_use_allowed": "no",
        "no_call_if_unverified": "yes",
        "next_action": "Record checksums after approved asset acquisition.",
    }


def _packet_row(manifest_path: str) -> dict[str, str]:
    return {
        "packet_id": "hg008_wgs_inputs_packet",
        "manifest_path": manifest_path,
        "asset_kind": "input",
        "dataset_id": "giab_hg008",
        "source_urls": "https://example.test/a",
        "source_url_count": "1",
        "access_terms_status": "needs_owner_review",
        "checksum_evidence_status": "checksum_not_captured",
        "estimated_transfer_cost_class": "high",
        "estimated_compute_cost_class": "high",
        "raw_data_upload_allowed": "no",
        "execution_allowed": "no",
        "clinical_use_allowed": "no",
        "owner_review_required": "yes",
        "approval_recommendation": "defer_until_terms_and_checksums_captured",
        "next_action": "Confirm exact source files access terms checksums and transfer budget before approval.",
    }


if __name__ == "__main__":
    unittest.main()
