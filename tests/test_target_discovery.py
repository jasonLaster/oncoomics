import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from diana_omics import target_discovery, utils
from diana_omics.commands.target_discovery import (
    analyze_dna_targets,
    build_rosalind_target_packet,
    build_target_dna_evidence,
    build_target_template,
    verify_modal_target_packet,
    verify_target_inputs,
)


class TargetDiscoveryTest(unittest.TestCase):
    def test_candidate_manifest_covers_adc_cdk12_and_cdk46_context(self):
        rows = target_discovery.candidate_rows()
        errors = target_discovery.validate_candidate_rows(rows)

        self.assertEqual(errors, [])
        self.assertTrue({"TACSTD2", "ERBB2", "CDK12", "RB1", "CCNE1", "B2M"}.issubset({row["gene_symbol"] for row in rows}))
        self.assertIn("ddr_transcription_cdk", {row["target_family"] for row in rows})
        self.assertIn("cell_cycle_resistance", {row["target_family"] for row in rows})

    def test_validate_input_rows_rejects_missing_columns_duplicates_and_missing_files(self):
        rows = [_input_row("dna", "dna", path="missing.csv"), _input_row("dna-copy", "dna", path="missing2.csv")]
        rows[1]["evidence_id"] = rows[0]["evidence_id"]
        rows[1]["reference_id"] = "hg19"

        errors, warnings, summary = target_discovery.validate_input_rows(rows, require_files=True)

        self.assertIn("Target discovery inputs have duplicate evidence_id dna.", errors)
        self.assertIn("Evidence row dna path path does not exist: missing.csv", errors)
        self.assertIn("DNA evidence rows contain multiple reference_id values: hg19, hg38.", warnings)
        self.assertEqual(summary["dnaRowCount"], 2)

    def test_validate_input_rows_accepts_optional_rna_protein_and_report_rows(self):
        rows = [
            _input_row("dna", "dna", reference_id="hg38"),
            _input_row("rna", "rna", reference_id=""),
            _input_row("protein", "protein", reference_id=""),
            _input_row("report", "report", reference_id=""),
        ]

        errors, warnings, summary = target_discovery.validate_input_rows(rows, require_files=False)

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(summary["dnaRowCount"], 1)
        self.assertEqual(summary["rnaRows"], 1)
        self.assertEqual(summary["proteinRows"], 1)
        self.assertEqual(summary["reportRows"], 1)

    def test_dna_board_keeps_surface_antigens_expression_unconfirmed(self):
        candidates = target_discovery.candidate_rows()
        _locus_rows, board = target_discovery.build_dna_board(
            candidates,
            [
                _dna("trop2", copy_number_status="neutral"),
                _dna("her2", gene_symbol="ERBB2", copy_number_status="amplification"),
            ],
        )

        trop2 = _by_id(board, "trop2")
        her2 = _by_id(board, "her2")
        self.assertEqual(trop2["overall_status"], "partial_evidence")
        self.assertEqual(trop2["candidate_class"], "genomically_supported_expression_unconfirmed")
        self.assertEqual(trop2["rna_status"], "no_call")
        self.assertEqual(trop2["protein_status"], "no_call")
        self.assertEqual(her2["candidate_class"], "copy_gain_expression_unconfirmed")
        self.assertNotEqual(her2["overall_status"], "ready")

    def test_dna_board_routes_cdk12_rb1_ccne1_and_b2m_boundaries(self):
        _locus_rows, board = target_discovery.build_dna_board(
            target_discovery.candidate_rows(),
            [
                _dna("cdk12", gene_symbol="CDK12", copy_number_status="amplification"),
                _dna("rb1", gene_symbol="RB1", copy_number_status="focal_loss"),
                _dna("ccne1", gene_symbol="CCNE1", copy_number_status="amplification"),
                _dna("b2m", gene_symbol="B2M", variant_effect="frameshift"),
            ],
        )

        self.assertEqual(_by_id(board, "cdk12")["candidate_class"], "ddr_transcriptional_cdk_followup")
        self.assertEqual(_by_id(board, "rb1")["candidate_class"], "not_supported_candidate")
        self.assertIn("loss or disruption", _by_id(board, "rb1")["sample_support_summary"])
        self.assertEqual(_by_id(board, "ccne1")["candidate_class"], "cell_cycle_resistance_context")
        self.assertEqual(_by_id(board, "b2m")["target_family"], "bispecific_antigen")
        self.assertEqual(_by_id(board, "b2m")["overall_status"], "not_supported")

    def test_rna_evidence_supports_expression_without_protein_confirmation(self):
        _locus_rows, board = target_discovery.build_dna_board(
            target_discovery.candidate_rows(),
            [
                _dna("trop2", copy_number_status="neutral"),
                _dna("ugt1a1", copy_number_status="neutral"),
            ],
            [
                _rna("trop2", read_count=127),
                _rna("ugt1a1", read_count=20),
            ],
        )

        trop2 = _by_id(board, "trop2")
        self.assertEqual(trop2["overall_status"], "partial_evidence")
        self.assertEqual(trop2["candidate_class"], "expression_supported_protein_unconfirmed")
        self.assertEqual(trop2["rna_status"], "partial_evidence")
        self.assertEqual(trop2["protein_status"], "no_call")
        self.assertIn("surface protein", trop2["sample_blockers"].lower())
        self.assertEqual(_by_id(board, "ugt1a1")["rna_status"], "no_call")

    def test_build_target_dna_evidence_counts_bam_loci_without_variant_or_cnv_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_csv(
                root / "manifests/target_gene_loci_hs37d5.csv",
                [
                    {
                        "target_id": "trop2",
                        "gene_symbol": "TACSTD2",
                        "contig": "1",
                        "start": "100",
                        "end": "200",
                    },
                    {
                        "target_id": "her2",
                        "gene_symbol": "ERBB2",
                        "contig": "17",
                        "start": "300",
                        "end": "400",
                    },
                ],
            )

            counts = {
                ("tumor.bam", "tumor.bai", "1:100-200"): 20,
                ("normal.bam", "normal.bai", "1:100-200"): 30,
                ("tumor.bam", "tumor.bai", "17:300-400"): 3,
                ("normal.bam", "normal.bai", "17:300-400"): 30,
            }

            def fake_count(bam: str, bai: str, region: str) -> int:
                return counts[(bam, bai, region)]

            with (
                patch.object(build_target_dna_evidence, "path_from_root", lambda relative: root / relative),
                patch.object(target_discovery, "path_from_root", lambda relative: root / relative),
                patch.object(
                    build_target_dna_evidence,
                    "run_samtools_count",
                    lambda bam, bai, region, timeout_seconds: build_target_dna_evidence.CountResult(
                        fake_count(bam, bai, region),
                        "passed",
                    ),
                ),
                patch.dict(
                    "os.environ",
                    {
                        "TARGET_DISCOVERY_TUMOR_BAM": "tumor.bam",
                        "TARGET_DISCOVERY_TUMOR_BAI": "tumor.bai",
                        "TARGET_DISCOVERY_NORMAL_BAM": "normal.bam",
                        "TARGET_DISCOVERY_NORMAL_BAI": "normal.bai",
                    },
                    clear=False,
                ),
            ):
                build_target_dna_evidence.main()

            rows = utils.parse_csv(utils.read_text(root / target_discovery.TARGET_DNA_EVIDENCE_DEFAULT))

        trop2 = _by_id(rows, "trop2")
        her2 = _by_id(rows, "her2")
        self.assertEqual(trop2["callability_status"], "callable")
        self.assertEqual(her2["callability_status"], "missing")
        self.assertEqual(trop2["copy_number_status"], "no_call")
        self.assertEqual(trop2["variant_effect"], "no_call")
        self.assertIn("variant, CNV, HLA-loss, RNA, and protein evidence remain no_call", trop2["evidence_detail"])

    def test_analyze_and_packet_commands_write_custody_bound_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_csv(root / target_discovery.TARGET_DISCOVERY_CANDIDATES, target_discovery.candidate_rows())
            utils.write_csv(
                root / target_discovery.TARGET_DNA_EVIDENCE_DEFAULT,
                [
                    _dna("trop2"),
                    _dna("her2", gene_symbol="ERBB2", copy_number_status="amplification"),
                    _dna("ccne1", gene_symbol="CCNE1", copy_number_status="amplification"),
                ],
            )

            with (
                patch.object(analyze_dna_targets, "path_from_root", lambda relative: root / relative),
                patch.object(build_rosalind_target_packet, "path_from_root", lambda relative: root / relative),
                patch.object(target_discovery, "path_from_root", lambda relative: root / relative),
                patch.dict("os.environ", {"ROSALIND_TARGET_SAMPLE": "Diana", "ROSALIND_TARGET_RUN_ID": "unit"}, clear=False),
            ):
                analyze_dna_targets.main()
                build_rosalind_target_packet.main()

            packet_root = root / "results/rosalind_targets/diana/unit"
            board = utils.parse_csv(utils.read_text(packet_root / "candidate_target_board.csv"))
            source_index = utils.read_json(packet_root / "input_evidence_index.json")
            reviewer_packet = utils.read_text(packet_root / "reviewer_packet.md")
            candidate_board = utils.read_text(packet_root / "candidate_target_board.csv")

        self.assertEqual(_by_id(board, "her2")["candidate_class"], "copy_gain_expression_unconfirmed")
        self.assertEqual(_by_id(board, "her2")["protein_status"], "no_call")
        self.assertTrue(all(row["sha256"] for row in source_index["rows"]))
        self.assertIn("RNA expression, cell-surface protein abundance", reviewer_packet)
        forbidden = [
            "treatment recommendation",
            "response predicted",
            "sacituzumab sensitive",
            "TROP-2 positive",
            "HER2 positive",
            "CDK12 inhibitor sensitive",
            "CDK4/6 resistant",
        ]
        for phrase in forbidden:
            self.assertNotIn(phrase, reviewer_packet)
            self.assertNotIn(phrase, candidate_board)

    def test_packet_rejects_duplicate_board_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_csv(root / target_discovery.TARGET_DISCOVERY_CANDIDATES, target_discovery.candidate_rows())
            board_root = root / target_discovery.TARGET_DISCOVERY_RESULTS
            board_root.mkdir(parents=True)
            _locus, board = target_discovery.build_dna_board(target_discovery.candidate_rows(), [_dna("trop2")])
            board.append(dict(board[0]))
            utils.write_csv(board_root / "candidate_target_board.csv", board)
            utils.write_csv(board_root / "dna_target_locus_summary.csv", _locus)

            with (
                patch.object(build_rosalind_target_packet, "path_from_root", lambda relative: root / relative),
                patch.object(target_discovery, "path_from_root", lambda relative: root / relative),
                self.assertRaises(SystemExit) as raised,
            ):
                build_rosalind_target_packet.main()

        self.assertIn("duplicate target_id", str(raised.exception))

    def test_packet_rejects_duplicate_json_source_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_csv(root / target_discovery.TARGET_DISCOVERY_CANDIDATES, target_discovery.candidate_rows())
            result_root = root / target_discovery.TARGET_DISCOVERY_RESULTS
            result_root.mkdir(parents=True)
            result_root.joinpath("input_validation_summary.json").write_text('{"status":"stale","status":"passed"}\n', encoding="utf-8")

            with (
                patch.object(build_rosalind_target_packet, "path_from_root", lambda relative: root / relative),
                patch.object(target_discovery, "path_from_root", lambda relative: root / relative),
                self.assertRaises(target_discovery.TargetDiscoveryError),
            ):
                build_rosalind_target_packet.main()

    def test_validate_candidate_board_rejects_unsafe_status_cells(self):
        _locus, board = target_discovery.build_dna_board(target_discovery.candidate_rows(), [_dna("trop2")])
        board[0]["overall_status"] = " partial_evidence"
        board[1]["sample_blockers"] = "unsafe|cell"

        errors = "\n".join(target_discovery.validate_candidate_board(board))

        self.assertIn("padded overall_status", errors)
        self.assertIn("unsafe sample_blockers", errors)

    def test_build_template_writes_candidate_manifest_and_input_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(build_target_template, "path_from_root", lambda relative: root / relative):
                build_target_template.main()

            self.assertTrue((root / target_discovery.TARGET_DISCOVERY_CANDIDATES).exists())
            self.assertTrue((root / target_discovery.TARGET_DISCOVERY_TEMPLATE).exists())
            self.assertEqual(utils.read_json(root / "results/target_discovery/input_contract.json")["status"], "template_ready")

    def test_verify_target_inputs_main_writes_no_interpretation_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = root / target_discovery.TARGET_DISCOVERY_DEFAULT
            utils.write_csv(inputs, [_input_row("dna", "dna", reference_id="hg38", path="")])

            with patch.object(verify_target_inputs, "path_from_root", lambda relative: root / relative):
                verify_target_inputs.main()

            summary = utils.read_json(root / "results/target_discovery/input_validation_summary.json")
            self.assertEqual(summary["status"], "passed")
            self.assertIn("never scores", summary["interpretationBoundary"])

    def test_verify_modal_packet_accepts_public_raw_mount_without_promoting_targets(self):
        packet = _modal_packet(raw_data_mounted=True)

        with patch.dict("os.environ", {"MODAL_TARGET_ALLOW_RAW": "1"}, clear=False):
            errors = verify_modal_target_packet.validate_modal_target_packet(packet)

        self.assertEqual(errors, [])

    def test_verify_modal_packet_accepts_rna_support_without_protein_confirmation(self):
        packet = _modal_packet(raw_data_mounted=True)
        summary = cast(dict[str, Any], packet["boardSummary"])
        summary["rnaEvidenceRows"] = 37
        summary["trop2RnaStatus"] = "partial_evidence"

        with patch.dict("os.environ", {"MODAL_TARGET_ALLOW_RAW": "1"}, clear=False):
            errors = verify_modal_target_packet.validate_modal_target_packet(packet)

        self.assertEqual(errors, [])

    def test_verify_modal_packet_requires_explicit_raw_mount_acceptance(self):
        packet = _modal_packet(raw_data_mounted=True)

        errors = verify_modal_target_packet.validate_modal_target_packet(packet)

        self.assertIn("MODAL_TARGET_ALLOW_RAW=1 is required to accept a raw mounted-BAM packet", errors)


