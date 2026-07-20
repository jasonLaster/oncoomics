import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Callable, Dict, Optional
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands.hrd_context import build_rosalind_hrd_packet as packet
from diana_omics.commands.phase3_wgs import stage_phase3_fast_deterministic_report as stage_phase3_fast_report
from tests.test_phase3_fast_deterministic_report import (
    _crosscheck_materialization_plan,
    _write_final_manifest,
)

PHASE3_FAST_FORBIDDEN_TOKENS_JSON = json.dumps(["UNIT-FORBIDDEN-PHASE3-FAST"])


def write_duplicate_json_field(path: Path, key: str, stale_value: object) -> None:
    payload = utils.read_json(path)
    text = json.dumps(payload, indent=2, sort_keys=True)
    current = f'  "{key}": {json.dumps(payload[key], sort_keys=True)}'
    if text.count(current) != 1:
        raise AssertionError(f"expected exactly one top-level JSON field {key}")
    duplicate = f'  "{key}": {json.dumps(stale_value, sort_keys=True)},\n{current}'
    path.write_text(text.replace(current, duplicate, 1) + "\n", encoding="utf-8")


def write_diana_wgs_worker_artifacts(root: Path, readiness_overrides: Optional[Dict[str, str]] = None) -> None:
    readiness_overrides = readiness_overrides or {}
    readiness = [
        {
            "evidence_surface": surface,
            "status": readiness_overrides.get(surface, status),
            "detail": detail,
        }
        for surface, status, detail in (
            ("source_sha256", "ready", "Payload checksums passed."),
            ("wgs_alignment", "ready", "Tumor and normal alignment passed."),
            ("matched_normal_somatic_variants", "ready", "Matched-normal calling passed."),
            ("coverage_cnv", "partial_evidence", "Coverage bins are not allele-specific."),
            ("sbs96", "partial_evidence", "SBS96 input exists without SBS3 assignment."),
            ("sv", "partial_evidence", "BAM-derived counts are not an SV callset."),
            ("scarHRD", "no_call", "Allele-specific segments and purity/ploidy are absent."),
            ("CHORD", "no_call", "A validated production SV callset is absent."),
            ("HRDetect", "no_call", "The calibrated integrated feature model is absent."),
            ("overall_hrd", "no_call", "No defensible scalar HRD classification is available."),
        )
    ]
    utils.write_json(
        root / "diana_hrd_summary.json",
        {
            "status": "no_call",
            "evidence_status": "partial_evidence",
            "run_id": "unit-worker-run",
            "input": {
                "dataset": "SENSITIVE-DATASET-LABEL",
                "pair": "SENSITIVE-PAIR-ID",
                "lanes": 2,
                "reference": "hg38 analysis reference",
                "source_integrity": "passed",
            },
            "hrd_readiness": readiness,
            "boundary": "Research-use output with no clinical or scalar HRD conclusion authorized.",
        },
    )
    utils.write_csv(root / "hrd_readiness.csv", readiness)
    alignment_rows = [
        {"status": "passed", "role": "tumor", "total_reads": 100, "mapped_reads": 98},
        {"status": "passed", "role": "normal", "total_reads": 100, "mapped_reads": 99},
    ]
    utils.write_json(root / "alignment/bam_validation_summary.json", {"status": "passed", "rows": alignment_rows})
    utils.write_json(
        root / "variants/mutect2_summary.json",
        {
            "status": "passed",
            "total_filtered_records": 321,
            "pass_records": 123,
            "pass_snvs": 100,
            "pass_indels": 23,
            "brca1_brca2_pass_region_records": 1,
        },
    )
    utils.write_csv(
        root / "variants/brca1_brca2_pass_variants.csv",
        [{"contig": "chr17", "position": "100", "annotation_status": "region_only_requires_variant_annotation_review"}],
    )
    utils.write_json(
        root / "cnv/coverage_cnv_summary.json",
        {"status": "partial_evidence", "bin_count": 600, "relative_gain_bins": 4, "relative_loss_bins": 5},
    )
    cnv_rows = []
    for index in range(600):
        coverage_class = (
            "relative_gain" if index < 4 else "relative_loss" if index < 9 else "neutral_or_low_signal"
        )
        cnv_rows.append(
            {"contig": "chr1", "start": index * 5_000_000, "end": (index + 1) * 5_000_000, "coverage_class": coverage_class}
        )
    utils.write_csv(root / "cnv/coverage_cnv_bins.csv", cnv_rows)
    utils.write_json(
        root / "signatures/signature_assignment_summary.json",
        {
            "status": "partial_evidence",
            "usable_snv_records": 100,
            "sbs96_rows": 96,
            "sigprofiler_assignment_status": "input_ready_threshold_met",
            "sbs3_status": "no_call_signature_assignment_and_threshold_policy_not_locked",
        },
    )
    substitutions = ("C>A", "C>G", "C>T", "T>A", "T>C", "T>G")
    bases = ("A", "C", "G", "T")
    sbs_rows = []
    for substitution in substitutions:
        for left in bases:
            for right in bases:
                sbs_rows.append(
                    {
                        "mutation_type": substitution,
                        "trinucleotide": f"{left}[{substitution}]{right}",
                        "count": 2 if len(sbs_rows) < 4 else 1,
                    }
                )
    utils.write_csv(root / "signatures/wgs_sbs96_matrix.csv", sbs_rows)
    sv_rows = [
        {
            "status": "partial_evidence", "role": "tumor", "total_alignments": 100,
            "discordant_mapped_pairs": 20, "supplementary_alignments": 10,
            "interchromosomal_pairs": 4, "large_insert_pairs": 16,
        },
        {
            "status": "partial_evidence", "role": "normal", "total_alignments": 100,
            "discordant_mapped_pairs": 8, "supplementary_alignments": 3,
            "interchromosomal_pairs": 2, "large_insert_pairs": 6,
        },
    ]
    utils.write_json(
        root / "sv/sv_evidence_summary.json",
        {"status": "partial_evidence", "rows": sv_rows, "production_sv_callset_status": "no_call"},
    )
    utils.write_csv(root / "sv/sv_evidence_summary.csv", sv_rows)
    utils.write_json(
        root / "tool_versions.json",
        {"bwa": "bwa 0.7.17", "samtools": "samtools 1.20", "bcftools": "bcftools 1.20", "gatk": "gatk 4.6.1.0"},
    )


def write_deterministic_report(root: Path, artifact_root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    input_rows = []
    source_sha256 = {}
    for relative, input_id in packet.DIANA_WGS_DETERMINISTIC_INPUTS.items():
        path = artifact_root / relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        source_sha256[input_id] = digest
        input_rows.append(
            {
                "input_id": input_id,
                "path": f"artifact-root/{relative}",
                "bytes": path.stat().st_size,
                "sha256": digest,
            }
        )
    utils.write_csv(root / "input_sha256.csv", input_rows)
    utils.write_csv(root / "readiness.csv", [{"evidence_surface": "overall_hrd", "state": "no_call", "reason": "unit"}])
    utils.write_json(
        root / "evidence_checks.json",
        {
            "status": "passed",
            "report_status": "partial_evidence",
            "overall_hrd_status": "no_call",
            "checks": [{"check_id": "unit_contract", "status": "passed", "detail": "synthetic"}],
            "input_sha256": input_rows,
        },
    )
    utils.write_json(
        root / "crosscheck_input_plans.json",
        {
            "schema_version": 1,
            "plan_type": "terminal_crosscheck_input_materialization_plan",
            "status": "materialized",
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "routes": {
                "sequenza_scarhrd": {
                    "status": "inputs_materialized",
                    "execution_status": "not_run",
                    "interpretation_status": "no_call",
                },
                "sigprofiler_sbs3": {
                    "status": "inputs_materialized",
                    "execution_status": "not_run",
                    "interpretation_status": "no_call",
                },
            },
        },
    )
    (root / "report.md").write_text("# Deterministic full-WGS unit report\n", encoding="utf-8")
    support_sha256 = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in packet.DETERMINISTIC_SUPPORT_FILES
    }
    utils.write_json(
        root / "report_manifest.json",
        {
            "schema_version": 1,
            "method_id": "deterministic_full_wgs",
            "report_kind": "deterministic_baseline",
            "evidence_status": "partial_evidence",
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "support_sha256": support_sha256,
            "source_sha256": source_sha256,
            "report_sha256": hashlib.sha256((root / "report.md").read_bytes()).hexdigest(),
            "review_summary": {
                "overall": {"evidence_status": "partial_evidence", "authorized_hrd_state": "no_call"},
                "custody": {
                    "private_freeze_status": "passed",
                    "exact_kms_match": True,
                    "freeze_receipt_version_id": "freeze-version-unit",
                    "stage_provenance_receipt_version_id": "stage-version-unit",
                    "freeze_receipt_sha256": "a" * 64,
                    "stage_provenance_receipt_sha256": "b" * 64,
                },
            },
        },
    )
    return root


def write_phase3_fast_deterministic_report(root: Path) -> tuple[Path, Path]:
    final_manifest_path, final_root, final_manifest = _write_final_manifest(root)
    deterministic_root = root / "deterministic"
    stage_phase3_fast_report.stage_phase3_fast_deterministic_report(
        final_manifest,
        _crosscheck_materialization_plan(final_manifest, final_manifest_path),
        final_manifest_sha256=hashlib.sha256(final_manifest_path.read_bytes()).hexdigest(),
        final_manifest_bytes=final_manifest_path.stat().st_size,
        final_root=final_root,
        output_dir=deterministic_root,
    )
    return deterministic_root, final_root


def mutate_phase3_fast_crosscheck_plans(
    deterministic_root: Path,
    mutation: Callable[[dict], None],
) -> None:
    plans_path = deterministic_root / "crosscheck_input_plans.json"
    plans = utils.read_json(plans_path)
    mutation(plans)
    utils.write_json(plans_path, plans)

    report_manifest_path = deterministic_root / "report_manifest.json"
    report_manifest = utils.read_json(report_manifest_path)
    report_manifest["support_sha256"]["crosscheck_input_plans.json"] = (
        hashlib.sha256(plans_path.read_bytes()).hexdigest()
    )
    utils.write_json(report_manifest_path, report_manifest)


def mutate_phase3_fast_report_manifest(
    deterministic_root: Path,
    mutation: Callable[[dict], None],
) -> None:
    report_manifest_path = deterministic_root / "report_manifest.json"
    report_manifest = utils.read_json(report_manifest_path)
    mutation(report_manifest)
    utils.write_json(report_manifest_path, report_manifest)


def phase3_fast_process_binding() -> dict:
    return {
        "binding_kind": "phase3_fast_final",
        "deterministic_report_sha256": "c" * 64,
        "deterministic_manifest_sha256": "d" * 64,
        "artifact_count": 12,
        "phase3_fast": {
            "workflow": {
                "name": "phase3_wgs_fast",
                "parameter_sha256": "2" * 64,
                "source_commit": "abcd1234",
            },
            "crosscheck_input_plans": {
                "sigprofiler_sbs3": "awaiting_private_results_freeze",
                "sequenza_scarhrd": "blocked",
            },
            "sequenza_scarhrd_alias_input_contract": {
                "schema_version": 1,
                "route": "sequenza_scarhrd",
                "status": "blocked",
                "run_alias": "subject01",
                "planned_aliases": {
                    "tumor": "subject01_tumor",
                    "normal": "subject01_normal",
                },
                "planned_alias_outputs": {
                    "tumor_bam": "tumor.bam",
                    "tumor_bai": "tumor.bam.bai",
                    "normal_bam": "normal.bam",
                    "normal_bai": "normal.bam.bai",
                    "staged_validation": "staged_input_validation.json",
                },
                "method_parameters": {
                    "sequenza": {
                        "female": True,
                    },
                },
                "reference": {
                    "build": "GRCh38",
                },
                "artifacts": {
                    "tumor_bam": {},
                    "tumor_bai": {},
                    "normal_bam": {},
                    "normal_bai": {},
                },
                "attestations": {
                    "input_sha256_verified": True,
                    "bam_quickcheck_passed": True,
                    "bam_reference_digest_matched": True,
                    "no_direct_identifiers_in_aliases": True,
                    "final_bam_contract_published": False,
                    "validated_sequenza_scarhrd_runtime": False,
                },
            },
        },
    }


def phase3_fast_ai_provenance_binding() -> dict:
    binding = phase3_fast_process_binding()
    binding["phase3_fast"]["run"] = {
        "run_id": "diana-wgs-hrd-20260716T033101Z",
        "subject_alias": "subject01",
        "pair_id": "subject01-tumor-normal",
    }
    compact = binding["phase3_fast"]["sequenza_scarhrd_alias_input_contract"]
    sha256 = "3" * 64
    version_id = "sequenza-ai-version"
    compact["reference"] = {
        "build": "GRCh38",
        "fasta": {"bytes": 1, "sha256": sha256, "version_id": version_id},
        "fai": {"bytes": 2, "sha256": sha256, "version_id": version_id},
        "sequence_dictionary": {
            "bytes": 3,
            "sha256": sha256,
            "version_id": version_id,
        },
    }
    compact["artifacts"] = {
        "tumor_bam": {"bytes": 4, "sha256": sha256, "version_id": version_id},
        "tumor_bai": {"bytes": 5, "sha256": sha256, "version_id": version_id},
        "normal_bam": {"bytes": 6, "sha256": sha256, "version_id": version_id},
        "normal_bai": {"bytes": 7, "sha256": sha256, "version_id": version_id},
    }
    return binding