def _input_row(evidence_id: str, layer: str, *, path: str = "", reference_id: str = "hg38") -> dict[str, str]:
    return {
        "evidence_id": evidence_id,
        "patient_id": "DIANA",
        "sample_id": "sample",
        "pair_id": "pair",
        "role": "tumor",
        "assay": "WGS" if layer == "dna" else "RNA",
        "evidence_layer": layer,
        "data_type": "SUMMARY",
        "path": path,
        "index_path": "",
        "reference_id": reference_id,
        "gene_symbol": "",
        "target_id": "",
        "source_name": "unit",
        "status": "present",
        "notes": "",
        "caveat": "",
    }


def _dna(
    target_id: str,
    *,
    gene_symbol: str = "",
    callability_status: str = "callable",
    copy_number_status: str = "neutral",
    variant_effect: str = "none",
    hla_loss_status: str = "none",
) -> dict[str, str]:
    return {
        "target_id": target_id,
        "gene_symbol": gene_symbol,
        "callability_status": callability_status,
        "copy_number_status": copy_number_status,
        "variant_effect": variant_effect,
        "hla_loss_status": hla_loss_status,
        "evidence_detail": "unit",
    }


def _rna(target_id: str, *, read_count: int = 20) -> dict[str, str]:
    return {
        "target_id": target_id,
        "gene_symbol": "",
        "rna_status": "detected",
        "read_count": str(read_count),
        "evidence_detail": "unit",
    }


def _by_id(rows: list[dict[str, str]], target_id: str) -> dict[str, str]:
    return next(row for row in rows if row["target_id"] == target_id)


def _modal_packet(*, raw_data_mounted: bool) -> dict[str, object]:
    return {
        "schema": "diana_modal_target_packet.v1",
        "status": "partial_evidence",
        "execution": {
            "runtime": "modal",
            "s3Mount": "modal.CloudBucketMount",
            "rawDataMounted": raw_data_mounted,
        },
        "inputEvidence": [
            {
                "path": "/s3/raw/manifest.csv",
                "bytes": 100,
                "sha256": "a" * 64,
            },
        ],
        "outputs": [
            {
                "path": "/s3/out/candidate_target_board.csv",
                "bytes": 100,
                "sha256": "b" * 64,
            },
        ],
        "boardSummary": {
            "candidateRows": 37,
            "partialEvidenceRows": 37,
            "readyRows": 0,
            "callableRows": 37,
            "trop2Status": "partial_evidence",
            "trop2RnaStatus": "no_call",
            "trop2ProteinStatus": "no_call",
        },
        "boundary": (
            "Modal consumed public mounted raw BAM indexes for DNA locus callability only; "
            "raw BAM range counts do not call RNA expression, surface protein abundance, or drug sensitivity."
        ),
    }


if __name__ == "__main__":
    unittest.main()