def write_staged_rosalind_packet(root: Path) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    for name in packet.PACKET_REPORT_SUPPORT_FILES:
        (root / name).write_text(f"{name}\n", encoding="utf-8")
    (root / "report.md").write_text("report\n", encoding="utf-8")
    utils.write_json(
        root / "report_manifest.json",
        {
            "schema_version": 1,
            "method_id": "rosalind_diana_wgs",
            "support_sha256": {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in packet.PACKET_REPORT_SUPPORT_FILES
            },
            "report_sha256": hashlib.sha256(
                (root / "report.md").read_bytes()
            ).hexdigest(),
        },
    )
    return [root / name for name in packet.PACKET_REPORT_FILES]


def rewrite_packet_report_with_text(root: Path, text: str) -> None:
    (root / "reviewer_packet.md").write_text(text, encoding="utf-8")
    (root / "report.md").write_text(text, encoding="utf-8")
    manifest = utils.read_json(root / "report_manifest.json")
    manifest["support_sha256"]["reviewer_packet.md"] = packet.sha256_file(
        root / "reviewer_packet.md"
    )
    manifest["report_sha256"] = packet.sha256_file(root / "report.md")
    utils.write_json(root / "report_manifest.json", manifest)


def write_diana_raw_intake_artifacts(root: Path) -> None:
    utils.write_csv(
        root / "manifests/diana_raw_inputs.template.csv",
        [{"patient_id": "DIANA", "sample_id": "DIANA-TUMOR-DNA"}],
    )
    utils.write_text(root / "docs/operations/diana-raw-inputs.md", "# Diana Raw Inputs")
    utils.write_json(
        root / "results/diana_raw_intake/input_contract.json",
        {
            "requiredColumns": ["patient_id", "pair_id", "sample_id"],
            "dnaAssays": ["WGS", "WES"],
            "dataTypes": ["FASTQ", "BAM", "CRAM"],
            "handoffPlanCommand": "PYTHONPATH=src /usr/bin/python3 -m diana_omics plan:diana-raw-handoff",
            "validationCommand": "DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw",
            "recomputeCommand": "DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics stage:diana-raw",
        },
    )
    utils.write_json(
        root / "results/diana_raw_intake/intake_readiness_summary.json",
        {
            "status": "template_ready",
            "template": "manifests/diana_raw_inputs.template.csv",
            "actualSamplesheet": "manifests/diana_raw_inputs.csv",
            "readyForDianaRawData": True,
        },
    )
    utils.write_json(
        root / "results/diana_raw_intake/input_validation_summary.json",
        {
            "status": "waiting_for_diana_raw_data",
            "summary": {
                "rowCount": 0,
                "dnaRowCount": 0,
                "tumorDnaRows": 0,
                "normalDnaRows": 0,
                "matchedPairIds": [],
            },
        },
    )
    utils.write_json(
        root / "results/diana_raw_intake/dinah_handoff_plan.json",
        {
            "status": "waiting_for_dinah_files",
            "samplesheet": "manifests/diana_raw_inputs.csv",
            "analysisId": "unit",
            "currentState": {"status": "waiting_for_dinah_files"},
            "handoffSteps": [
                {"name": "strict_validate_diana_inputs"},
                {"name": "stage_diana_raw_analysis_packet"},
            ],
        },
    )


class RosalindHrdPacketTest(unittest.TestCase):
    def test_schema_version_checks_use_exact_integer_helper(self):
        for value, expected, accepted in (
            (1, 1, True),
            (2, 2, True),
            (True, 1, False),
            (1.0, 1, False),
            ("1", 1, False),
            (None, 1, False),
        ):
            with self.subTest(value=value):
                self.assertIs(packet.is_exact_int(value, expected), accepted)

    def test_optional_counts_reject_json_bool_float_and_padded_text(self):
        self.assertEqual(packet.optional_nonnegative_int(None, "optional count"), 0)
        self.assertEqual(packet.optional_nonnegative_int("", "optional count"), 0)
        self.assertEqual(packet.optional_nonnegative_int(12, "optional count"), 12)
        self.assertEqual(packet.optional_nonnegative_int("12", "optional count"), 12)

        for value in (True, False, 1.0, " 1", "1\n", "-1", [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError,
                    "optional count must be a non-negative integer or blank",
                ):
                    packet.optional_nonnegative_int(value, "optional count")

    def test_hcc1395_wgs_packet_rejects_boolean_sv_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(
                root / "results/phase3_wgs_smoke/sv_evidence_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "status": "passed",
                            "tool": "samtools view flag/evidence counters",
                            "discordant_mapped_pairs": True,
                            "chord_input_status": "not_assessable_requires_validated_sv_caller_vcf",
                        }
                    ],
                },
            )

            with (
                patch.object(packet, "path_from_root", lambda relative: root / relative),
                self.assertRaisesRegex(
                    ValueError,
                    "HCC1395 WGS SV discordant_mapped_pairs must be a "
                    "non-negative integer or blank",
                ),
            ):
                packet.hcc1395_wgs_evidence()

    def test_hcc1395_wgs_packet_rejects_malformed_sv_rows(self):
        cases = (
            ("missing", None),
            ("empty", []),
            ("object", {}),
            ("non_object_row", [{"discordant_mapped_pairs": 1}, True]),
        )

        for label, rows in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                sv_summary = {"status": "passed"}
                if label != "missing":
                    sv_summary["rows"] = rows
                utils.write_json(
                    root / "results/phase3_wgs_smoke/sv_evidence_summary.json",
                    sv_summary,
                )

                with (
                    patch.object(packet, "path_from_root", lambda relative: root / relative),
                    self.assertRaisesRegex(
                        ValueError,
                        (
                            "HCC1395 WGS SV evidence rows must be a non-empty "
                            "list of JSON objects"
                        ),
                    ),
                ):
                    packet.hcc1395_wgs_evidence()

    def test_schema_version_checks_avoid_raw_comparisons(self):
        source = Path(packet.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(packet.__file__))

        raw_schema_version_comparisons = [
            f"{node.lineno}: {ast.get_source_segment(source, node)}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Compare)
            and "schema_version" in (ast.get_source_segment(source, node) or "")
        ]

        self.assertEqual(raw_schema_version_comparisons, [])

    def test_sha256_file_rejects_symlinked_leaf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_source = root / "real-source.json"
            source_link = root / "report_manifest.json"
            real_source.write_text("{}\n", encoding="utf-8")
            source_link.symlink_to(real_source)

            with self.assertRaisesRegex(
                ValueError,
                "report_manifest.json SHA-256 input must be a regular "
                "non-symlink file",
            ):
                packet.sha256_file(source_link)

    def test_sha256_file_rejects_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_sources = root / "real-sources"
            linked_sources = root / "linked-sources"
            real_sources.mkdir()
            (real_sources / "report_manifest.json").write_text(
                "{}\n",
                encoding="utf-8",
            )
            linked_sources.symlink_to(real_sources, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "report_manifest.json SHA-256 input parent may not be a symlink",
            ):
                packet.sha256_file(linked_sources / "report_manifest.json")

    def test_sha256_file_rejects_input_that_changes_during_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report_manifest.json"
            path.write_text('{"status":"stable"}\n', encoding="utf-8")
            original_sha256_file_once = packet.sha256_file_once
            mutated = False

            def mutate_after_first_hash(input_path: Path) -> str:
                nonlocal mutated
                digest = original_sha256_file_once(input_path)
                if input_path == path and not mutated:
                    mutated = True
                    path.write_text('{"status":"rewritten"}\n', encoding="utf-8")
                return digest

            with (
                patch.object(
                    packet,
                    "sha256_file_once",
                    side_effect=mutate_after_first_hash,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report_manifest.json SHA-256 input changed during read",
                ),
            ):
                packet.sha256_file(path)

    def test_artifact_index_rejects_symlinked_present_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_source = root / "real-source.json"
            source_link = root / "source.json"
            real_source.write_text("{}\n", encoding="utf-8")
            source_link.symlink_to(real_source)

            with (
                patch.dict(
                    "os.environ",
                    {"ROSALIND_HRD_ARTIFACT_ROOT": str(root)},
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "source.json SHA-256 input must be a regular "
                    "non-symlink file",
                ),
            ):
                packet.artifact_index(("source.json",))

    def test_packet_file_writes_are_create_only_and_fsynced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "results/rosalind_hrd/unit/report.md"

            with patch.object(
                packet.os,
                "fsync",
                wraps=packet.os.fsync,
            ) as fsync:
                packet.write_text_create_only(destination, "one")

            self.assertEqual(destination.read_text(encoding="utf-8"), "one\n")
            self.assertEqual(fsync.call_count, 2)

            with self.assertRaises(FileExistsError):
                packet.write_text_create_only(destination, "two")

            self.assertEqual(destination.read_text(encoding="utf-8"), "one\n")

    def test_packet_file_write_rehashes_after_directory_fsync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "results/rosalind_hrd/unit/report.md"
            original_fsync_directory = packet.fsync_directory

            def tamper_after_directory_fsync(path: Path) -> None:
                original_fsync_directory(path)
                destination.write_text("tampered\n", encoding="utf-8")

            with (
                patch.object(
                    packet,
                    "fsync_directory",
                    side_effect=tamper_after_directory_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "HRD packet output changed during write",
                ),
            ):
                packet.write_text_create_only(destination, "one")

            self.assertFalse(destination.exists())

    def test_hcc1395_wes_packet_writes_no_call_adapter_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(
                root / "results/full_wes_benchmark/full_wes_benchmark_summary.json",
                {
                    "status": "passed",
                    "bamValidationStatus": "passed",
                    "exactPassTruthMatches": 1122,
                    "exactPassRecall": 0.8585,
                    "exactPassPrecision": 0.9842,
                    "contaminationStatus": "passed",
                    "contaminationEstimate": "0.0",
                },
            )
            utils.write_json(root / "results/full_wes_benchmark/truth_overlap_benchmark_summary.json", {"status": "passed"})
            utils.write_csv(
                root / "results/full_wes_benchmark/full_wes_fastq_validation.csv",
                [{"status": "passed"}, {"status": "passed"}, {"status": "passed"}, {"status": "passed"}],
            )
            utils.write_csv(
                root / "results/full_wes_benchmark/full_wes_bam_validation.csv",
                [{"status": "passed"}, {"status": "passed"}],
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wes_summary.json",
                {"status": "expanded_non_dry_passed"},
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["hcc1395_wes"], "unit")

            self.assertEqual(summary["sampleSet"], "hcc1395_wes")
            reviewer = utils.read_text(root / "results/rosalind_hrd/hcc1395_wes/unit/reviewer_packet.md")
            adapter_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/hcc1395_wes/unit/hrd_adapter_status.csv"))
            self.assertIn("does not support a genome-wide HRD scar", reviewer)
            self.assertIn("no_call", {row["state"] for row in adapter_rows})

    def test_hcc1395_wes_packet_rejects_incomplete_source_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(
                root / "results/full_wes_benchmark/full_wes_benchmark_summary.json",
                {
                    "status": "passed",
                    "bamValidationStatus": "passed",
                    "exactPassTruthMatches": 1122,
                    "exactPassRecall": 0.8585,
                    "exactPassPrecision": 0.9842,
                    "contaminationStatus": "passed",
                    "contaminationEstimate": "0.0",
                },
            )
            utils.write_json(
                root / "results/full_wes_benchmark/truth_overlap_benchmark_summary.json",
                {"status": "passed"},
            )
            utils.write_csv(
                root / "results/full_wes_benchmark/full_wes_fastq_validation.csv",
                [
                    {"status": "passed"},
                    {"status": "passed"},
                    {"status": "passed"},
                    {"status": "passed"},
                ],
            )
            utils.write_csv(
                root / "results/full_wes_benchmark/full_wes_bam_validation.csv",
                [{"status": "passed"}, {"status": "passed"}],
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wes_summary.json",
                {"status": "expanded_non_dry_passed"},
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                packet.write_packet(packet.PACKET_SPECS["hcc1395_wes"], "unit")

            output_dir = root / "results/rosalind_hrd/hcc1395_wes/unit"
            manifest_path = output_dir / "report_manifest.json"
            manifest = utils.read_json(manifest_path)
            manifest["source_sha256"].pop("source_artifact_001")
            utils.write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                ValueError,
                "Rosalind report manifest source_sha256 is not exact",
            ):
                packet.require_rosalind_report_manifest(output_dir)

    def test_hcc1395_wgs_packet_blocks_metadata_only_sv_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(
                root / "results/phase3_wgs_smoke/phase3_wgs_summary.json",
                {
                    "status": "passed",
                    "fullSourceFastqs": True,
                    "readPairsPerEnd": 942559447,
                    "bamValidationStatus": "passed",
                    "mutect2Status": "skipped_public_bam_timing",
                    "truthVariantsDepthEligible": 0,
                    "exactPassTruthMatches": 0,
                    "coverageCnvStatus": "passed",
                    "coverageCnvBins": 631,
                    "sbs96MatrixStatus": "skipped_public_bam_timing",
                    "sbs96UsableSnvRecords": 0,
                },
            )
            for relative in [
                "results/phase3_wgs_smoke/bam_validation_summary.csv",
                "results/phase3_wgs_smoke/coverage_cnv_summary.json",
                "results/phase3_wgs_smoke/signature_assignment_summary.json",
                "results/clinicalization/hrd_interpretation_readiness_summary.json",
                "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wgs_summary.json",
            ]:
                if relative.endswith(".csv"):
                    utils.write_csv(root / relative, [{"status": "passed"}])
                else:
                    utils.write_json(root / relative, {"status": "passed", "rows": []})
            utils.write_json(
                root / "results/phase3_wgs_smoke/hrd_tool_readiness_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "tool": "CHORD",
                            "interpretability_status": "not_assessable_requires_validated_sv_caller_vcf",
                            "caveat": "needs validated SV caller",
                        }
                    ],
                },
            )
            utils.write_json(
                root / "results/phase3_wgs_smoke/sv_evidence_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "status": "passed",
                            "tool": "metadata_only",
                            "discordant_mapped_pairs": "",
                            "chord_input_status": "not_assessable_metadata_only",
                        }
                    ],
                },
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["hcc1395_wgs"], "unit")

            self.assertTrue(any("no discordant mapped-pair counts" in blocker for blocker in summary["blockers"]))
            next_actions = utils.read_text(root / "results/rosalind_hrd/hcc1395_wgs/unit/next_actions.md")
            self.assertIn("regenerate full SV evidence", next_actions)

    def test_hcc1395_wgs_packet_surfaces_interpretation_gaps_without_operational_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(
                root / "results/phase3_wgs_smoke/phase3_wgs_summary.json",
                {
                    "status": "passed",
                    "fullSourceFastqs": True,
                    "readPairsPerEnd": 568040077,
                    "bamValidationStatus": "passed",
                    "mutect2Status": "passed",
                    "truthVariantsDepthEligible": 300,
                    "exactPassTruthMatches": 268,
                    "coverageCnvStatus": "passed",
                    "coverageCnvBins": 631,
                    "sbs96MatrixStatus": "passed",
                    "sbs96UsableSnvRecords": 265,
                },
            )
            utils.write_csv(
                root / "results/phase3_wgs_smoke/bam_validation_summary.csv",
                [{"status": "passed"}],
            )
            utils.write_json(
                root / "results/phase3_wgs_smoke/coverage_cnv_summary.json",
                {"status": "passed"},
            )
            utils.write_json(
                root / "results/phase3_wgs_smoke/signature_assignment_summary.json",
                {"status": "passed"},
            )
            utils.write_json(
                root / "results/phase3_wgs_smoke/sv_evidence_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "discordant_mapped_pairs": 42,
                            "chord_input_status": "not_assessable_requires_validated_sv_caller_vcf",
                        }
                    ],
                },
            )
            utils.write_json(
                root / "results/phase3_wgs_smoke/hrd_tool_readiness_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "tool": "SigProfilerAssignment",
                            "interpretability_status": "input_ready_threshold_met",
                            "caveat": "SBS96 input exists, but assignment has not run.",
                        },
                        {
                            "tool": "scarHRD",
                            "interpretability_status": "no_call",
                            "caveat": "Allele-specific segments are absent.",
                        },
                        {
                            "tool": "CHORD",
                            "interpretability_status": "no_call",
                            "caveat": "A production SV callset is absent.",
                        },
                    ],
                },
            )
            utils.write_json(
                root / "results/clinicalization/hrd_interpretation_readiness_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "adapter_id": "scarhrd",
                            "interpretation_status": "no_call",
                            "no_call_reason": "Allele-specific CNV/LOH is unavailable.",
                            "required_inputs": "Total/minor copy number, purity, and ploidy.",
                        },
                        {
                            "adapter_id": "SBS3",
                            "interpretation_status": "no_call",
                            "no_call_reason": "Assignment and thresholds are not locked.",
                            "required_inputs": "Validated assignment and reconstruction metrics.",
                        },
                        {
                            "adapter_id": "chord",
                            "interpretation_status": "no_call",
                            "no_call_reason": "A production SV callset is unavailable.",
                            "required_inputs": "Validated SNV, indel, SV, and CNV features.",
                        },
                        {
                            "adapter_id": "HRDetect",
                            "interpretation_status": "no_call",
                            "no_call_reason": "The calibrated feature vector is unavailable.",
                            "required_inputs": "A locked six-feature input set and calibration.",
                        },
                    ],
                },
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wgs_summary.json",
                {"status": "passed"},
            )
            utils.write_json(
                root / "results/clinicalization/sv_caller_readiness_summary.json",
                {
                    "status": "partial_evidence",
                    "rows": [
                        {
                            "candidate_count": 4,
                            "phase3_discordant_mapped_pairs": 42,
                            "ready_for_clinical_interpretation": "no",
                        }
                    ],
                },
            )
            utils.write_json(
                root / "results/clinicalization/cnv_loh_readiness_summary.json",
                {
                    "status": "partial_evidence",
                    "rows": [
                        {
                            "phase3_cnv_bins": 631,
                            "current_bins_are_not_allele_specific_segments": "yes",
                            "ready_for_clinical_interpretation": "no",
                        }
                    ],
                },
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["hcc1395_wgs"], "unit")

            output_dir = root / "results/rosalind_hrd/hcc1395_wgs/unit"
            self.assertEqual(summary["blockers"], [])
            gap_names = [gap["adapter"].casefold() for gap in summary["interpretationGaps"]]
            self.assertIn("sigprofilerassignment", gap_names)
            self.assertIn("scarhrd", gap_names)
            self.assertIn("sbs3", gap_names)
            self.assertIn("chord", gap_names)
            self.assertIn("hrdetect", gap_names)
            self.assertEqual(gap_names.count("scarhrd"), 1)
            self.assertEqual(gap_names.count("chord"), 1)

            adapter_text = utils.read_text(output_dir / "hrd_adapter_status.csv")
            report = utils.read_text(output_dir / "report.md")
            next_actions = utils.read_text(output_dir / "next_actions.md")
            self.assertNotIn("input_ready_threshold_met", adapter_text)
            self.assertNotIn("input_ready_threshold_met", report)
            self.assertIn("input_matrix_ready_assignment_not_run", adapter_text)
            self.assertIn("## Interpretation Gaps", report)
            self.assertIn("## Operational/Data Blockers", report)
            self.assertIn("interpretation gaps above remain active", report)
            self.assertIn("## Interpretation Gaps", next_actions)

            manifest = utils.read_json(output_dir / "report_manifest.json")
            self.assertEqual(
                manifest["review_summary"]["interpretation_gaps"],
                summary["interpretationGaps"],
            )

    def test_hcc1395_wgs_packet_flags_stale_sv_readiness_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(root / "results/phase3_wgs_smoke/phase3_wgs_summary.json", {"status": "passed"})
            utils.write_json(root / "results/phase3_wgs_smoke/hrd_tool_readiness_summary.json", {"status": "passed", "rows": []})
            utils.write_json(root / "results/clinicalization/cnv_loh_readiness_summary.json", {"status": "passed", "rows": []})
            utils.write_json(root / "results/clinicalization/hrd_interpretation_readiness_summary.json", {"status": "passed", "rows": []})
            utils.write_json(root / "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wgs_summary.json", {"status": "passed"})
            utils.write_csv(root / "results/phase3_wgs_smoke/bam_validation_summary.csv", [{"status": "passed"}])
            utils.write_json(root / "results/phase3_wgs_smoke/coverage_cnv_summary.json", {"status": "passed"})
            utils.write_json(root / "results/phase3_wgs_smoke/signature_assignment_summary.json", {"status": "passed"})
            utils.write_json(
                root / "results/phase3_wgs_smoke/sv_evidence_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "status": "passed",
                            "tool": "metadata_only",
                            "discordant_mapped_pairs": "",
                            "chord_input_status": "not_assessable_metadata_only",
                        }
                    ],
                },
            )
            utils.write_json(
                root / "results/clinicalization/sv_caller_readiness_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "candidate_count": 4,
                            "phase3_discordant_mapped_pairs": 20,
                            "ready_for_clinical_interpretation": "no",
                        }
                    ],
                },
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["hcc1395_wgs"], "unit")

            self.assertTrue(any("SV readiness sidecar is stale" in blocker for blocker in summary["blockers"]))
            evidence_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/hcc1395_wgs/unit/sample_validation_summary.csv"))
            self.assertIn("sv_caller_readiness", {row["evidence_id"] for row in evidence_rows})

    def test_hcc1395_wgs_packet_flags_zero_sidecar_against_positive_sv_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(root / "results/phase3_wgs_smoke/phase3_wgs_summary.json", {"status": "passed"})
            utils.write_json(root / "results/phase3_wgs_smoke/hrd_tool_readiness_summary.json", {"status": "passed", "rows": []})
            utils.write_json(root / "results/clinicalization/cnv_loh_readiness_summary.json", {"status": "passed", "rows": []})
            utils.write_json(root / "results/clinicalization/hrd_interpretation_readiness_summary.json", {"status": "passed", "rows": []})
            utils.write_json(root / "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wgs_summary.json", {"status": "passed"})
            utils.write_csv(root / "results/phase3_wgs_smoke/bam_validation_summary.csv", [{"status": "passed"}])
            utils.write_json(root / "results/phase3_wgs_smoke/coverage_cnv_summary.json", {"status": "passed"})
            utils.write_json(root / "results/phase3_wgs_smoke/signature_assignment_summary.json", {"status": "passed"})
            utils.write_json(
                root / "results/phase3_wgs_smoke/sv_evidence_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "status": "passed",
                            "tool": "samtools view flag/evidence counters",
                            "discordant_mapped_pairs": 20,
                            "chord_input_status": "not_assessable_requires_validated_sv_caller_vcf",
                        }
                    ],
                },
            )
            utils.write_json(
                root / "results/clinicalization/sv_caller_readiness_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "candidate_count": 4,
                            "phase3_discordant_mapped_pairs": 0,
                            "ready_for_clinical_interpretation": "no",
                        }
                    ],
                },
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["hcc1395_wgs"], "unit")

            self.assertTrue(any("sv_evidence_summary reports 20" in blocker for blocker in summary["blockers"]))

    def test_artifact_root_override_reads_materialized_inputs(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            packet_root = output_root / "isolated-rosalind"
            artifact_root = Path(artifacts)
            utils.write_json(
                artifact_root / "results/full_wes_benchmark/full_wes_benchmark_summary.json",
                {
                    "status": "passed",
                    "bamValidationStatus": "passed",
                    "exactPassTruthMatches": 1122,
                    "exactPassRecall": 0.8585,
                    "exactPassPrecision": 0.9842,
                    "contaminationStatus": "passed",
                    "contaminationEstimate": "0.0",
                },
            )
            utils.write_json(artifact_root / "results/full_wes_benchmark/truth_overlap_benchmark_summary.json", {"status": "passed"})
            utils.write_csv(
                artifact_root / "results/full_wes_benchmark/full_wes_fastq_validation.csv",
                [{"status": "passed"}, {"status": "passed"}, {"status": "passed"}, {"status": "passed"}],
            )
            utils.write_csv(
                artifact_root / "results/full_wes_benchmark/full_wes_bam_validation.csv",
                [{"status": "passed"}, {"status": "passed"}],
            )
            utils.write_json(
                artifact_root / "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wes_summary.json",
                {"status": "expanded_non_dry_passed"},
            )

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_OUTPUT_ROOT": str(packet_root),
                    },
                ),
            ):
                summary = packet.write_packet(packet.PACKET_SPECS["hcc1395_wes"], "unit")

            self.assertEqual(summary["missingArtifacts"], [])
            self.assertEqual(
                summary["outputDir"],
                str(packet_root.resolve() / "hcc1395_wes/unit"),
            )
            evidence_rows = utils.parse_csv(utils.read_text(packet_root / "hcc1395_wes/unit/sample_validation_summary.csv"))
            self.assertIn("4/4 FASTQ rows passed", evidence_rows[0]["detail"])
            artifact_index = utils.read_json(packet_root / "hcc1395_wes/unit/input_evidence_index.json")
            self.assertTrue(str(artifact_root) in artifact_index["artifacts"][0]["resolved_path"])

    def test_diana_wgs_packet_consumes_worker_artifact_root_without_exposing_input_labels(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertEqual(summary["missingArtifacts"], [])
            self.assertEqual(summary["blockers"], [])
            self.assertTrue(summary["interpretationGaps"])
            report_manifest = utils.read_json(
                output_root
                / "results/rosalind_hrd/diana_wgs/unit/report_manifest.json"
            )
            self.assertEqual(
                report_manifest["review_summary"]["provenance"]["tool_versions"],
                {
                    "bcftools": "bcftools 1.20",
                    "bwa": "bwa 0.7.17",
                    "gatk": "gatk 4.6.1.0",
                    "samtools": "samtools 1.20",
                },
            )
            evidence_rows = utils.parse_csv(
                utils.read_text(output_root / "results/rosalind_hrd/diana_wgs/unit/sample_validation_summary.csv")
            )
            self.assertEqual(
                {row["evidence_id"] for row in evidence_rows},
                {
                    "wgs_run_boundary",
                    "wgs_alignment",
                    "matched_normal_somatic_variants",
                    "hrr_region_small_variants",
                    "coverage_cnv",
                    "sbs96_input",
                    "bam_derived_sv_evidence",
                },
            )
            adapter_rows = utils.parse_csv(
                utils.read_text(output_root / "results/rosalind_hrd/diana_wgs/unit/hrd_adapter_status.csv")
            )
            self.assertEqual({row["state"] for row in adapter_rows}, {"ready", "partial_evidence", "no_call"})
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "scarHRD")["state"], "no_call")
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "SBS3")["state"], "no_call")
            reviewer = utils.read_text(output_root / "results/rosalind_hrd/diana_wgs/unit/reviewer_packet.md")
            self.assertIn("does not support a scalar or categorical HRD conclusion", reviewer)
            self.assertNotIn("SENSITIVE-PAIR-ID", reviewer)
            self.assertNotIn("SENSITIVE-DATASET-LABEL", reviewer)

            evidence_index = utils.read_json(
                output_root / "results/rosalind_hrd/diana_wgs/unit/input_evidence_index.json"
            )
            self.assertEqual(len(evidence_index["artifacts"]), len(packet.PACKET_SPECS["diana_wgs"].artifacts))
            for artifact in evidence_index["artifacts"]:
                source = artifact_root / artifact["path"]
                self.assertEqual(artifact["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())

            report = output_root / "results/rosalind_hrd/diana_wgs/unit/report.md"
            manifest = utils.read_json(
                output_root / "results/rosalind_hrd/diana_wgs/unit/report_manifest.json"
            )
            self.assertEqual(report.read_text(encoding="utf-8"), reviewer)
            self.assertEqual(manifest["method_id"], "rosalind_diana_wgs")
            self.assertEqual(manifest["evidence_status"], "partial_evidence")
            self.assertEqual(manifest["authorized_hrd_state"], "no_call")
            self.assertFalse(manifest["classification_authorized"])
            self.assertEqual(
                manifest["review_summary"]["interpretation_gaps"],
                summary["interpretationGaps"],
            )
            self.assertEqual(manifest["report_sha256"], hashlib.sha256(report.read_bytes()).hexdigest())
            self.assertEqual(len(manifest["source_sha256"]), len(evidence_index["artifacts"]))
            self.assertEqual(
                set(manifest["support_sha256"]),
                {
                    "input_evidence_index.json", "sample_validation_summary.csv",
                    "hrd_adapter_status.csv", "research_context_sources.json",
                    "next_actions.md", "reviewer_packet.md",
                },
            )
            self.assertEqual(manifest["review_summary"]["provenance"]["artifact_count"], 12)
            self.assertTrue(manifest["review_summary"]["provenance"]["custody"]["exact_kms_match"])
            self.assertTrue(all(row["next_action"] for row in manifest["review_summary"]["adapters"]))
            self.assertIn("## Deterministic custody and process", reviewer)
            self.assertIn("samtools 1.20", reviewer)
            serialized_manifest = utils.read_text(
                output_root / "results/rosalind_hrd/diana_wgs/unit/report_manifest.json"
            )
            self.assertNotIn("SENSITIVE-PAIR-ID", serialized_manifest)
            self.assertNotIn("SENSITIVE-DATASET-LABEL", serialized_manifest)

    def test_diana_wgs_packet_carries_verified_terminal_deterministic_hashes(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            expected_report_sha256 = packet.sha256_file(
                deterministic_root / "report.md"
            )
            expected_manifest_sha256 = packet.sha256_file(
                deterministic_root / "report_manifest.json"
            )
            real_read_json_file = packet.read_json_file
            tampered = False

            def tamper_after_report_validation(path: Path, label: str):
                nonlocal tampered
                value = real_read_json_file(path, label)
                if label == "Diana WGS tool versions" and not tampered:
                    (deterministic_root / "report.md").write_text(
                        "# Late unverified deterministic report\n",
                        encoding="utf-8",
                    )
                    manifest_path = deterministic_root / "report_manifest.json"
                    manifest = utils.read_json(manifest_path)
                    manifest["review_summary"]["custody"][
                        "freeze_receipt_sha256"
                    ] = "c" * 64
                    utils.write_json(manifest_path, manifest)
                    tampered = True
                return value

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
                patch.object(
                    packet,
                    "read_json_file",
                    side_effect=tamper_after_report_validation,
                ),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            manifest = utils.read_json(
                output_root / "results/rosalind_hrd/diana_wgs/unit/report_manifest.json"
            )
            provenance = manifest["review_summary"]["provenance"]
            self.assertEqual(
                provenance["deterministic_report_sha256"],
                expected_report_sha256,
            )
            self.assertEqual(
                provenance["deterministic_manifest_sha256"],
                expected_manifest_sha256,
            )
            self.assertNotEqual(
                provenance["deterministic_report_sha256"],
                packet.sha256_file(deterministic_root / "report.md"),
            )
            self.assertNotEqual(
                provenance["deterministic_manifest_sha256"],
                packet.sha256_file(deterministic_root / "report_manifest.json"),
            )

    def test_diana_wgs_packet_carries_parsed_terminal_manifest_hash(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            expected_manifest_sha256 = packet.sha256_file(
                deterministic_root / "report_manifest.json"
            )
            read_count = 0
            real_stable_read = packet.read_stable_json_file_bytes

            def tamper_after_deterministic_manifest_read(path: Path, label: str):
                nonlocal read_count
                data = real_stable_read(path, label)
                if label == "deterministic report manifest":
                    read_count += 1
                if label == "deterministic report manifest" and read_count == 1:
                    manifest = utils.read_json(path)
                    manifest["classification_qc_status"] = "passed"
                    utils.write_json(path, manifest)
                return data

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
                patch.object(
                    packet,
                    "read_stable_json_file_bytes",
                    side_effect=tamper_after_deterministic_manifest_read,
                ),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            manifest = utils.read_json(
                output_root / "results/rosalind_hrd/diana_wgs/unit/report_manifest.json"
            )
            self.assertEqual(
                manifest["review_summary"]["provenance"]["deterministic_manifest_sha256"],
                expected_manifest_sha256,
            )
            self.assertNotEqual(
                expected_manifest_sha256,
                packet.sha256_file(deterministic_root / "report_manifest.json"),
            )

    def test_diana_wgs_packet_consumes_phase3_fast_deterministic_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(output_root / "phase3_fast")

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": PHASE3_FAST_FORBIDDEN_TOKENS_JSON,
                    },
                ),
            ):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

            self.assertEqual(summary["missingArtifacts"], [])
            self.assertEqual(summary["blockers"], [])
            self.assertTrue(summary["interpretationGaps"])

            output_dir = output_root / "results/rosalind_hrd/diana_wgs/phase3-fast"
            evidence_rows = utils.parse_csv(utils.read_text(output_dir / "sample_validation_summary.csv"))
            self.assertEqual(
                {row["evidence_id"] for row in evidence_rows},
                {
                    "phase3_fast_run_boundary",
                    "source_sha256",
                    "matched_normal_somatic_variants",
                    "wgs_bam_qc",
                    "coverage_cnv",
                    "sbs96_input",
                    "sigprofiler_sbs3_input_plan",
                    "sequenza_scarhrd_input_plan",
                    "bam_derived_sv_evidence",
                },
            )
            self.assertEqual(
                next(row for row in evidence_rows if row["evidence_id"] == "sbs96_input")["status"],
                "partial_evidence",
            )

            adapter_rows = utils.parse_csv(utils.read_text(output_dir / "hrd_adapter_status.csv"))
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "scarHRD")["state"], "no_call")
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "CHORD")["state"], "no_call")
            self.assertEqual(
                next(row for row in adapter_rows if row["adapter"] == "SBS96 input matrix")["state"],
                "partial_evidence",
            )
            self.assertEqual(
                next(row for row in adapter_rows if row["adapter"] == "SigProfiler/SBS3 input materializer")["state"],
                "blocked",
            )
            self.assertEqual(
                next(row for row in adapter_rows if row["adapter"] == "Sequenza/scarHRD input materializer")["state"],
                "blocked",
            )

            reviewer = utils.read_text(output_dir / "reviewer_packet.md")
            self.assertIn("Phase 3 fast final evidence", reviewer)
            self.assertIn("SigProfiler/SBS3 input materialization: `awaiting_private_results_freeze`", reviewer)
            self.assertIn("Sequenza/scarHRD input materialization: `blocked`", reviewer)
            self.assertIn(
                "Sequenza/scarHRD alias contract: `blocked` with `sequenza.female=true`.",
                reviewer,
            )
            self.assertIn(
                "Sequenza/scarHRD attestations: final BAM contract published `false`; "
                "validated runtime `false`.",
                reviewer,
            )
            self.assertIn("SBS96", reviewer)
            manifest = utils.read_json(output_dir / "report_manifest.json")
            self.assertEqual(manifest["method_id"], "rosalind_diana_wgs")
            self.assertEqual(manifest["evidence_status"], "partial_evidence")
            self.assertEqual(manifest["authorized_hrd_state"], "no_call")
            self.assertFalse(manifest["classification_authorized"])
            self.assertEqual(
                manifest["review_summary"]["interpretation_gaps"],
                summary["interpretationGaps"],
            )
            self.assertEqual(
                manifest["review_summary"]["provenance"]["binding_kind"],
                "phase3_fast_final",
            )
            self.assertEqual(
                {"run_id": "diana-wgs-hrd-20260716T033101Z"},
                manifest["review_summary"]["provenance"]["phase3_fast"]["run"],
            )
            self.assertEqual(
                {
                    "workflow_id": "phase3_wgs_fast",
                    "parameter_sha256": "2" * 64,
                    "source_commit": "abcd1234",
                },
                manifest["review_summary"]["provenance"]["phase3_fast"]["workflow"],
            )
            self.assertEqual(
                "awaiting_private_results_freeze",
                manifest["review_summary"]["provenance"]["phase3_fast"]["crosscheck_input_plans"][
                    "sigprofiler_sbs3"
                ],
            )
            self.assertEqual(
                "blocked",
                manifest["review_summary"]["provenance"]["phase3_fast"]["crosscheck_input_plans"][
                    "sequenza_scarhrd"
                ],
            )
            sequenza_contract = manifest["review_summary"]["provenance"]["phase3_fast"][
                "sequenza_scarhrd_alias_input_contract"
            ]
            self.assertEqual(
                {"sequenza": {"female": True}},
                sequenza_contract["method_parameters"],
            )
            self.assertEqual(
                {
                    "tumor": "subject01_tumor",
                    "normal": "subject01_normal",
                },
                sequenza_contract["planned_aliases"],
            )
            self.assertNotIn("tumor_sample", json.dumps(sequenza_contract))
            self.assertNotIn("normal_sample", json.dumps(sequenza_contract))
            self.assertEqual(
                [
                    "normal_bai",
                    "normal_bam",
                    "staged_validation",
                    "tumor_bai",
                    "tumor_bam",
                ],
                sequenza_contract["planned_alias_output_roles"],
            )
            self.assertNotIn(".bam", json.dumps(sequenza_contract))
            self.assertFalse(
                sequenza_contract["attestations"]["final_bam_contract_published"]
            )
            self.assertFalse(
                sequenza_contract["attestations"]["validated_sequenza_scarhrd_runtime"]
            )
            self.assertEqual("GRCh38", sequenza_contract["reference"]["build"])
            self.assertIn("tumor_bam", sequenza_contract["artifacts"])
            self.assertEqual(
                {"bytes", "sha256", "version_id"},
                set(sequenza_contract["artifacts"]["tumor_bam"]),
            )
            self.assertIn("small_variants.filter_mutect.filtered_vcf", manifest["source_sha256"])
            evidence_index = utils.read_json(output_dir / "input_evidence_index.json")
            self.assertEqual(
                len(evidence_index["artifacts"]),
                manifest["review_summary"]["provenance"]["artifact_count"] + 1,
            )

    def test_diana_wgs_packet_carries_verified_phase3_fast_deterministic_hashes(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(
                output_root / "phase3_fast"
            )
            expected_report_sha256 = packet.sha256_file(
                deterministic_root / "report.md"
            )
            expected_manifest_sha256 = packet.sha256_file(
                deterministic_root / "report_manifest.json"
            )
            real_compact_summary = packet.phase3_fast_compact_sequenza_summary
            tampered = False

            def tamper_after_report_validation(value):
                nonlocal tampered
                summary = real_compact_summary(value)
                if not tampered:
                    (deterministic_root / "report.md").write_text(
                        "# Late unverified Phase 3 fast report\n",
                        encoding="utf-8",
                    )
                    mutate_phase3_fast_report_manifest(
                        deterministic_root,
                        lambda manifest: manifest.__setitem__(
                            "classification_qc_status",
                            "passed",
                        ),
                    )
                    tampered = True
                return summary

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": PHASE3_FAST_FORBIDDEN_TOKENS_JSON,
                    },
                ),
                patch.object(
                    packet,
                    "phase3_fast_compact_sequenza_summary",
                    side_effect=tamper_after_report_validation,
                ),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

            manifest = utils.read_json(
                output_root
                / "results/rosalind_hrd/diana_wgs/phase3-fast/report_manifest.json"
            )
            provenance = manifest["review_summary"]["provenance"]
            self.assertEqual(
                provenance["deterministic_report_sha256"],
                expected_report_sha256,
            )
            self.assertEqual(
                provenance["deterministic_manifest_sha256"],
                expected_manifest_sha256,
            )
            self.assertNotEqual(
                provenance["deterministic_report_sha256"],
                packet.sha256_file(deterministic_root / "report.md"),
            )
            self.assertNotEqual(
                provenance["deterministic_manifest_sha256"],
                packet.sha256_file(deterministic_root / "report_manifest.json"),
            )

    def test_diana_wgs_packet_carries_parsed_phase3_fast_manifest_hash(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(
                output_root / "phase3_fast"
            )
            expected_manifest_sha256 = packet.sha256_file(
                deterministic_root / "report_manifest.json"
            )
            read_count = 0
            real_stable_read = packet.read_stable_json_file_bytes

            def tamper_after_deterministic_manifest_read(path: Path, label: str):
                nonlocal read_count
                data = real_stable_read(path, label)
                if label == "deterministic report manifest":
                    read_count += 1
                if label == "deterministic report manifest" and read_count == 1:
                    mutate_phase3_fast_report_manifest(
                        deterministic_root,
                        lambda manifest: manifest.__setitem__(
                            "classification_qc_status",
                            "passed",
                        ),
                    )
                return data

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": PHASE3_FAST_FORBIDDEN_TOKENS_JSON,
                    },
                ),
                patch.object(
                    packet,
                    "read_stable_json_file_bytes",
                    side_effect=tamper_after_deterministic_manifest_read,
                ),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

            manifest = utils.read_json(
                output_root
                / "results/rosalind_hrd/diana_wgs/phase3-fast/report_manifest.json"
            )
            self.assertEqual(
                manifest["review_summary"]["provenance"]["deterministic_manifest_sha256"],
                expected_manifest_sha256,
            )
            self.assertNotEqual(
                expected_manifest_sha256,
                packet.sha256_file(deterministic_root / "report_manifest.json"),
            )

    def test_diana_wgs_phase3_fast_packet_reuses_deterministic_binding_for_evidence(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(
                output_root / "phase3_fast"
            )
            expected_manifest_sha256 = packet.sha256_file(
                deterministic_root / "report_manifest.json"
            )
            mutated_manifest = False
            mutated_plan = False
            real_stable_read = packet.read_stable_json_file_bytes

            def tamper_after_bound_input_reads(path: Path, label: str):
                nonlocal mutated_manifest, mutated_plan
                data = real_stable_read(path, label)
                if label == "deterministic report manifest" and not mutated_manifest:
                    mutate_phase3_fast_report_manifest(
                        deterministic_root,
                        lambda manifest: manifest.__setitem__(
                            "classification_qc_status",
                            "passed",
                        ),
                    )
                    mutated_manifest = True
                if label == "Phase 3 fast cross-check input plan" and not mutated_plan:
                    mutate_phase3_fast_crosscheck_plans(
                        deterministic_root,
                        lambda plans: plans["routes"]["sequenza_scarhrd"].__setitem__(
                            "status",
                            "inputs_materialized",
                        ),
                    )
                    mutated_plan = True
                return data

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": PHASE3_FAST_FORBIDDEN_TOKENS_JSON,
                    },
                ),
                patch.object(
                    packet,
                    "read_stable_json_file_bytes",
                    side_effect=tamper_after_bound_input_reads,
                ),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

            output_dir = (
                output_root / "results/rosalind_hrd/diana_wgs/phase3-fast"
            )
            manifest = utils.read_json(output_dir / "report_manifest.json")
            sample_rows = utils.parse_csv(
                utils.read_text(output_dir / "sample_validation_summary.csv")
            )
            sequenza_row = next(
                row
                for row in sample_rows
                if row["evidence_id"] == "sequenza_scarhrd_input_plan"
            )
            self.assertEqual(
                manifest["review_summary"]["provenance"]["deterministic_manifest_sha256"],
                expected_manifest_sha256,
            )
            self.assertEqual(
                "blocked",
                manifest["review_summary"]["provenance"]["phase3_fast"][
                    "crosscheck_input_plans"
                ]["sequenza_scarhrd"],
            )
            self.assertIn(
                "Alias-only Sequenza/scarHRD materialization is blocked; execution is not_run",
                sequenza_row["detail"],
            )
            self.assertNotIn("inputs_materialized", sequenza_row["detail"])

    def test_diana_wgs_packet_rejects_deterministic_report_below_symlinked_parent(self):
        self.assertFalse(packet.is_platform_root_alias(Path("linked-phase3-fast")))

        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(
                output_root / "phase3_fast"
            )
            real_parent = output_root / "real-phase3-fast"
            real_parent.mkdir()
            moved_root = real_parent / "deterministic"
            deterministic_root.rename(moved_root)
            linked_parent = output_root / "linked-phase3-fast"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(
                            linked_parent / "deterministic"
                        ),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": PHASE3_FAST_FORBIDDEN_TOKENS_JSON,
                    },
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "deterministic report .* parent may not be a symlink",
                ),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

            self.assertFalse(
                (
                    output_root
                    / "results/rosalind_hrd/diana_wgs/phase3-fast/report_manifest.json"
                ).exists()
            )

    def test_diana_wgs_phase3_fast_packet_rejects_symlinked_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(
                output_root / "phase3_fast"
            )
            real_readiness = deterministic_root / "real-readiness.csv"
            readiness = deterministic_root / "readiness.csv"
            readiness.rename(real_readiness)
            readiness.symlink_to(real_readiness)

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": PHASE3_FAST_FORBIDDEN_TOKENS_JSON,
                    },
                ),
                self.assertRaisesRegex(
                    ValueError,
                    r"deterministic readiness\.csv must be a non-empty regular non-symlink file",
                ),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

            self.assertFalse(
                (
                    output_root
                    / "results/rosalind_hrd/diana_wgs/phase3-fast/report_manifest.json"
                ).exists()
            )

    def test_diana_wgs_phase3_fast_packet_requires_sequenza_alias_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(output_root / "phase3_fast")
            mutate_phase3_fast_crosscheck_plans(
                deterministic_root,
                lambda plans: plans["routes"]["sequenza_scarhrd"].pop(
                    "alias_input_contract"
                ),
            )

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": PHASE3_FAST_FORBIDDEN_TOKENS_JSON,
                    },
                ),
                self.assertRaisesRegex(ValueError, "lacks an alias input contract"),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

    def test_diana_wgs_phase3_fast_packet_rejects_non_exact_plan_schemas(self):
        cases = (
            (
                "crosscheck_input_plans",
                lambda plans: plans.update({"schema_version": 1.0}),
                "Phase 3 fast cross-check input plan contract is not exact",
            ),
            (
                "sequenza_alias_contract",
                lambda plans: plans["routes"]["sequenza_scarhrd"][
                    "alias_input_contract"
                ].update({"schema_version": True}),
                "Phase 3 fast Sequenza alias input contract is not exact",
            ),
        )
        for label, mutation, error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                output_root = Path(tmp)
                deterministic_root, final_root = (
                    write_phase3_fast_deterministic_report(
                        output_root / "phase3_fast"
                    )
                )
                mutate_phase3_fast_crosscheck_plans(deterministic_root, mutation)

                with (
                    patch.object(
                        packet,
                        "path_from_root",
                        lambda relative: output_root / relative,
                    ),
                    patch.dict(
                        "os.environ",
                        {
                            "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                            "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(
                                deterministic_root
                            ),
                            "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": (
                                PHASE3_FAST_FORBIDDEN_TOKENS_JSON
                            ),
                        },
                    ),
                    self.assertRaisesRegex(ValueError, error),
                ):
                    packet.write_packet(
                        packet.PACKET_SPECS["diana_wgs"],
                        "phase3-fast",
                    )

                self.assertFalse(
                    (
                        output_root
                        / "results/rosalind_hrd/diana_wgs/phase3-fast/"
                        "report_manifest.json"
                    ).exists()
                )

    def test_diana_wgs_phase3_fast_packet_rejects_duplicate_report_manifest_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(
                output_root / "phase3_fast"
            )
            write_duplicate_json_field(
                deterministic_root / "report_manifest.json",
                "schema_version",
                0,
            )

            with (
                patch.object(
                    packet,
                    "path_from_root",
                    lambda relative: output_root / relative,
                ),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(
                            deterministic_root
                        ),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": (
                            PHASE3_FAST_FORBIDDEN_TOKENS_JSON
                        ),
                    },
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "duplicate JSON object name in deterministic report manifest: schema_version",
                ),
            ):
                packet.write_packet(
                    packet.PACKET_SPECS["diana_wgs"],
                    "phase3-fast",
                )

            self.assertFalse(
                (
                    output_root
                    / "results/rosalind_hrd/diana_wgs/phase3-fast/"
                    "report_manifest.json"
                ).exists()
            )

    def test_diana_wgs_phase3_fast_packet_rejects_non_exact_run_provenance(self):
        cases = (
            (
                "extra_field",
                lambda manifest: manifest["review_summary"]["run"].__setitem__(
                    "unexpected",
                    "metadata",
                ),
                "Phase 3 fast run provenance is not exact",
            ),
            (
                "boolean_run_id",
                lambda manifest: manifest["review_summary"]["run"].__setitem__(
                    "run_id",
                    True,
                ),
                "Phase 3 fast run_id must be a non-empty unpadded single-line string",
            ),
            (
                "padded_subject_alias",
                lambda manifest: manifest["review_summary"]["run"].__setitem__(
                    "subject_alias",
                    " subject01 ",
                ),
                "Phase 3 fast subject_alias must be a non-empty unpadded single-line string",
            ),
            (
                "multiline_pair_id",
                lambda manifest: manifest["review_summary"]["run"].__setitem__(
                    "pair_id",
                    "tumor\nnormal",
                ),
                "Phase 3 fast pair_id must be a non-empty unpadded single-line string",
            ),
        )
        for label, mutation, error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                output_root = Path(tmp)
                deterministic_root, final_root = (
                    write_phase3_fast_deterministic_report(
                        output_root / "phase3_fast"
                    )
                )
                mutate_phase3_fast_report_manifest(deterministic_root, mutation)

                with (
                    patch.object(
                        packet,
                        "path_from_root",
                        lambda relative: output_root / relative,
                    ),
                    patch.dict(
                        "os.environ",
                        {
                            "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                            "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(
                                deterministic_root
                            ),
                            "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": (
                                PHASE3_FAST_FORBIDDEN_TOKENS_JSON
                            ),
                        },
                    ),
                    self.assertRaisesRegex(ValueError, error),
                ):
                    packet.write_packet(
                        packet.PACKET_SPECS["diana_wgs"],
                        "phase3-fast",
                    )

                self.assertFalse(
                    (
                        output_root
                        / "results/rosalind_hrd/diana_wgs/phase3-fast/"
                        "report_manifest.json"
                    ).exists()
                )

    def test_diana_wgs_phase3_fast_packet_rejects_non_exact_workflow_provenance(self):
        cases = (
            (
                "extra_field",
                lambda manifest: manifest["review_summary"]["workflow"].__setitem__(
                    "unexpected",
                    "metadata",
                ),
                "Phase 3 fast workflow provenance is not exact",
            ),
            (
                "boolean_name",
                lambda manifest: manifest["review_summary"]["workflow"].__setitem__(
                    "name",
                    True,
                ),
                "Phase 3 fast workflow name must be a non-empty unpadded single-line string",
            ),
            (
                "uppercase_parameter_sha256",
                lambda manifest: manifest["review_summary"]["workflow"].__setitem__(
                    "parameter_sha256",
                    "A" * 64,
                ),
                "Phase 3 fast workflow parameter_sha256 must be a SHA-256 hex digest",
            ),
            (
                "multiline_source_commit",
                lambda manifest: manifest["review_summary"]["workflow"].__setitem__(
                    "source_commit",
                    "abcd\n1234",
                ),
                "Phase 3 fast workflow source_commit must be a non-empty unpadded single-line string",
            ),
        )
        for label, mutation, error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                output_root = Path(tmp)
                deterministic_root, final_root = (
                    write_phase3_fast_deterministic_report(
                        output_root / "phase3_fast"
                    )
                )
                mutate_phase3_fast_report_manifest(deterministic_root, mutation)

                with (
                    patch.object(
                        packet,
                        "path_from_root",
                        lambda relative: output_root / relative,
                    ),
                    patch.dict(
                        "os.environ",
                        {
                            "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                            "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(
                                deterministic_root
                            ),
                            "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": (
                                PHASE3_FAST_FORBIDDEN_TOKENS_JSON
                            ),
                        },
                    ),
                    self.assertRaisesRegex(ValueError, error),
                ):
                    packet.write_packet(
                        packet.PACKET_SPECS["diana_wgs"],
                        "phase3-fast",
                    )

            self.assertFalse(
                (
                    output_root
                    / "results/rosalind_hrd/diana_wgs/phase3-fast/"
                    "report_manifest.json"
                ).exists()
            )

    def test_diana_wgs_phase3_fast_packet_rejects_non_exact_sequenza_run_alias(
        self,
    ):
        cases = (
            (
                "boolean",
                True,
                "Phase 3 fast Sequenza run_alias must be a non-empty unpadded single-line string",
            ),
            (
                "padded",
                " subject01 ",
                "Phase 3 fast Sequenza run_alias must be a non-empty unpadded single-line string",
            ),
            (
                "multiline",
                "subject\n01",
                "Phase 3 fast Sequenza run_alias must be a non-empty unpadded single-line string",
            ),
        )
        for label, run_alias, error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                output_root = Path(tmp)
                deterministic_root, final_root = (
                    write_phase3_fast_deterministic_report(
                        output_root / "phase3_fast"
                    )
                )
                mutate_phase3_fast_crosscheck_plans(
                    deterministic_root,
                    lambda plans: plans["routes"]["sequenza_scarhrd"][
                        "alias_input_contract"
                    ].__setitem__("run_alias", run_alias),
                )

                with (
                    patch.object(
                        packet,
                        "path_from_root",
                        lambda relative: output_root / relative,
                    ),
                    patch.dict(
                        "os.environ",
                        {
                            "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                            "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(
                                deterministic_root
                            ),
                            "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": (
                                PHASE3_FAST_FORBIDDEN_TOKENS_JSON
                            ),
                        },
                    ),
                    self.assertRaisesRegex(ValueError, error),
                ):
                    packet.write_packet(
                        packet.PACKET_SPECS["diana_wgs"],
                        "phase3-fast",
                    )

                self.assertFalse(
                    (
                        output_root
                        / "results/rosalind_hrd/diana_wgs/phase3-fast/"
                        "report_manifest.json"
                    ).exists()
                )

    def test_diana_wgs_phase3_fast_process_lines_reject_loose_summaries(self):
        cases = (
            (
                "missing_workflow_name",
                lambda binding: binding["phase3_fast"]["workflow"].pop("name"),
                "Phase 3 fast workflow provenance is not exact",
            ),
            (
                "missing_route_state",
                lambda binding: binding["phase3_fast"][
                    "crosscheck_input_plans"
                ].pop("sigprofiler_sbs3"),
                "Phase 3 fast cross-check route summary is not exact",
            ),
            (
                "extra_route_state",
                lambda binding: binding["phase3_fast"][
                    "crosscheck_input_plans"
                ].__setitem__("facets", "blocked"),
                "Phase 3 fast cross-check route summary is not exact",
            ),
            (
                "non_exact_sequenza_female",
                lambda binding: binding["phase3_fast"][
                    "sequenza_scarhrd_alias_input_contract"
                ]["method_parameters"]["sequenza"].__setitem__("female", "true"),
                "Phase 3 fast compact Sequenza alias contract is not exact",
            ),
            (
                "missing_sequenza_attestation",
                lambda binding: binding["phase3_fast"][
                    "sequenza_scarhrd_alias_input_contract"
                ]["attestations"].pop("validated_sequenza_scarhrd_runtime"),
                "Phase 3 fast compact Sequenza alias contract is not exact",
            ),
        )

        for label, mutation, error in cases:
            with self.subTest(label=label):
                binding = phase3_fast_process_binding()
                mutation(binding)

                with self.assertRaisesRegex(ValueError, error):
                    packet.diana_wgs_deterministic_process_lines(binding)

    def test_diana_wgs_phase3_fast_ai_provenance_summarizes_exact_sequenza_alias_contract(
        self,
    ):
        provenance = packet.diana_wgs_report_provenance(
            phase3_fast_ai_provenance_binding()
        )

        sequenza_contract = provenance["phase3_fast"][
            "sequenza_scarhrd_alias_input_contract"
        ]
        self.assertEqual(
            [
                "normal_bai",
                "normal_bam",
                "staged_validation",
                "tumor_bai",
                "tumor_bam",
            ],
            sequenza_contract["planned_alias_output_roles"],
        )
        self.assertNotIn("planned_alias_outputs", sequenza_contract)

    def test_diana_wgs_phase3_fast_ai_provenance_rejects_loose_sequenza_alias_contract(
        self,
    ):
        cases = (
            (
                "missing_planned_alias_outputs",
                lambda compact: compact.pop("planned_alias_outputs"),
                "Phase 3 fast Sequenza AI provenance is not exact",
            ),
            (
                "raw_planned_alias_output",
                lambda compact: compact["planned_alias_outputs"].__setitem__(
                    "tumor_bam",
                    "raw.bam",
                ),
                "Phase 3 fast Sequenza AI provenance is not exact",
            ),
            (
                "uppercase_reference_sha256",
                lambda compact: compact["reference"]["fasta"].__setitem__(
                    "sha256",
                    "A" * 64,
                ),
                "Sequenza AI fasta sha256 must be a SHA-256 hex digest",
            ),
            (
                "blank_artifact_version_id",
                lambda compact: compact["artifacts"]["tumor_bam"].__setitem__(
                    "version_id",
                    " none ",
                ),
                "Sequenza AI tumor_bam version_id must be a non-empty VersionId string",
            ),
        )

        for label, mutation, error in cases:
            with self.subTest(label=label):
                binding = phase3_fast_ai_provenance_binding()
                mutation(
                    binding["phase3_fast"]["sequenza_scarhrd_alias_input_contract"]
                )

                with self.assertRaisesRegex(ValueError, error):
                    packet.diana_wgs_report_provenance(binding)

    def test_diana_wgs_phase3_fast_packet_rejects_json_float_counts_and_bytes(self):
        cases = (
            (
                "artifact_count",
                lambda deterministic_root: mutate_phase3_fast_report_manifest(
                    deterministic_root,
                    lambda manifest: manifest["review_summary"].__setitem__(
                        "artifact_count",
                        1.0,
                    ),
                ),
                "Phase 3 fast artifact_count must be a non-negative integer",
            ),
            (
                "artifact_group",
                lambda deterministic_root: mutate_phase3_fast_report_manifest(
                    deterministic_root,
                    lambda manifest: manifest["review_summary"][
                        "artifact_groups"
                    ].__setitem__("small_variants", 1.0),
                ),
                "Phase 3 fast artifact group small_variants must be a non-negative integer",
            ),
            (
                "sequenza_alias_bytes",
                lambda deterministic_root: mutate_phase3_fast_crosscheck_plans(
                    deterministic_root,
                    lambda plans: plans["routes"]["sequenza_scarhrd"][
                        "alias_input_contract"
                    ]["artifacts"]["tumor_bam"].__setitem__("bytes", 1.0),
                ),
                "Sequenza tumor_bam bytes must be a non-negative integer",
            ),
        )
        for label, mutation, error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                output_root = Path(tmp)
                deterministic_root, final_root = (
                    write_phase3_fast_deterministic_report(
                        output_root / "phase3_fast"
                    )
                )
                mutation(deterministic_root)

                with (
                    patch.object(
                        packet,
                        "path_from_root",
                        lambda relative: output_root / relative,
                    ),
                    patch.dict(
                        "os.environ",
                        {
                            "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                            "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(
                                deterministic_root
                            ),
                            "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": (
                                PHASE3_FAST_FORBIDDEN_TOKENS_JSON
                            ),
                        },
                    ),
                    self.assertRaisesRegex(ValueError, error),
                ):
                    packet.write_packet(
                        packet.PACKET_SPECS["diana_wgs"],
                        "phase3-fast",
                    )

                self.assertFalse(
                    (
                        output_root
                        / "results/rosalind_hrd/diana_wgs/phase3-fast/"
                        "report_manifest.json"
                    ).exists()
                )

    def test_diana_wgs_phase3_fast_packet_rejects_non_exact_alias_version_ids(self):
        cases = (
            ("empty", ""),
            ("null", "null"),
            ("none", "none"),
            ("whitespace", "space separated"),
            ("boolean", True),
        )
        for label, version_id in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                output_root = Path(tmp)
                deterministic_root, final_root = write_phase3_fast_deterministic_report(
                    output_root / "phase3_fast"
                )
                mutate_phase3_fast_crosscheck_plans(
                    deterministic_root,
                    lambda plans: plans["routes"]["sequenza_scarhrd"][
                        "alias_input_contract"
                    ]["artifacts"]["tumor_bam"].__setitem__(
                        "version_id",
                        version_id,
                    ),
                )

                with (
                    patch.object(
                        packet,
                        "path_from_root",
                        lambda relative: output_root / relative,
                    ),
                    patch.dict(
                        "os.environ",
                        {
                            "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                            "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(
                                deterministic_root
                            ),
                            "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": (
                                PHASE3_FAST_FORBIDDEN_TOKENS_JSON
                            ),
                        },
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "Sequenza tumor_bam version_id must be a non-empty VersionId string",
                    ),
                ):
                    packet.write_packet(
                        packet.PACKET_SPECS["diana_wgs"],
                        "phase3-fast",
                    )

                self.assertFalse(
                    (
                        output_root
                        / "results/rosalind_hrd/diana_wgs/phase3-fast/"
                        "report_manifest.json"
                    ).exists()
                )

    def test_diana_wgs_phase3_fast_packet_requires_forbidden_token_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(output_root / "phase3_fast")

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "requires at least one forbidden token"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

            output_dir = output_root / "results/rosalind_hrd/diana_wgs/phase3-fast"
            self.assertFalse(output_dir.exists())

    def test_diana_wgs_packet_rejects_empty_forbidden_token_inventory(self):
        with self.assertRaisesRegex(ValueError, "non-empty JSON string array"):
            with patch.dict("os.environ", {"ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": "[]"}):
                packet.diana_wgs_forbidden_tokens()

    def test_diana_wgs_phase3_fast_packet_rejects_final_artifact_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(output_root / "phase3_fast")
            (final_root / "artifacts/cnv_evidence/coverage_bins/coverage_cnv_bins.csv").write_text(
                "changed\n",
                encoding="utf-8",
            )

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": PHASE3_FAST_FORBIDDEN_TOKENS_JSON,
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "final artifact hash differs"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

    def test_diana_wgs_phase3_fast_packet_rejects_final_artifact_below_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(output_root / "phase3_fast")
            linked = final_root / "artifacts/cnv_evidence"
            real = output_root / "real-cnv-evidence"
            linked.replace(real)
            linked.symlink_to(real, target_is_directory=True)

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": PHASE3_FAST_FORBIDDEN_TOKENS_JSON,
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "final artifact .* parent may not be a symlink"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

            output_dir = output_root / "results/rosalind_hrd/diana_wgs/phase3-fast"
            self.assertFalse((output_dir / "report_manifest.json").exists())

    def test_diana_wgs_packet_clamps_unsupported_adapter_promotions(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(
                artifact_root,
                readiness_overrides={"coverage_cnv": "ready", "scarHRD": "ready", "overall_hrd": "ready"},
            )
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertTrue(any("coverage_cnv attempted promotion to ready" in blocker for blocker in summary["blockers"]))
            self.assertTrue(any("scarHRD attempted promotion to ready" in blocker for blocker in summary["blockers"]))
            self.assertTrue(any("overall_hrd attempted promotion to ready" in blocker for blocker in summary["blockers"]))
            adapter_rows = utils.parse_csv(
                utils.read_text(output_root / "results/rosalind_hrd/diana_wgs/unit/hrd_adapter_status.csv")
            )
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "Coverage CNV proxy")["state"], "partial_evidence")
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "scarHRD")["state"], "no_call")
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "Overall HRD classification")["state"], "no_call")

    def test_diana_wgs_packet_does_not_turn_missing_sidecars_into_zero_count_findings(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)
            for relative in (
                "alignment/bam_validation_summary.json",
                "variants/mutect2_summary.json",
                "cnv/coverage_cnv_summary.json",
                "signatures/signature_assignment_summary.json",
                "sv/sv_evidence_summary.json",
            ):
                (artifact_root / relative).unlink()

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "Diana WGS"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")
            self.assertFalse(
                (output_root / "results/rosalind_hrd/diana_wgs/unit/report_manifest.json").exists()
            )

    def test_diana_wgs_packet_flags_disagreement_between_readiness_csv_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            worker_summary = utils.read_json(artifact_root / "diana_hrd_summary.json")
            next(row for row in worker_summary["hrd_readiness"] if row["evidence_surface"] == "wgs_alignment")["status"] = "no_call"
            utils.write_json(artifact_root / "diana_hrd_summary.json", worker_summary)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertTrue(any("readiness CSV disagrees" in blocker for blocker in summary["blockers"]))
            adapter_rows = utils.parse_csv(
                utils.read_text(output_root / "results/rosalind_hrd/diana_wgs/unit/hrd_adapter_status.csv")
            )
            alignment = next(row for row in adapter_rows if row["adapter"] == "WGS alignment")
            self.assertEqual(alignment["state"], "no_call")
            self.assertIn("no state promotion", alignment["blocker"])

    def test_diana_wgs_packet_rejects_malformed_embedded_readiness(self):
        for label, readiness in (
            ("object", {}),
            ("non_object_row", [{"evidence_surface": "wgs_alignment"}, True]),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
                output_root = Path(tmp)
                artifact_root = Path(artifacts)
                write_diana_wgs_worker_artifacts(artifact_root)
                worker_summary_path = artifact_root / "diana_hrd_summary.json"
                worker_summary = utils.read_json(worker_summary_path)
                worker_summary["hrd_readiness"] = readiness
                utils.write_json(worker_summary_path, worker_summary)
                deterministic_root = write_deterministic_report(
                    output_root / "deterministic",
                    artifact_root,
                )
                output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"

                with (
                    patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                    patch.dict(
                        "os.environ",
                        {
                            "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                            "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        },
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "Diana WGS embedded readiness must be a list of JSON objects",
                    ),
                ):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

                self.assertFalse((output_dir / "report_manifest.json").exists())

    def test_diana_wgs_packet_rejects_loose_embedded_readiness_fields(self):
        for field, value in (
            ("evidence_surface", True),
            ("status", None),
            ("detail", ["Coverage bins are partial."]),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
                output_root = Path(tmp)
                artifact_root = Path(artifacts)
                write_diana_wgs_worker_artifacts(artifact_root)
                worker_summary_path = artifact_root / "diana_hrd_summary.json"
                worker_summary = utils.read_json(worker_summary_path)
                worker_summary["hrd_readiness"][0][field] = value
                utils.write_json(worker_summary_path, worker_summary)
                deterministic_root = write_deterministic_report(
                    output_root / "deterministic",
                    artifact_root,
                )
                output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"

                with (
                    patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                    patch.dict(
                        "os.environ",
                        {
                            "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                            "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        },
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "Diana WGS embedded readiness fields must be strings",
                    ),
                ):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

                self.assertFalse((output_dir / "report_manifest.json").exists())

    def test_diana_wgs_packet_rejects_deterministic_or_worker_tampering(self):
        for tool, value in (
            ("bcftools", ""),
            ("bcftools", "bcftools\t1.20"),
            ("bwa", True),
            ("gatk", "gatk\n4.6.1.0"),
            ("gatk", "gatk|4.6.1.0"),
            ("samtools", " samtools 1.20"),
        ):
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
                output_root = Path(tmp)
                artifact_root = Path(artifacts)
                write_diana_wgs_worker_artifacts(artifact_root)
                tools_path = artifact_root / "tool_versions.json"
                tools = utils.read_json(tools_path)
                tools[tool] = value
                utils.write_json(tools_path, tools)
                deterministic_root = write_deterministic_report(
                    output_root / "deterministic",
                    artifact_root,
                )
                output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"

                with (
                    patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                    patch.dict(
                        "os.environ",
                        {
                            "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                            "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        },
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        f"Diana WGS {tool} tool version must be a non-empty unpadded single-line string",
                    ),
                ):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

                self.assertFalse((output_dir / "report_manifest.json").exists())

        for field, value in (
            ("freeze_receipt_version_id", True),
            ("stage_provenance_receipt_version_id", " stage-version-unit"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
                output_root = Path(tmp)
                artifact_root = Path(artifacts)
                write_diana_wgs_worker_artifacts(artifact_root)
                deterministic_root = write_deterministic_report(
                    output_root / "deterministic",
                    artifact_root,
                )
                manifest_path = deterministic_root / "report_manifest.json"
                manifest = utils.read_json(manifest_path)
                manifest["review_summary"]["custody"][field] = value
                utils.write_json(manifest_path, manifest)
                output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"

                with (
                    patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                    patch.dict(
                        "os.environ",
                        {
                            "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                            "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        },
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        f"deterministic custody {field} must be a non-empty VersionId string",
                    ),
                ):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

                self.assertFalse((output_dir / "report_manifest.json").exists())

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)
            manifest_path = deterministic_root / "report_manifest.json"
            manifest = utils.read_json(manifest_path)
            manifest["classification_qc_status"] = "passed"
            utils.write_json(manifest_path, manifest)
            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "deterministic report manifest classification_qc_status is not exact",
                ):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")
            self.assertFalse((output_dir / "report_manifest.json").exists())

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)
            (deterministic_root / "evidence_checks.json").write_text("{}\n", encoding="utf-8")
            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "support hash differs"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")
            self.assertEqual(list(output_dir.glob("*")), [])

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            alignment_path = artifact_root / "alignment/bam_validation_summary.json"
            alignment = utils.read_json(alignment_path)
            alignment["rows"][1]["role"] = "tumor"
            utils.write_json(alignment_path, alignment)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "one passed tumor and one passed normal"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

    def test_diana_wgs_packet_rejects_stale_artifact_index(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            original_artifact_index = packet.artifact_index

            def stale_artifact_index(*args, **kwargs):
                rows = original_artifact_index(*args, **kwargs)
                return [
                    {
                        **row,
                        "sha256": "0" * 64
                        if row["path"] == "diana_hrd_summary.json"
                        else row["sha256"],
                    }
                    for row in rows
                ]

            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.object(packet, "artifact_index", side_effect=stale_artifact_index),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "artifact index differs from deterministic input summary",
                ):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertEqual(list(output_dir.glob("*")), [])

    def test_diana_wgs_packet_rejects_existing_packet_files_create_only(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

                output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
                original_bytes = {
                    path.name: path.read_bytes() for path in output_dir.iterdir()
                }
                (deterministic_root / "evidence_checks.json").write_text(
                    "{}\n", encoding="utf-8"
                )

                with self.assertRaisesRegex(ValueError, "already contains packet files"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertEqual(
                {path.name: path.read_bytes() for path in output_dir.iterdir()},
                original_bytes,
            )

    def test_diana_wgs_packet_file_copy_rejects_symlinked_staged_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_source = root / "source.txt"
            symlink_source = root / "source-link.txt"
            destination = root / "report.md"
            real_source.write_text("packet\n", encoding="utf-8")
            symlink_source.symlink_to(real_source)

            with self.assertRaisesRegex(ValueError, "staged Diana WGS packet"):
                packet.copy_diana_wgs_packet_file(symlink_source, destination)

            self.assertFalse(destination.exists())

    def test_diana_wgs_packet_file_copy_rejects_symlinked_destination_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            real_output = root / "real-output"
            linked_output = root / "linked-output"
            source.write_text("packet\n", encoding="utf-8")
            real_output.mkdir()
            linked_output.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "Diana WGS packet output parent may not be a symlink",
            ):
                packet.copy_diana_wgs_packet_file(source, linked_output / "report.md")

            self.assertFalse((real_output / "report.md").exists())

    def test_diana_wgs_packet_file_copy_rehashes_after_parent_fsync(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_text("packet\n", encoding="utf-8")
            real_fsync_directory = packet.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                destination.write_text("tampered\n", encoding="utf-8")

            with (
                patch.object(
                    packet,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged Diana WGS packet changed during copy",
                ),
            ):
                packet.copy_diana_wgs_packet_file(source, destination)

            self.assertFalse(destination.exists())

    def test_diana_wgs_packet_file_copy_rejects_source_symlink_swap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            relocated = root / "relocated.txt"
            destination = root / "report.md"
            source.write_text("packet\n", encoding="utf-8")
            real_fsync_directory = packet.fsync_directory

            def swap_source_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                relocated.write_text("packet\n", encoding="utf-8")
                source.unlink()
                source.symlink_to(relocated)

            with (
                patch.object(
                    packet,
                    "fsync_directory",
                    side_effect=swap_source_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "source.txt SHA-256 input must be a regular "
                    "non-symlink file",
                ),
            ):
                packet.copy_diana_wgs_packet_file(source, destination)

            self.assertTrue(relocated.exists())
            self.assertTrue(source.is_symlink())
            self.assertFalse(destination.exists())

    def test_diana_wgs_packet_cleans_current_attempt_after_install_failure(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            copied: list[str] = []
            original_copy = packet.copy_diana_wgs_packet_file

            def fail_after_first_copy(source: Path, destination: Path) -> None:
                if copied:
                    raise ValueError("synthetic install failure")
                original_copy(source, destination)
                copied.append(destination.name)

            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
                patch.object(
                    packet,
                    "copy_diana_wgs_packet_file",
                    side_effect=fail_after_first_copy,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "synthetic install failure"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertEqual(copied, ["input_evidence_index.json"])
            self.assertEqual(list(output_dir.glob("*")), [])

    def test_diana_wgs_packet_preserves_unexpected_child_after_install_failure(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            original_copy = packet.copy_diana_wgs_packet_file

            def fail_with_unexpected_child(source: Path, destination: Path) -> None:
                original_copy(source, destination)
                if destination.name == "sample_validation_summary.csv":
                    (destination.parent / "unexpected.tmp").write_text(
                        "stray partial packet file\n",
                        encoding="utf-8",
                    )
                    raise ValueError("synthetic unexpected packet child")

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
                patch.object(
                    packet,
                    "copy_diana_wgs_packet_file",
                    side_effect=fail_with_unexpected_child,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "synthetic unexpected packet child"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertTrue(output_dir.is_dir())
            for name in packet.PACKET_REPORT_FILES:
                self.assertFalse((output_dir / name).exists())
            self.assertEqual(
                (output_dir / "unexpected.tmp").read_text(encoding="utf-8"),
                "stray partial packet file\n",
            )

    def test_diana_wgs_packet_cleans_current_attempt_after_final_directory_fsync_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "output"
            output.mkdir()
            staged_paths = write_staged_rosalind_packet(staging)

            with (
                patch.object(
                    packet,
                    "fsync_directory",
                    side_effect=lambda path: (
                        (_ for _ in ()).throw(
                            OSError("synthetic final directory fsync failure")
                        )
                        if path == output
                        else None
                    ),
                ),
                self.assertRaisesRegex(
                    OSError,
                    "synthetic final directory fsync failure",
                ),
            ):
                packet.install_diana_wgs_packet(staged_paths, output)

            self.assertEqual(list(output.iterdir()), [])

    def test_diana_wgs_packet_rejects_stale_staged_report_manifest(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            real_fsync_directory = packet.fsync_directory
            tampered = False

            def tamper_after_manifest_fsync(path: Path) -> None:
                nonlocal tampered
                real_fsync_directory(path)
                if tampered:
                    return
                for manifest in (
                    output_root / "results/rosalind_hrd/diana_wgs"
                ).glob(".unit.*/report_manifest.json"):
                    (manifest.parent / "reviewer_packet.md").write_text(
                        "tampered packet\n",
                        encoding="utf-8",
                    )
                    tampered = True

            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
                patch.object(
                    packet,
                    "fsync_directory",
                    side_effect=tamper_after_manifest_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "Rosalind report manifest is stale for reviewer_packet.md",
                ),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertTrue(tampered)
            self.assertEqual(list(output_dir.iterdir()), [])

    def test_diana_wgs_packet_cleans_current_attempt_after_final_manifest_stale(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "output"
            output.mkdir()
            staged_paths = write_staged_rosalind_packet(staging)
            real_fsync_directory = packet.fsync_directory

            def tamper_after_final_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                if path == output:
                    (output / "reviewer_packet.md").write_text(
                        "tampered final packet\n",
                        encoding="utf-8",
                    )

            with (
                patch.object(
                    packet,
                    "fsync_directory",
                    side_effect=tamper_after_final_directory_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "Rosalind report manifest is stale for reviewer_packet.md",
                ),
            ):
                packet.install_diana_wgs_packet(staged_paths, output)

            self.assertEqual(list(output.iterdir()), [])

    def test_diana_wgs_packet_rescans_installed_packet(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            resolved_output_dir = output_dir.resolve()
            real_fsync_directory = packet.fsync_directory
            seen_complete_install = False
            tampered = False

            def tamper_after_final_install_fsync(path: Path) -> None:
                nonlocal seen_complete_install, tampered
                real_fsync_directory(path)
                if (
                    path.resolve() == resolved_output_dir
                    and all((output_dir / name).is_file() for name in packet.PACKET_REPORT_FILES)
                ):
                    if seen_complete_install and not tampered:
                        rewrite_packet_report_with_text(
                            output_dir,
                            "UNIT-FORBIDDEN-FINAL-INSTALL\n",
                        )
                        tampered = True
                    seen_complete_install = True

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": json.dumps(
                            ["UNIT-FORBIDDEN-FINAL-INSTALL"]
                        ),
                    },
                ),
                patch.object(
                    packet,
                    "fsync_directory",
                    side_effect=tamper_after_final_install_fsync,
                ),
                self.assertRaisesRegex(ValueError, "identifier scan failed"),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertTrue(tampered)
            self.assertEqual(list(output_dir.iterdir()), [])

    def test_diana_wgs_packet_summary_uses_installed_report_manifest_sha256(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            real_install = packet.install_diana_wgs_packet
            tampered = False

            def tamper_staging_before_install(
                staged_paths: list[Path],
                output: Path,
                forbidden_tokens: list[str],
            ) -> str:
                nonlocal tampered
                rewrite_packet_report_with_text(
                    staged_paths[0].parent,
                    "Post-scan safe report rewrite.\n",
                )
                tampered = True
                return real_install(staged_paths, output, forbidden_tokens)

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
                patch.object(
                    packet,
                    "install_diana_wgs_packet",
                    side_effect=tamper_staging_before_install,
                ),
            ):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertTrue(tampered)
            report_manifest = (
                output_root / "results/rosalind_hrd/diana_wgs/unit/report_manifest.json"
            )
            self.assertEqual(
                summary["reportManifestSha256"],
                packet.sha256_file(report_manifest),
            )

    def test_diana_wgs_packet_rejects_stale_extra_output(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            output_dir.mkdir(parents=True)
            utils.write_text(output_dir / "unexpected.txt", "stale")

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "unexpected existing files"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertEqual(
                sorted(path.name for path in output_dir.iterdir()),
                ["unexpected.txt"],
            )

    def test_diana_wgs_packet_rejects_output_below_symlinked_parent(self):
        self.assertFalse(packet.is_platform_root_alias(Path("linked-parent")))

        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as tmp:
                output_root = Path(tmp)
                real_parent = output_root / "real-rosalind"
                if nested == "existing":
                    (real_parent / nested).mkdir(parents=True)
                else:
                    real_parent.mkdir()
                linked_parent = output_root / "results/rosalind_hrd"
                linked_parent.parent.mkdir()
                linked_parent.symlink_to(real_parent, target_is_directory=True)

                with self.assertRaisesRegex(
                    ValueError,
                    "Diana WGS packet output parent may not be a symlink",
                ):
                    packet.prepare_diana_wgs_output_dir(
                        linked_parent / nested / "diana_wgs" / "unit",
                        packet.PACKET_REPORT_FILES,
                    )

                self.assertFalse((real_parent / nested / "diana_wgs").exists())

    def test_diana_wgs_packet_identifier_scan_removes_generated_outputs(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            summary_path = artifact_root / "diana_hrd_summary.json"
            summary = utils.read_json(summary_path)
            summary["input"]["reference"] = summary["input"]["pair"]
            utils.write_json(summary_path, summary)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)
            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "identifier scan failed"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")
            self.assertFalse((output_dir / "report.md").exists())
            self.assertFalse((output_dir / "report_manifest.json").exists())
            self.assertEqual(list(output_dir.glob("*")), [])

    def test_hg008_packet_surfaces_sv_truth_asset_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/hg008_snv_panel.json",
                {"status": "expanded_non_dry_passed", "publicFindingResult": "40/40 SNVs passed.", "blockers": []},
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/hg008_cnv_sweep.json",
                {
                    "status": "expanded_non_dry_passed",
                    "publicFindingResult": "4/4 CNVs passed.",
                    "blockers": ["No Diana-generated CNV callset exists for HG008."],
                    "evidence": {"cnvProbes": [{"passed": True}, {"passed": True}, {"passed": True}, {"passed": True}]},
                },
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/hg008_sv_truth_asset.json",
                {
                    "status": "expanded_non_dry_gap_identified",
                    "publicFindingResult": "HG008 SV truth asset is present.",
                    "blockers": ["No Diana-generated SV callset exists for HG008."],
                },
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json",
                {
                    "status": "bounded_non_dry_partial",
                    "publicFindingResult": "SV overlap remains unrun.",
                    "blockers": ["No Diana-generated SV/CNV callset exists for HG008 in this bounded run."],
                    "evidence": {
                        "cnvDepthProbe": {
                            "passedCnvDepthSignal": True,
                            "normalizedLossTumorNormalRatio": 0.438786,
                            "remainingSvGap": "SV reciprocal-overlap remains unrun.",
                        }
                    },
                },
            )
            utils.write_json(root / "results/clinicalization/known_answer_runs/expanded_cohort/hg008_rna_stats.json", {"status": "passed"})

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["hg008"], "unit")

            self.assertEqual(
                summary["blockers"],
                [
                    "No Diana-generated CNV segment callset exists for HG008; current HG008 CNV evidence is bounded depth-direction validation, not segment-level reciprocal overlap.",
                    "No Diana-generated SV callset exists for HG008; SV reciprocal-overlap against v0.5 truth remains unrun.",
                ],
            )
            evidence_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/hg008/unit/sample_validation_summary.csv"))
            self.assertIn("sv_truth_asset", {row["evidence_id"] for row in evidence_rows})
            cnv_row = next(row for row in evidence_rows if row["evidence_id"] == "cnv_depth_sweep")
            self.assertIn("Bounded reciprocal depth signal present: yes", cnv_row["detail"])
            reviewer = utils.read_text(root / "results/rosalind_hrd/hg008/unit/reviewer_packet.md")
            self.assertIn("HG008 SV truth asset is present", reviewer)
            self.assertIn("normalized loss tumor-normal ratio: 0.438786", reviewer)

    def test_colo829_packet_surfaces_purity_series_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in (
                "colo829_platform_illumina_hiseqx",
                "colo829_platform_pacbio_sequel",
                "colo829_platform_ont_minion",
                "colo829_platform_illumina_novaseq_phased",
            ):
                utils.write_json(
                    root / f"results/clinicalization/known_answer_runs/expanded_cohort/{name}.json",
                    {"status": "expanded_non_dry_passed", "publicFindingResult": f"{name} recovered BRAF V600E."},
                )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/colo829_sv_cna_truth_asset.json",
                {
                    "status": "expanded_non_dry_gap_identified",
                    "publicFindingResult": "SV/CNA truth assets are present.",
                    "blockers": ["No Diana SV/CNA callset exists."],
                },
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/colo829/sv_cna_reciprocal_overlap_summary.json",
                {"status": "bounded_non_dry_gap_identified", "publicFindingResult": "SV/CNA overlap was not generated.", "blockers": []},
            )
            purity_blocker = "Selected purity BAMs require full transfer or local indexing before monotonic recall can be tested."
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_illumina.json",
                {
                    "status": "expanded_non_dry_blocked_remote_index_missing",
                    "publicFindingResult": "COLO829 purity illumina metadata exposes selected levels.",
                    "blockers": [purity_blocker],
                },
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_long_read.json",
                {
                    "status": "expanded_non_dry_blocked_remote_index_missing",
                    "publicFindingResult": "COLO829 purity long_read metadata exposes selected levels.",
                    "blockers": [purity_blocker],
                },
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/colo829_purity/purity_recall_table_summary.json",
                {
                    "status": "bounded_non_dry_blocked_remote_index_missing",
                    "publicFindingResult": "COLO829 dilution BAMs cannot be remotely region-sliced.",
                    "blockers": [purity_blocker],
                },
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["colo829"], "unit")

            self.assertIn(purity_blocker, summary["blockers"])
            evidence_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/colo829/unit/sample_validation_summary.csv"))
            evidence_ids = {row["evidence_id"] for row in evidence_rows}
            self.assertIn("purity_illumina_metadata", evidence_ids)
            self.assertIn("purity_long_read_metadata", evidence_ids)
            self.assertIn("purity_recall_table", evidence_ids)
            adapter_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/colo829/unit/hrd_adapter_status.csv"))
            self.assertIn("Purity sensitivity benchmark", {row["adapter"] for row in adapter_rows})

    def test_cloud_materialization_plan_preserves_selected_sample_sets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                packet.write_cloud_materialization_plan(
                    "results/rosalind_hrd/unit",
                    "unit",
                    [{"sampleSet": "hcc1395_wgs", "missingArtifacts": []}],
                )
            plan = utils.read_text(root / "results/rosalind_hrd/unit/cloud_materialization_plan.md")
        self.assertIn("export ROSALIND_HRD_SAMPLE_SET=hcc1395_wgs", plan)

    def test_cloud_materialization_plan_identifies_diana_wgs_artifact_directory_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                packet.write_cloud_materialization_plan(
                    "results/rosalind_hrd/unit",
                    "unit",
                    [{"sampleSet": "diana_wgs", "missingArtifacts": ["diana_hrd_summary.json"]}],
                )
            plan = utils.read_text(root / "results/rosalind_hrd/unit/cloud_materialization_plan.md")
        self.assertIn("artifact directory that directly contains `diana_hrd_summary.json`", plan)
        self.assertIn("Do not point it at the parent run directory", plan)

    def test_cloud_materialization_plan_rejects_symlinked_parent_without_writing_target(self):
        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                real_output = root / "real-rosalind"
                if nested == "existing":
                    (real_output / nested).mkdir(parents=True)
                else:
                    real_output.mkdir()
                linked_output = root / "results" / "rosalind_hrd"
                linked_output.parent.mkdir()
                linked_output.symlink_to(real_output, target_is_directory=True)

                with patch.object(
                    packet,
                    "path_from_root",
                    lambda relative, root=root: root / relative,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "HRD packet output parent may not be a symlink",
                    ):
                        packet.write_cloud_materialization_plan(
                            f"results/rosalind_hrd/{nested}/unit",
                            "unit",
                            [{"sampleSet": "diana_wgs", "missingArtifacts": []}],
                        )

                self.assertFalse((real_output / nested / "unit").exists())

    def test_run_manifest_rechecks_packet_manifest_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_diana_raw_intake_artifacts(root)
            real_write_packet = packet.write_packet
            tampered = False

            def tamper_after_packet_summary(
                spec: packet.PacketSpec,
                packet_run_id: str,
            ) -> dict[str, object]:
                nonlocal tampered
                summary = real_write_packet(spec, packet_run_id)
                manifest_path = (
                    root
                    / "results/rosalind_hrd/diana_raw_intake/unit/report_manifest.json"
                )
                manifest = utils.read_json(manifest_path)
                manifest["review_summary"]["blockers"].append(
                    "changed after packet summary"
                )
                utils.write_json(manifest_path, manifest)
                tampered = True
                return summary

            with (
                patch.object(packet, "path_from_root", lambda relative: root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": "",
                        "ROSALIND_HRD_OUTPUT_ROOT": "",
                        "ROSALIND_HRD_RUN_ID": "unit",
                        "ROSALIND_HRD_SAMPLE_SET": "diana_raw_intake",
                    },
                ),
                patch.object(
                    packet,
                    "write_packet",
                    side_effect=tamper_after_packet_summary,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "Rosalind packet summary report manifest changed",
                ),
            ):
                packet.main()

            self.assertTrue(tampered)
            self.assertFalse(
                (root / "results/rosalind_hrd/unit/run_manifest.json").exists()
            )

    def test_run_manifest_rechecks_support_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_diana_raw_intake_artifacts(root)
            real_write_json = packet.write_json_create_only
            tampered = False

            def tamper_packet_index_after_run_manifest(
                path: Path,
                value: object,
            ) -> None:
                nonlocal tampered
                real_write_json(path, value)
                if path.name == "run_manifest.json":
                    utils.write_text(path.parent / "packet_index.md", "tampered\n")
                    tampered = True

            with (
                patch.object(packet, "path_from_root", lambda relative: root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": "",
                        "ROSALIND_HRD_OUTPUT_ROOT": "",
                        "ROSALIND_HRD_RUN_ID": "unit",
                        "ROSALIND_HRD_SAMPLE_SET": "diana_raw_intake",
                    },
                ),
                patch.object(
                    packet,
                    "write_json_create_only",
                    side_effect=tamper_packet_index_after_run_manifest,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "Rosalind run manifest is stale for packet_index.md",
                ),
            ):
                packet.main()

            self.assertTrue(tampered)
            for name in (
                "run_manifest.json",
                "packet_index.md",
                "cloud_materialization_plan.md",
            ):
                self.assertFalse((root / "results/rosalind_hrd/unit" / name).exists())

    def test_diana_raw_intake_packet_marks_waiting_input_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_diana_raw_intake_artifacts(root)

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_raw_intake"], "unit")

            self.assertTrue(any("Actual Diana BAM/FASTQ/CRAM paths" in blocker for blocker in summary["blockers"]))
            adapter_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/diana_raw_intake/unit/hrd_adapter_status.csv"))
            self.assertIn("blocked_until_files", {row["state"] for row in adapter_rows})
            reviewer = utils.read_text(root / "results/rosalind_hrd/diana_raw_intake/unit/reviewer_packet.md")
            self.assertIn("verify:diana-raw", reviewer)
            self.assertIn("dinah_handoff_plan", reviewer)
            self.assertIn("plan:diana-raw-handoff", reviewer)


if __name__ == "__main__":
    unittest.main()
