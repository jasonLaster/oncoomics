#!/usr/bin/env python3
"""De-identified end-to-end contract tests for stage_deterministic_wgs_report.py.

The fixture mirrors the dictionaries and CSVs emitted by the build_* and
stage_evidence functions in /tmp/diana_hrd_wgs_worker.py. It contains no live
artifact paths, sample identifiers, cloud calls, or patient data.
"""

from __future__ import annotations

import ast
import base64
import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

GENERATOR = SCRIPT_DIR / "stage_deterministic_wgs_report.py"
SPEC = importlib.util.spec_from_file_location(
    "stage_deterministic_wgs_report", GENERATOR
)
assert SPEC and SPEC.loader
REPORT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT_MODULE)

PUBLISH_SCRIPT = SCRIPT_DIR / "publish_private_report.py"
PUBLISH_SPEC = importlib.util.spec_from_file_location(
    "publish_private_report", PUBLISH_SCRIPT
)
assert PUBLISH_SPEC and PUBLISH_SPEC.loader
PUBLISH = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(PUBLISH)

KMS_ARN = "arn:aws:kms:us-east-1:000000000000:key/00000000-0000-0000-0000-000000000000"
RUN_ID = "synthetic-hrd-run"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str] | None = None,
    delimiter: str = ",",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = fieldnames or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter=delimiter, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_minimal_report_packet(staging: Path) -> None:
    REPORT_MODULE.write_staged_text(staging / "report.md", "# Deterministic WGS\n")
    for name in (
        "crosscheck_input_plans.json",
        "evidence_checks.json",
        "input_sha256.csv",
        "readiness.csv",
    ):
        REPORT_MODULE.write_staged_text(staging / name, f"{name}\n")
    REPORT_MODULE.write_staged_json(
        staging / "report_manifest.json",
        {
            "schema_version": 1,
            "method_id": "deterministic_full_wgs",
            "report_kind": "deterministic_baseline",
            "evidence_status": "partial_evidence",
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "report_sha256": sha256(staging / "report.md"),
            "support_sha256": {
                name: sha256(staging / name)
                for name in (
                    "crosscheck_input_plans.json",
                    "evidence_checks.json",
                    "input_sha256.csv",
                    "readiness.csv",
                )
            },
            "source_sha256": {"somatic_vcf": "a" * 64},
            "review_summary": {"overall": {"authorized_hrd_state": "no_call"}},
        },
    )


def write_indexed_vcf(path: Path, records: list[str]) -> None:
    plain = path.with_suffix("")
    plain.parent.mkdir(parents=True, exist_ok=True)
    plain.write_text(
        "\n".join(
            [
                "##fileformat=VCFv4.2",
                "##FILTER=<ID=LowQual,Description=\"Synthetic non-PASS record\">",
                "##contig=<ID=chr1,length=1000000>",
                "##contig=<ID=chr13,length=50000000>",
                "##contig=<ID=chr17,length=50000000>",
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                *records,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(["bcftools", "view", "-Oz", "-o", str(path), str(plain)], check=True)
    subprocess.run(["bcftools", "index", "-t", "-f", str(path)], check=True)
    plain.unlink()


class StageDeterministicWgsReportInstallTests(unittest.TestCase):
    def test_schema_versions_are_exact_json_integers(self) -> None:
        for value in (True, 1.0, "1", 2, None):
            with self.subTest(value=value):
                self.assertFalse(
                    REPORT_MODULE.exact_schema_version(
                        {"schema_version": value},
                        1,
                    )
                )

        self.assertTrue(REPORT_MODULE.exact_schema_version({"schema_version": 1}, 1))
        self.assertTrue(REPORT_MODULE.exact_schema_status({"schema_version": 2, "status": "passed"}, 2))
        self.assertFalse(REPORT_MODULE.exact_schema_status({"schema_version": 2.0, "status": "passed"}, 2))

    def test_terminal_integer_helpers_reject_coercible_values(self) -> None:
        self.assertTrue(REPORT_MODULE.positive_int(1))
        self.assertTrue(REPORT_MODULE.nonnegative_int(0))
        self.assertTrue(REPORT_MODULE.integer_equals(7, 7))
        self.assertEqual(
            REPORT_MODULE.require_nonnegative_exact_int(0, "synthetic count"),
            0,
        )

        for value in (True, 1.0, "1", 0, -1, None):
            with self.subTest(helper="positive_int", value=value):
                self.assertFalse(REPORT_MODULE.positive_int(value))
        for value in (True, 1.0, "1", -1, None):
            with self.subTest(helper="nonnegative_int", value=value):
                self.assertFalse(REPORT_MODULE.nonnegative_int(value))
        for value in (True, 7.0, "7", 0, None):
            with self.subTest(helper="integer_equals", value=value):
                self.assertFalse(REPORT_MODULE.integer_equals(value, 7))
        for value in (True, 1.0, "1", -1, None):
            with self.subTest(helper="require_nonnegative_exact_int", value=value):
                with self.assertRaisesRegex(ValueError, "not an exact"):
                    REPORT_MODULE.require_nonnegative_exact_int(
                        value,
                        "synthetic count",
                    )

    def test_exact_bool_helper_rejects_coercible_values(self) -> None:
        self.assertTrue(
            REPORT_MODULE.require_exact_bool(
                True,
                True,
                "synthetic flag",
            )
        )
        self.assertFalse(
            REPORT_MODULE.require_exact_bool(
                False,
                False,
                "synthetic flag",
            )
        )
        for value in (1, "true", "false", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "not exactly"):
                    REPORT_MODULE.require_exact_bool(
                        value,
                        True,
                        "synthetic flag",
                    )

    def test_crosscheck_plan_validation_rejects_coercible_values(self) -> None:
        def materialization() -> dict[str, Any]:
            return {
                "outputs": {
                    name: {"bytes": 1, "sha256": f"{index}" * 64}
                    for index, name in enumerate(
                        (
                            "somatic.pass.vcf.gz",
                            "somatic.pass.vcf.gz.tbi",
                            "sbs96.csv",
                            "staged_input_validation.json",
                        ),
                        1,
                    )
                },
                "input_sha256": {
                    "filtered_vcf": "a" * 64,
                    "filtered_vcf_index": "b" * 64,
                    "source_sbs96_matrix": "c" * 64,
                    "reference_fasta": "d" * 64,
                    "reference_fai": "e" * 64,
                },
                "validation": {
                    "pass_snv_records": 1,
                    "pass_snv_alleles": 1,
                    "sbs96_contexts": 96,
                    "sbs96_burden": 1,
                    "matrix_matches_independent_pass_vcf_derivation": True,
                    "source_sample_names_retained": False,
                },
            }

        input_contract = {
            "routes": ["sequenza_scarhrd", "sigprofiler_sbs3"],
            "artifacts": {
                "tumor_bam": {"sha256": "6" * 64},
                "tumor_bai": {"sha256": "7" * 64},
                "normal_bam": {"sha256": "8" * 64},
                "normal_bai": {"sha256": "9" * 64},
            },
            "method_parameters": {"sequenza": {"female": True}},
        }

        self.assertEqual(
            REPORT_MODULE.build_crosscheck_input_plans(
                materialization(),
                input_contract,
            )["routes"]["sigprofiler_sbs3"]["validation"][
                "pass_snv_records"
            ],
            1,
        )

        mutations = (
            ("count bool", "pass_snv_records", True),
            ("count float", "sbs96_contexts", 96.0),
            ("count string", "sbs96_contexts", "96"),
            (
                "matrix flag string",
                "matrix_matches_independent_pass_vcf_derivation",
                "true",
            ),
            ("retained flag int", "source_sample_names_retained", 0),
        )
        for name, field, value in mutations:
            with self.subTest(name=name):
                payload = materialization()
                payload["validation"][field] = value

                with self.assertRaisesRegex(ValueError, "not an exact|not exactly"):
                    REPORT_MODULE.build_crosscheck_input_plans(
                        payload,
                        input_contract,
                    )

        output_mutations = (
            ("bytes bool", True),
            ("bytes float", 1.0),
            ("bytes string", "1"),
        )
        for name, value in output_mutations:
            with self.subTest(name=name):
                payload = materialization()
                payload["outputs"]["sbs96.csv"]["bytes"] = value

                with self.assertRaisesRegex(ValueError, "not an exact"):
                    REPORT_MODULE.build_crosscheck_input_plans(
                        payload,
                        input_contract,
                    )

    def test_crosscheck_plan_guards_avoid_raw_validation_coercion(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        module = ast.parse(source)
        raw_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"bool", "int"}
            and node.args
            and (
                "validation.get" in ast.unparse(node.args[0])
                or 'row["bytes"]' in ast.unparse(node.args[0])
                or "row['bytes']" in ast.unparse(node.args[0])
            )
        ]

        self.assertEqual(raw_coercions, [])

    def test_batch_execution_provenance_rejects_coercible_integers(self) -> None:
        mutations = (
            (
                "batch started bool",
                lambda execution: execution["batch"].__setitem__(
                    "started_at_epoch_ms",
                    True,
                ),
            ),
            (
                "batch stopped float",
                lambda execution: execution["batch"].__setitem__(
                    "stopped_at_epoch_ms",
                    2.0,
                ),
            ),
            (
                "batch attempt count string",
                lambda execution: execution["batch"].__setitem__(
                    "attempt_count",
                    "1",
                ),
            ),
            (
                "attempt started bool",
                lambda execution: execution["batch"]["attempts"][0].__setitem__(
                    "started_at_epoch_ms",
                    True,
                ),
            ),
            (
                "attempt stopped string",
                lambda execution: execution["batch"]["attempts"][0].__setitem__(
                    "stopped_at_epoch_ms",
                    "2",
                ),
            ),
            (
                "attempt exit bool",
                lambda execution: execution["batch"]["attempts"][0].__setitem__(
                    "exit_code",
                    False,
                ),
            ),
            (
                "attempt exit float",
                lambda execution: execution["batch"]["attempts"][0].__setitem__(
                    "exit_code",
                    0.0,
                ),
            ),
            (
                "timeout bool",
                lambda execution: execution["batch"]["timeout"].__setitem__(
                    "attemptDurationSeconds",
                    True,
                ),
            ),
            (
                "retry attempts string",
                lambda execution: execution["batch"]["retry_strategy"].__setitem__(
                    "attempts",
                    "1",
                ),
            ),
            (
                "job definition revision float",
                lambda execution: execution["job_definition"].__setitem__(
                    "revision",
                    1.0,
                ),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                execution = load_json(fixture.aux / "execution.json")
                mutate(execution)
                write_json(fixture.aux / "execution.json", execution)

                result = subprocess.run(
                    fixture.command(),
                    text=True,
                    capture_output=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "batch_execution_provenance",
                    result.stdout + result.stderr,
                )
                self.assertFalse((fixture.output / "report.md").exists())

    def test_batch_execution_provenance_avoids_raw_int_coercion(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        module = ast.parse(source)
        raw_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "execution_batch.get('started_at_epoch_ms'",
                    'execution_batch.get("started_at_epoch_ms"',
                    "execution_batch.get('stopped_at_epoch_ms'",
                    'execution_batch.get("stopped_at_epoch_ms"',
                    "execution_batch.get('attempt_count'",
                    'execution_batch.get("attempt_count"',
                    "execution_attempt.get('started_at_epoch_ms'",
                    'execution_attempt.get("started_at_epoch_ms"',
                    "execution_attempt.get('stopped_at_epoch_ms'",
                    'execution_attempt.get("stopped_at_epoch_ms"',
                    "execution_attempt.get('exit_code'",
                    'execution_attempt.get("exit_code"',
                    "execution_timeout.get('attemptDurationSeconds'",
                    'execution_timeout.get("attemptDurationSeconds"',
                    "execution_retry.get('attempts'",
                    'execution_retry.get("attempts"',
                    "execution_definition.get('revision'",
                    'execution_definition.get("revision"',
                )
            )
        ]

        self.assertEqual(raw_coercions, [])

    def test_run_provenance_rejects_coercible_lane_counts(self) -> None:
        mutations = (
            (
                "summary lanes bool",
                lambda fixture: self._mutate_json(
                    fixture.artifacts / "diana_hrd_summary.json",
                    lambda summary: summary["input"].__setitem__("lanes", True),
                ),
            ),
            (
                "summary lanes float",
                lambda fixture: self._mutate_json(
                    fixture.artifacts / "diana_hrd_summary.json",
                    lambda summary: summary["input"].__setitem__("lanes", 8.0),
                ),
            ),
            (
                "summary lanes string",
                lambda fixture: self._mutate_json(
                    fixture.artifacts / "diana_hrd_summary.json",
                    lambda summary: summary["input"].__setitem__("lanes", "8"),
                ),
            ),
            (
                "preflight lanes bool",
                lambda fixture: self._mutate_json(
                    fixture.aux / "preflight.json",
                    lambda preflight: preflight.__setitem__("wgs_lanes", True),
                ),
            ),
            (
                "preflight lanes float",
                lambda fixture: self._mutate_json(
                    fixture.aux / "preflight.json",
                    lambda preflight: preflight.__setitem__("wgs_lanes", 8.0),
                ),
            ),
            (
                "preflight lanes string",
                lambda fixture: self._mutate_json(
                    fixture.aux / "preflight.json",
                    lambda preflight: preflight.__setitem__("wgs_lanes", "8"),
                ),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                mutate(fixture)

                result = subprocess.run(
                    fixture.command(),
                    text=True,
                    capture_output=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("run_provenance", result.stdout + result.stderr)
                self.assertFalse((fixture.output / "report.md").exists())

    @staticmethod
    def _mutate_json(path: Path, mutate: Any) -> None:
        payload = load_json(path)
        mutate(payload)
        write_json(path, payload)

    def test_alignment_metrics_reject_coercible_json_counts(self) -> None:
        mutations = (
            ("bam bytes string", "tumor", "bam_bytes", "1000"),
            ("total reads string", "tumor", "total_reads", "100"),
            ("mapped reads string", "tumor", "mapped_reads", "90"),
            ("duplicate reads string", "tumor", "duplicate_reads", "10"),
            ("normal reads float", "normal", "total_reads", 120.0),
            ("normal duplicate bool", "normal", "duplicate_reads", True),
        )
        for name, role, field, value in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                self._mutate_alignment_json_count(fixture, role, field, value)

                result = subprocess.run(
                    fixture.command(),
                    text=True,
                    capture_output=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "alignment_metric_bounds",
                    result.stdout + result.stderr,
                )
                self.assertFalse((fixture.output / "report.md").exists())

    def test_alignment_gather_rejects_coercible_counts(self) -> None:
        mutations = (
            (
                "bam bytes bool",
                lambda row: row.__setitem__("output_bam_bytes", True),
            ),
            (
                "bam bytes float",
                lambda row: row.__setitem__("output_bam_bytes", 1000.0),
            ),
            (
                "bam bytes string",
                lambda row: row.__setitem__("output_bam_bytes", "1000"),
            ),
            (
                "lane count bool",
                lambda row: row.__setitem__("lane_count", True),
            ),
            (
                "lane count float",
                lambda row: row.__setitem__("lane_count", 4.0),
            ),
            (
                "lane count string",
                lambda row: row.__setitem__("lane_count", "4"),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                self._mutate_json(
                    fixture.aux / "gather.json",
                    lambda payload, mutate=mutate: mutate(payload["samples"][0]),
                )

                result = subprocess.run(
                    fixture.command(),
                    text=True,
                    capture_output=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "alignment_provenance",
                    result.stdout + result.stderr,
                )
                self.assertFalse((fixture.output / "report.md").exists())

    def test_alignment_guards_avoid_raw_int_coercion(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        module = ast.parse(source)
        raw_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "json_row.get('bam_bytes'",
                    'json_row.get("bam_bytes"',
                    "json_row.get('total_reads'",
                    'json_row.get("total_reads"',
                    "json_row.get('mapped_reads'",
                    'json_row.get("mapped_reads"',
                    "json_row.get('duplicate_reads'",
                    'json_row.get("duplicate_reads"',
                    "gather_row.get('output_bam_bytes'",
                    'gather_row.get("output_bam_bytes"',
                    "gather_row.get('lane_count'",
                    'gather_row.get("lane_count"',
                    "alignment_by_role[role].get(field",
                    'alignment_by_role[role].get(field',
                    "alignment_by_role[role]['bam_bytes'",
                    'alignment_by_role[role]["bam_bytes"',
                    "alignment_by_role[role]['total_reads'",
                    'alignment_by_role[role]["total_reads"',
                    "alignment_by_role[role]['mapped_reads'",
                    'alignment_by_role[role]["mapped_reads"',
                    "alignment_by_role[role]['duplicate_reads'",
                    'alignment_by_role[role]["duplicate_reads"',
                )
            )
        ]

        self.assertEqual(raw_coercions, [])

    @staticmethod
    def _mutate_alignment_json_count(
        fixture: SyntheticFixture,
        role: str,
        field: str,
        value: Any,
    ) -> None:
        def mutate_alignment(alignment: dict[str, Any]) -> None:
            for row in alignment["rows"]:
                if row["role"] == role:
                    row[field] = value

        StageDeterministicWgsReportInstallTests._mutate_json(
            fixture.artifacts / "alignment/bam_validation_summary.json",
            mutate_alignment,
        )
        StageDeterministicWgsReportInstallTests._mutate_json(
            fixture.artifacts / "diana_hrd_summary.json",
            lambda summary: mutate_alignment(summary["alignment"]),
        )

    def test_run_provenance_avoids_raw_int_coercion(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        module = ast.parse(source)
        raw_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "input_payload.get('lanes'",
                    'input_payload.get("lanes"',
                    "preflight.get('wgs_lanes'",
                    'preflight.get("wgs_lanes"',
                )
            )
        ]

        self.assertEqual(raw_coercions, [])

    def test_terminal_byte_guards_avoid_raw_int_coercion(self) -> None:
        module = ast.parse(GENERATOR.read_text(encoding="utf-8"))
        raw_byte_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "audit.get('bytes_streamed'",
                    'audit.get("bytes_streamed"',
                    "destination.get('bytes'",
                    'destination.get("bytes"',
                    "execution_worker.get('bytes'",
                    'execution_worker.get("bytes"',
                    "input_snapshot.get('file_count'",
                    'input_snapshot.get("file_count"',
                    "input_snapshot['file_count'",
                    'input_snapshot["file_count"',
                    "materialized.get('bytes'",
                    'materialized.get("bytes"',
                    "exact_materialization.get('object_count'",
                    'exact_materialization.get("object_count"',
                    "exact_materialization.get('passed_count'",
                    'exact_materialization.get("passed_count"',
                    "final_freeze.get('object_count'",
                    'final_freeze.get("object_count"',
                    "final_freeze.get('passed_count'",
                    'final_freeze.get("passed_count"',
                    "preflight.get('wgs_bytes'",
                    'preflight.get("wgs_bytes"',
                    "receipt.get('object_count'",
                    'receipt.get("object_count"',
                    "receipt.get('passed_count'",
                    'receipt.get("passed_count"',
                    "row.get('actual_size_bytes'",
                    'row.get("actual_size_bytes"',
                    "row.get('bytes'",
                    'row.get("bytes"',
                    "source.get('bytes'",
                    'source.get("bytes"',
                    "staged_output.get('bytes'",
                    'staged_output.get("bytes"',
                )
            )
        ]

        self.assertEqual(raw_byte_coercions, [])

    def test_terminal_schema_guards_use_exact_integer_helper(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(GENERATOR))

        raw_comparisons = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "schema_version" not in segment:
                continue
            if segment in {
                'type(payload.get("schema_version")) is int',
                'payload["schema_version"] == expected',
            }:
                continue
            raw_comparisons.append(f"{node.lineno}: {segment}")

        self.assertEqual(raw_comparisons, [])

    def test_load_json_rejects_input_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-input-"
        ) as temporary:
            root = Path(temporary)
            real_parent = root / "real-inputs"
            real_parent.mkdir()
            (real_parent / "input.json").write_text(
                '{"status":"passed"}\n',
                encoding="utf-8",
            )
            linked_parent = root / "linked-inputs"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                REPORT_MODULE.load_json(linked_parent / "input.json")

    def test_load_csv_rejects_input_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-input-"
        ) as temporary:
            root = Path(temporary)
            real_parent = root / "real-inputs"
            real_parent.mkdir()
            (real_parent / "input.csv").write_text(
                "status\npassed\n",
                encoding="utf-8",
            )
            linked_parent = root / "linked-inputs"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                REPORT_MODULE.load_csv(linked_parent / "input.csv")

    def test_forbidden_tokens_merge_materialized_file_tokens(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-forbidden-tokens-"
        ) as temporary:
            token_file = Path(temporary) / "forbidden_tokens.json"
            write_json(token_file, ["synthetic", "synthetic-private-sample"])

            tokens = REPORT_MODULE.forbidden_tokens(
                {"input": {"dataset": "", "pair": ""}},
                [],
                [],
                {"objects": [], "source_uri": "", "result_uri": ""},
                [" synthetic "],
                [token_file],
            )

        self.assertEqual(len(tokens), len(set(tokens)))
        self.assertIn("synthetic", tokens)
        self.assertIn("synthetic-private-sample", tokens)
        self.assertLess(
            tokens.index("synthetic-private-sample"),
            tokens.index("synthetic"),
        )

    def test_input_snapshot_receipt_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-input-snapshot-receipt-"
        ) as temporary:
            root = Path(temporary)
            output = root / "input-snapshot-receipt.json"
            real_fsync_directory = REPORT_MODULE.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.chmod(0o600)
                output.write_text(
                    '{"status":"tampered"}\n',
                    encoding="utf-8",
                )
                output.chmod(0o400)

            with (
                patch.object(
                    REPORT_MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "input snapshot receipt changed during write",
                ),
            ):
                REPORT_MODULE.write_snapshot_receipt(
                    output,
                    {
                        "schema_version": 1,
                        "status": "passed",
                    },
                )

            self.assertFalse(output.exists())

    def test_input_snapshot_receipt_rejects_symlinked_output_parent(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-input-snapshot-receipt-"
        ) as temporary:
            root = Path(temporary)
            real_parent = root / "real-snapshot"
            real_parent.mkdir()
            linked_parent = root / "linked-snapshot"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                REPORT_MODULE.write_snapshot_receipt(
                    linked_parent / "input-snapshot-receipt.json",
                    {
                        "schema_version": 1,
                        "status": "passed",
                    },
                )

            self.assertFalse((real_parent / "input-snapshot-receipt.json").exists())

    def test_packet_file_install_removes_partial_after_file_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")

            with (
                patch.object(
                    REPORT_MODULE.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                REPORT_MODULE.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_packet_file_install_removes_partial_after_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")

            with (
                patch.object(
                    REPORT_MODULE.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                REPORT_MODULE.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_packet_file_install_rejects_symlinked_staged_source(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            root = Path(temporary)
            real_source = root / "real-report.md"
            real_source.write_bytes(b"one\n")
            symlink_source = root / "report.md"
            symlink_source.symlink_to(real_source)
            destination = root / "output" / "report.md"
            destination.parent.mkdir()

            with self.assertRaisesRegex(ValueError, "staged report packet"):
                REPORT_MODULE.copy_create_only(symlink_source, destination)

            self.assertFalse(destination.exists())

    def test_packet_file_install_rejects_symlinked_destination_parent(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            root = Path(temporary)
            source = root / "report.md"
            source.write_bytes(b"one\n")
            real_output = root / "real-output"
            real_output.mkdir()
            linked_output = root / "linked-output"
            linked_output.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "report output packet parent may not be a symlink",
            ):
                REPORT_MODULE.copy_create_only(source, linked_output / "report.md")

            self.assertFalse((real_output / "report.md").exists())

    def test_packet_file_install_revalidates_copied_bytes(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")
            real_fsync_directory = REPORT_MODULE.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                destination.write_bytes(b"tampered deterministic report\n")

            with (
                patch.object(
                    REPORT_MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged report packet changed during copy",
                ),
            ):
                REPORT_MODULE.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_staged_report_write_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            root = Path(temporary)
            output = root / "report.md"
            real_fsync_directory = REPORT_MODULE.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_bytes(b"tampered deterministic report\n")

            with (
                patch.object(
                    REPORT_MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged report packet changed during write",
                ),
            ):
                REPORT_MODULE.write_staged_text(output, "# Report\n")

            self.assertFalse(output.exists())

    def test_staged_report_manifest_rejects_stale_report_binding(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            staging = Path(temporary)
            write_minimal_report_packet(staging)

            (staging / "report.md").write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "report manifest is stale for report.md",
            ):
                REPORT_MODULE.require_report_manifest(staging)

    def test_staged_report_manifest_rejects_stale_support_binding(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            staging = Path(temporary)
            write_minimal_report_packet(staging)

            (staging / "readiness.csv").write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "report manifest is stale for readiness.csv",
            ):
                REPORT_MODULE.require_report_manifest(staging)

    def test_staged_report_manifest_rejects_coerced_hashes(self) -> None:
        digest = "1" * 64
        cases = (
            (
                "report",
                lambda manifest: manifest.__setitem__("report_sha256", int(digest)),
                "report.md",
            ),
            (
                "support",
                lambda manifest: manifest["support_sha256"].__setitem__(
                    "readiness.csv",
                    int(digest),
                ),
                "readiness.csv",
            ),
            (
                "source",
                lambda manifest: manifest["source_sha256"].__setitem__(
                    "somatic_vcf",
                    int(digest),
                ),
                "source_sha256.somatic_vcf",
            ),
        )

        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-install-"
            ) as temporary:
                staging = Path(temporary)
                write_minimal_report_packet(staging)
                manifest_path = staging / "report_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["report_sha256"] = digest
                manifest["source_sha256"]["somatic_vcf"] = digest
                for name in manifest["support_sha256"]:
                    manifest["support_sha256"][name] = digest
                mutate(manifest)
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with (
                    patch.object(REPORT_MODULE, "sha256", return_value=digest),
                    self.assertRaisesRegex(
                        ValueError,
                        "report manifest has malformed SHA-256 for " + message,
                    ),
                ):
                    REPORT_MODULE.require_report_manifest(staging)

    def test_staged_report_manifest_requires_exact_envelope(self) -> None:
        mutations = {
            "extra_top_level": lambda manifest: manifest.__setitem__(
                "legacy_note", "accepted"
            ),
            "missing_no_call_boundary": lambda manifest: manifest.pop(
                "authorized_hrd_state"
            ),
            "extra_support_file": lambda manifest: manifest[
                "support_sha256"
            ].__setitem__("legacy_support.json", "a" * 64),
            "float_schema_version": lambda manifest: manifest.__setitem__(
                "schema_version",
                1.0,
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-install-"
            ) as temporary:
                staging = Path(temporary)
                write_minimal_report_packet(staging)
                manifest_path = staging / "report_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(manifest)
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "report manifest (envelope|identity|support SHA-256 inventory) is not exact",
                ):
                    REPORT_MODULE.require_report_manifest(staging)

    def test_failed_packet_install_removes_only_installed_packet_files(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "report"
            staging.mkdir()
            output.mkdir()
            staged_paths = []
            for name in REPORT_MODULE.OUTPUT_NAMES:
                path = staging / name
                path.write_text(f"{name}\n", encoding="utf-8")
                staged_paths.append(path)

            real_copy = REPORT_MODULE.copy_create_only

            def fail_with_unexpected_child(source: Path, destination: Path) -> None:
                real_copy(source, destination)
                if destination.name == "readiness.csv":
                    (destination.parent / "unexpected.tmp").write_text(
                        "stray partial file\n",
                        encoding="utf-8",
                    )
                    raise ValueError("synthetic install failure")

            with (
                patch.object(
                    REPORT_MODULE,
                    "copy_create_only",
                    side_effect=fail_with_unexpected_child,
                ),
                self.assertRaisesRegex(ValueError, "synthetic install failure"),
            ):
                REPORT_MODULE.install_packet_create_only(staged_paths, output)

            self.assertTrue(output.is_dir())
            for name in REPORT_MODULE.OUTPUT_NAMES:
                self.assertFalse((output / name).exists())
            self.assertEqual(
                (output / "unexpected.tmp").read_text(encoding="utf-8"),
                "stray partial file\n",
            )

    def test_failed_packet_install_removes_installed_files_after_final_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "report"
            staging.mkdir()
            output.mkdir()
            staged_paths = []
            for name in REPORT_MODULE.OUTPUT_NAMES:
                path = staging / name
                path.write_text(f"{name}\n", encoding="utf-8")
                staged_paths.append(path)

            side_effects = [None for _ in REPORT_MODULE.OUTPUT_NAMES]
            side_effects.append(OSError("synthetic report directory fsync failure"))
            with (
                patch.object(
                    REPORT_MODULE,
                    "fsync_directory",
                    side_effect=side_effects,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "synthetic report directory fsync failure",
                ),
            ):
                REPORT_MODULE.install_packet_create_only(staged_paths, output)

            self.assertTrue(output.is_dir())
            self.assertEqual([], list(output.iterdir()))

    def test_packet_install_removes_installed_files_after_stale_installed_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "report"
            staging.mkdir()
            output.mkdir()
            write_minimal_report_packet(staging)
            manifest_path = staging / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["support_sha256"]["readiness.csv"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "report manifest is stale for readiness.csv",
            ):
                REPORT_MODULE.install_packet_create_only(
                    [staging / name for name in REPORT_MODULE.OUTPUT_NAMES],
                    output,
                )

            self.assertTrue(output.is_dir())
            self.assertEqual([], list(output.iterdir()))

    def test_packet_install_rechecks_installed_files_after_final_directory_fsync(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="synthetic-hrd-report-install-"
        ) as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "report"
            staging.mkdir()
            output.mkdir()
            write_minimal_report_packet(staging)
            real_fsync_directory = REPORT_MODULE.fsync_directory

            def tamper_after_output_fsync(path: Path) -> None:
                real_fsync_directory(path)
                if path == output:
                    (output / "input_sha256.csv").write_text(
                        "tampered after final output fsync\n",
                        encoding="utf-8",
                    )

            with (
                patch.object(
                    REPORT_MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_output_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report output packet changed during install: input_sha256.csv",
                ),
            ):
                REPORT_MODULE.install_packet_create_only(
                    [staging / name for name in REPORT_MODULE.OUTPUT_NAMES],
                    output,
                )

            self.assertTrue(output.is_dir())
            self.assertEqual([], list(output.iterdir()))


def readiness_rows(pass_records: int, bin_count: int, usable_snvs: int) -> list[dict[str, str]]:
    return [
        {"evidence_surface": "source_sha256", "status": "ready", "detail": "30/30 synthetic payload objects passed SHA-256."},
        {"evidence_surface": "wgs_alignment", "status": "ready", "detail": "Eight synthetic lanes were structurally validated."},
        {"evidence_surface": "matched_normal_somatic_variants", "status": "ready", "detail": f"Mutect2 PASS records: {pass_records}."},
        {"evidence_surface": "coverage_cnv", "status": "partial_evidence", "detail": f"{bin_count} normalized coverage bins; not allele-specific."},
        {"evidence_surface": "sbs96", "status": "partial_evidence", "detail": f"{usable_snvs} PASS SNV in SBS96; no SBS3 assignment."},
        {"evidence_surface": "sv", "status": "partial_evidence", "detail": "BAM-derived counts only; no validated SV callset."},
        {"evidence_surface": "scarHRD", "status": "no_call", "detail": "No allele-specific segments or purity/ploidy solution."},
        {"evidence_surface": "CHORD", "status": "no_call", "detail": "No validated production SV callset."},
        {"evidence_surface": "HRDetect", "status": "no_call", "detail": "Integrated model is not validated."},
        {"evidence_surface": "overall_hrd", "status": "no_call", "detail": "No defensible scalar HRD classification."},
    ]


class SyntheticFixture:
    def __init__(self, root: Path, *, inconsistent_variant_count: bool = False):
        self.root = root
        self.artifacts = root / "artifacts"
        self.early = root / "early"
        self.aux = root / "auxiliary"
        self.output = root / "report-output"
        self.inconsistent_variant_count = inconsistent_variant_count
        self._build()

    def _build(self) -> None:
        alignment_rows = [
            {
                "status": "passed",
                "role": "tumor",
                "bam_bytes": 1000,
                "total_reads": 100,
                "mapped_reads": 90,
                "duplicate_reads": 10,
                "reference": "ucsc_hg38_analysis_set_full",
            },
            {
                "status": "passed",
                "role": "normal",
                "bam_bytes": 1200,
                "total_reads": 120,
                "mapped_reads": 110,
                "duplicate_reads": 12,
                "reference": "ucsc_hg38_analysis_set_full",
            },
        ]
        alignment = {"status": "passed", "rows": alignment_rows}
        write_json(self.artifacts / "alignment/bam_validation_summary.json", alignment)
        write_csv(self.artifacts / "alignment/bam_validation_summary.csv", alignment_rows)
        for row in alignment_rows:
            flagstat = (
                f"{row['total_reads']} + 0 in total (QC-passed reads + QC-failed reads)\n"
                f"{row['duplicate_reads']} + 0 duplicates\n"
                f"{row['mapped_reads']} + 0 mapped (90.00% : N/A)\n"
            )
            (self.artifacts / f"alignment/{row['role']}.flagstat.txt").write_text(flagstat, encoding="utf-8")

        filtered_vcf = self.artifacts / "variants/diana.wgs.mutect2.filtered.vcf.gz"
        brca_vcf = self.artifacts / "variants/brca1_brca2.pass.vcf.gz"
        pass_snv = "chr17\t43050000\t.\tC\tT\t60\tPASS\t."
        write_indexed_vcf(
            filtered_vcf,
            ["chr1\t100\t.\tA\tAT\t10\tLowQual\t.", pass_snv],
        )
        write_indexed_vcf(brca_vcf, [pass_snv])
        brca_rows = [
            {
                "contig": "chr17",
                "position": "43050000",
                "ref": "C",
                "alt": "T",
                "filter": "PASS",
                "genotype": "",
                "allele_depth": "",
                "allele_fraction": "",
                "region_label": "BRCA1",
                "annotation_status": "region_only_requires_variant_annotation_review",
            }
        ]
        write_csv(
            self.artifacts / "variants/brca1_brca2_pass_variants.csv",
            brca_rows,
            [
                "contig", "position", "ref", "alt", "filter", "genotype",
                "allele_depth", "allele_fraction", "region_label", "annotation_status",
            ],
        )
        reported_pass = 2 if self.inconsistent_variant_count else 1
        variants = {
            "status": "passed",
            "caller": "GATK Mutect2 synthetic matched tumor-normal fixture",
            "total_filtered_records": 2,
            "pass_records": reported_pass,
            "pass_snvs": 1,
            "pass_indels": 0,
            "brca1_brca2_pass_region_records": 1,
            "panel_of_normals": "synthetic-pon.vcf.gz",
            "germline_resource": "synthetic-germline.vcf.gz",
            "contamination_resource": "synthetic-common.vcf",
            "contamination_table": "contamination.table",
            "orientation_bias_model": "read-orientation-model.tar.gz",
            "filtered_vcf": filtered_vcf.name,
            "caveat": "Synthetic research-use fixture.",
        }
        write_json(self.artifacts / "variants/mutect2_summary.json", variants)
        write_csv(
            self.artifacts / "variants/contamination.table",
            [{"sample": "subject01_tumor", "contamination": "0.01", "error": "0.001"}],
            delimiter="\t",
        )
        for name in (
            "tumor-segmentation.table",
            "tumor.pileups.table",
            "normal.pileups.table",
            "read-orientation-model.tar.gz",
        ):
            (self.artifacts / f"variants/{name}").write_bytes(b"synthetic\n")

        cnv_rows = [
            {"contig": "chr1", "start": 0, "end": 100, "length": 100, "tumor_depth_sum": 10, "normal_depth_sum": 10, "tumor_mean_depth": 0.1, "normal_mean_depth": 0.1, "raw_log2_tumor_normal": 0, "normalized_log2_tumor_normal": 0.7, "coverage_class": "relative_gain"},
            {"contig": "chr1", "start": 100, "end": 200, "length": 100, "tumor_depth_sum": 5, "normal_depth_sum": 10, "tumor_mean_depth": 0.05, "normal_mean_depth": 0.1, "raw_log2_tumor_normal": -1, "normalized_log2_tumor_normal": -0.7, "coverage_class": "relative_loss"},
            {"contig": "chr1", "start": 200, "end": 300, "length": 100, "tumor_depth_sum": 10, "normal_depth_sum": 10, "tumor_mean_depth": 0.1, "normal_mean_depth": 0.1, "raw_log2_tumor_normal": 0, "normalized_log2_tumor_normal": 0, "coverage_class": "neutral_or_low_signal"},
        ]
        cnv = {
            "status": "partial_evidence",
            "tool": "samtools bedcov normalized tumor-normal synthetic bins",
            "bin_count": len(cnv_rows),
            "median_raw_log2_tumor_normal": 0.0,
            "relative_gain_bins": 1,
            "relative_loss_bins": 1,
            "scarhrd_input_status": "no_call_without_allele_specific_segments_purity_ploidy",
            "caveat": "Synthetic coverage proxy.",
        }
        write_csv(self.artifacts / "cnv/coverage_cnv_bins.csv", cnv_rows)
        write_json(self.artifacts / "cnv/coverage_cnv_summary.json", cnv)

        mutation_types = ("C>A", "C>G", "C>T", "T>A", "T>C", "T>G")
        bases = "ACGT"
        sbs_rows: list[dict[str, Any]] = []
        for mutation in mutation_types:
            for left in bases:
                for right in bases:
                    sbs_rows.append(
                        {
                            "sample": "subject01_tumor",
                            "mutation_type": mutation,
                            "trinucleotide": f"{left}[{mutation}]{right}",
                            "count": 1 if not sbs_rows else 0,
                        }
                    )
        signatures = {
            "status": "partial_evidence",
            "source_vcf": filtered_vcf.name,
            "source_record_policy": "PASS SNVs",
            "usable_snv_records": 1,
            "skipped_snv_records": 0,
            "sbs96_rows": 96,
            "sigprofiler_assignment_status": "not_assessable_low_mutation_count",
            "sbs3_status": "no_call_signature_assignment_and_threshold_policy_not_locked",
            "caveat": "Synthetic SBS96 fixture.",
        }
        write_csv(self.artifacts / "signatures/wgs_sbs96_matrix.csv", sbs_rows)
        write_json(self.artifacts / "signatures/signature_assignment_summary.json", signatures)

        sv_rows = [
            {"status": "partial_evidence", "role": "tumor", "total_alignments": 100, "supplementary_alignments": 2, "discordant_mapped_pairs": 3, "interchromosomal_pairs": 1, "large_insert_pairs": 1, "chord_input_status": "no_call_requires_validated_production_sv_caller_vcf", "caveat": "Synthetic counts."},
            {"status": "partial_evidence", "role": "normal", "total_alignments": 120, "supplementary_alignments": 1, "discordant_mapped_pairs": 2, "interchromosomal_pairs": 1, "large_insert_pairs": 0, "chord_input_status": "no_call_requires_validated_production_sv_caller_vcf", "caveat": "Synthetic counts."},
        ]
        sv = {"status": "partial_evidence", "rows": sv_rows, "production_sv_callset_status": "no_call"}
        write_csv(self.artifacts / "sv/sv_evidence_summary.csv", sv_rows)
        write_json(self.artifacts / "sv/sv_evidence_summary.json", sv)
        write_json(
            self.artifacts / "tool_versions.json",
            {"bwa": "synthetic-bwa", "samtools": "synthetic-samtools", "bcftools": "synthetic-bcftools", "gatk": "synthetic-gatk"},
        )

        readiness = readiness_rows(reported_pass, len(cnv_rows), 1)
        write_csv(self.artifacts / "hrd_readiness.csv", readiness)
        summary = {
            "status": "no_call",
            "evidence_status": "partial_evidence",
            "run_id": RUN_ID,
            "generated_at": "2026-07-17T00:00:00+00:00",
            "elapsed_seconds": 1.0,
            "input": {
                "dataset": "WGS data",
                "pair": "tumor matched normal",
                "lanes": 8,
                "reference": "UCSC hg38 analysis set full",
                "source_integrity": "passed",
            },
            "alignment": alignment,
            "variants": variants,
            "coverage_cnv": cnv,
            "signatures": signatures,
            "sv": sv,
            "hrd_readiness": readiness,
            "boundary": "Synthetic partial evidence; overall HRD remains no_call.",
        }
        write_json(self.artifacts / "diana_hrd_summary.json", summary)

        write_json(
            self.aux / "preflight.json",
            {"status": "passed", "run_id": RUN_ID, "wgs_lanes": 8, "wgs_bytes": 16, "reference": "UCSC hg38 analysis set full"},
        )
        write_json(
            self.aux / "gather.json",
            {
                "status": "passed",
                "run_id": RUN_ID,
                "reference": "ucsc_hg38_analysis_set_full",
                "samples": [
                    {"status": "passed", "role": "tumor", "lane_count": 4, "output_bam": "tumor.markdup.bam", "output_bam_bytes": 1000},
                    {"status": "passed", "role": "normal", "lane_count": 4, "output_bam": "normal.markdup.bam", "output_bam_bytes": 1200},
                ],
            },
        )
        audit_objects = [
            {
                "status": "passed",
                "dataset": "wgs" if index < 16 else "immunoid",
                "data_type": "FASTQ",
                "actual_size_bytes": 1,
                "size_matches": True,
                "sha256_matches": True,
                "sample_id": "subject01",
                "assay": "",
            }
            for index in range(30)
        ]
        write_json(
            self.aux / "sha-audit.json",
            {
                "status": "passed",
                "algorithm": "sha256",
                "object_count": 30,
                "passed_count": 30,
                "failed_count": 0,
                "bytes_streamed": 30,
                "objects": audit_objects,
            },
        )
        launch_uri = "s3://synthetic-work/run/worker.py"
        executed_uri = (
            "s3://diana-omics-private-results-test/"
            "runs/subject01/synthetic-run/deterministic/provenance/worker.py"
        )
        worker_receipt_path = self.aux / "executed-worker-freeze.json"
        write_json(
            worker_receipt_path,
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": RUN_ID,
                "batch_job_id": "synthetic-job",
                "source": {
                    "task_arn": "arn:aws:ecs:us-east-1:0:task/synthetic/task",
                    "container_runtime_id": "synthetic-runtime",
                    "bytes": 123,
                    "sha256": "b" * 64,
                },
                "freeze": {
                    "bucket": "diana-omics-private-results-test",
                    "key": (
                        "runs/subject01/synthetic-run/deterministic/"
                        "provenance/worker.py"
                    ),
                    "version_id": "executed-worker-version",
                    "bytes": 123,
                    "checksum_type": "FULL_OBJECT",
                    "checksum_sha256_hex": "b" * 64,
                    "kms_key_id": KMS_ARN,
                },
                "checks": dict(
                    REPORT_MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_CHECKS
                ),
            },
        )
        worker_receipt_upload_path = self.aux / "executed-worker-freeze-upload.json"
        write_json(
            worker_receipt_upload_path,
            {
                "schema_version": 1,
                "status": "passed",
                "local_receipt_sha256": sha256(worker_receipt_path),
                "object": {
                    "version_id": "executed-worker-receipt-version",
                    "checksum_sha256_hex": sha256(worker_receipt_path),
                    "kms_key_id": KMS_ARN,
                },
                "checks": dict(
                    REPORT_MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_UPLOAD_CHECKS
                ),
            },
        )
        write_json(
            self.aux / "execution.json",
            {
                "schema_version": 1,
                "run_id": RUN_ID,
                "batch": {
                    "status": "SUCCEEDED",
                    "started_at_epoch_ms": 1,
                    "stopped_at_epoch_ms": 2,
                    "attempt_count": 1,
                    "attempts": [
                        {
                            "started_at_epoch_ms": 1,
                            "stopped_at_epoch_ms": 2,
                            "status_reason": "",
                            "container_instance_arn": "arn:aws:ecs:us-east-1:0:container-instance/synthetic",
                            "task_arn": "arn:aws:ecs:us-east-1:0:task/synthetic/task",
                            "log_stream": "synthetic-stream",
                            "exit_code": 0,
                            "reason": "",
                        }
                    ],
                    "retry_strategy": {"attempts": 1, "evaluateOnExit": []},
                    "timeout": {"attemptDurationSeconds": 129600},
                    "job_id": "synthetic-job",
                    "job_queue_arn": "arn:aws:batch:us-east-1:000000000000:job-queue/synthetic",
                    "job_definition_arn": "arn:aws:batch:us-east-1:000000000000:job-definition/synthetic:1",
                    "log_group": "/synthetic/logs",
                    "log_stream": "synthetic-stream",
                    "command": [
                        "aws",
                        "s3",
                        "cp",
                        launch_uri,
                        "worker.py",
                        "python3",
                        "worker.py",
                        "evidence",
                        "--run-id",
                        RUN_ID,
                    ],
                },
                "container": {
                    "image_reference": "synthetic/image:fixture",
                    "image_digest": "sha256:" + "a" * 64,
                    "task_arn": "arn:aws:ecs:us-east-1:0:task/synthetic/task",
                    "runtime_ids": ["synthetic-runtime"],
                },
                "queue": {"name": "synthetic", "status": "VALID"},
                "job_definition": {"name": "synthetic", "revision": 1},
                "worker": {
                    "launch_uri": launch_uri,
                    "executed_uri": executed_uri,
                    "executed_version_id": "executed-worker-version",
                    "freeze_receipt_path": str(worker_receipt_path),
                    "freeze_receipt_sha256": sha256(worker_receipt_path),
                    "freeze_receipt_version_id": "executed-worker-receipt-version",
                    "freeze_receipt_upload_path": str(worker_receipt_upload_path),
                    "freeze_receipt_upload_sha256": sha256(
                        worker_receipt_upload_path
                    ),
                    "bytes": 123,
                    "sha256": "b" * 64,
                    "etag": '"synthetic-worker"',
                    "last_modified": "2026-07-16T23:00:00+00:00",
                    "checksums": {"ChecksumSHA256": "synthetic-checksum"},
                    "checksum_type": "FULL_OBJECT",
                    "server_side_encryption": "aws:kms",
                    "kms_key_id": KMS_ARN,
                    "checks": dict(REPORT_MODULE.EXPECTED_BATCH_WORKER_CHECKS),
                },
            },
        )
        stage_destination_prefix = (
            f"s3://diana-omics-private-results-test/runs/subject01/{RUN_ID}/"
            "deterministic/provenance/wgs-stage/"
        )
        stage_rows = []
        for index, name in enumerate(("preflight.json", "gather.json"), 1):
            local = self.aux / name
            digest = sha256(local)
            checksum = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
            stage_rows.append(
                {
                    "name": name,
                    "source": {
                        "bucket": "diana-omics-work-test",
                        "key": (
                            f"runs/diana-hrd/{RUN_ID}/private-results/{name}"
                        ),
                        "version_id": "null",
                        "bytes": local.stat().st_size,
                        "etag": "synthetic-stage-source",
                        "checksums": {"ChecksumSHA256": checksum},
                        "checksum_type": "FULL_OBJECT",
                        "sha256": digest,
                        "server_side_encryption": "aws:kms",
                        "kms_key_id": KMS_ARN,
                    },
                    "destination": {
                        "bucket": "diana-omics-private-results-test",
                        "key": (
                            f"runs/subject01/{RUN_ID}/deterministic/"
                            f"provenance/wgs-stage/{name}"
                        ),
                        "version_id": f"stage-version-{index}",
                        "bytes": local.stat().st_size,
                        "etag": "synthetic-stage-destination",
                        "checksums": {"ChecksumSHA256": checksum},
                        "checksum_type": "FULL_OBJECT",
                        "sha256": digest,
                        "kms_key_id": KMS_ARN,
                    },
                    "checks": {
                        "get_matches_head": True,
                        "local_bytes_exact": True,
                        "semantic_binding": True,
                        "source_kms_exact": True,
                        "source_unchanged": True,
                        "copy_version_exact": True,
                        "destination_get_matches_head": True,
                        "bytes_equal": True,
                        "sha256_equal": True,
                        "full_object_checksum": True,
                        "exact_kms": True,
                    },
                    "status": "passed",
                }
            )
        stage_receipt_path = self.aux / "stage-provenance.json"
        write_json(
            stage_receipt_path,
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": RUN_ID,
                "batch_job_id": "synthetic-job",
                "batch_status": "SUCCEEDED",
                "execution_receipt_sha256": sha256(self.aux / "execution.json"),
                "source_prefix": (
                    f"s3://diana-omics-work-test/runs/diana-hrd/{RUN_ID}/"
                    "private-results/"
                ),
                "destination_prefix": stage_destination_prefix,
                "kms_key_arn": KMS_ARN,
                "source_bucket_versioning": "Suspended",
                "destination_bucket_versioning": "Enabled",
                "destination_history_exact": True,
                "script_sha256": "f" * 64,
                "receipt_anchor_strategy": (
                    "sha256_content_addressed_never_overwritten"
                ),
                "objects": stage_rows,
                "object_count": 2,
                "passed_count": 2,
            },
        )
        stage_receipt_sha = sha256(stage_receipt_path)
        write_json(
            self.aux / "stage-provenance-anchor.json",
            {
                "schema_version": 1,
                "status": "passed",
                "receipt_sha256": stage_receipt_sha,
                "receipt_bytes": stage_receipt_path.stat().st_size,
                "receipt_uri": (
                    stage_destination_prefix
                    + f"receipts/{stage_receipt_sha}.json"
                ),
                "receipt_version_id": "stage-receipt-version",
                "checks": {
                    "version_exact": True,
                    "get_matches_head": True,
                    "bytes_exact": True,
                    "local_sha256_exact": True,
                    "sha256_checksum_exact": True,
                    "exact_kms": True,
                    "content_type_exact": True,
                    "history_exact": True,
                },
            },
        )
        reference_fasta_sha256 = "d" * 64
        reference_fai_sha256 = "e" * 64
        write_json(
            self.aux / "staged-input-validation.json",
            {
                "schema_version": 1,
                "route": "sigprofiler_sbs3",
                "status": "passed",
                "checks": {
                    "somatic_vcf_reference": {
                        "status": "passed",
                        "pass_snv_records": 1,
                        "pass_snv_alleles": 1,
                        "reference_fasta_sha256": reference_fasta_sha256,
                        "reference_fai_sha256": reference_fai_sha256,
                    },
                    "sbs96_equivalence": {
                        "status": "passed",
                        "matrix_matches_independent_pass_vcf_derivation": True,
                        "contexts": 96,
                        "usable_pass_snv_alleles": 1,
                        "matrix_burden": 1,
                    },
                },
                "classification_authorization": "none",
                "authorized_hrd_state": "no_call",
            },
        )

        early_pass = [{"contig": "chr1", "position": "1", "filter": "PASS"}]
        early_cnv_rows = [{"contig": "chr1", "start": "0", "end": "100", "coverage_class": "neutral_or_low_signal"}]
        write_csv(self.early / "variants/core_hrr_pass_variants.csv", early_pass)
        write_csv(self.early / "coverage_cnv/coverage_cnv_bins.csv", early_cnv_rows)
        write_json(
            self.early / "early_look_summary.json",
            {
                "status": "partial_evidence",
                "overall_hrd_status": "no_call",
                "core_hrr_variants": {"pass_records": 1, "brca1_brca2_pass_records": 0},
                "coverage_cnv": {"bin_count": 1, "relative_gain_bins": 0, "relative_loss_bins": 0, "median_raw_log2_tumor_normal": 0.0},
                "contamination": {"contamination": 0.02},
                "bam_qc": {"tumor": {"total_reads": 10}, "normal": {"total_reads": 12}},
            },
        )
        (self.artifacts / "logs/worker-extra.log").parent.mkdir(parents=True, exist_ok=True)
        (self.artifacts / "logs/worker-extra.log").write_text(
            "synthetic unconsumed final artifact\n", encoding="utf-8"
        )
        freeze_rows = []
        for index, path in enumerate(sorted(item for item in self.artifacts.rglob("*") if item.is_file()), 1):
            relative = str(path.relative_to(self.artifacts))
            checksum = base64.b64encode(hashlib.sha256(path.read_bytes()).digest()).decode("ascii")
            freeze_rows.append(
                {
                    "relative_key": relative,
                    "source": {
                        "bucket": "diana-omics-work-test",
                        "key": f"runs/diana-hrd/{RUN_ID}/private-results/final/artifacts/{relative}",
                        "version_id": "source-version",
                        "bytes": path.stat().st_size,
                        "etag": "synthetic",
                        "checksums": {"ChecksumSHA256": checksum},
                        "checksum_type": "FULL_OBJECT",
                    },
                    "destination": {
                        "bucket": "diana-omics-private-results-test",
                        "key": f"runs/subject01/{RUN_ID}/deterministic/final/{relative}",
                        "version_id": f"destination-version-{index}",
                        "bytes": path.stat().st_size,
                        "etag": "synthetic",
                        "checksums": {"ChecksumSHA256": checksum},
                        "checksum_type": "FULL_OBJECT",
                        "server_side_encryption": "aws:kms",
                        "kms_key_id": KMS_ARN,
                    },
                    "checks": {
                        "listed_inventory_stable": True,
                        "source_stable": True,
                        "size_matches": True,
                        "common_checksum_matches": True,
                        "exact_kms_matches": True,
                        "destination_versioned": True,
                        "copy_response_version_matches": True,
                    },
                    "status": "passed",
                }
            )
        write_json(
            self.aux / "final-freeze.json",
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": RUN_ID,
                "batch_job_id": "synthetic-job",
                "batch_status": "SUCCEEDED",
                "execution_receipt": {
                    "path": str(self.aux / "execution.json"),
                    "sha256": sha256(self.aux / "execution.json"),
                },
                "source_prefix": f"s3://diana-omics-work-test/runs/diana-hrd/{RUN_ID}/private-results/final/artifacts/",
                "destination_prefix": f"s3://diana-omics-private-results-test/runs/subject01/{RUN_ID}/deterministic/final/",
                "kms_key_arn": KMS_ARN,
                "script_sha256": "e" * 64,
                "destination_bucket_versioning": "Enabled",
                "destination_initial_version_history_count": 0,
                "receipt_anchor_strategy": "sha256_content_addressed_create_only",
                "object_count": len(freeze_rows),
                "passed_count": len(freeze_rows),
                "initial_inventory_identity": [
                    {
                        "relative_key": row["relative_key"],
                        "key": row["source"]["key"],
                        "bytes": row["source"]["bytes"],
                        "etag": row["source"]["etag"],
                        "version_id": row["source"]["version_id"],
                    }
                    for row in freeze_rows
                ],
                "final_inventory_identity": [
                    {
                        "relative_key": row["relative_key"],
                        "key": row["source"]["key"],
                        "bytes": row["source"]["bytes"],
                        "etag": row["source"]["etag"],
                        "version_id": row["source"]["version_id"],
                    }
                    for row in freeze_rows
                ],
                "destination_inventory": [
                    {
                        "relative_key": row["relative_key"],
                        "key": row["destination"]["key"],
                        "version_id": row["destination"]["version_id"],
                        "bytes": row["destination"]["bytes"],
                        "etag": row["destination"]["etag"],
                        "checksums": row["destination"]["checksums"],
                        "checksum_type": "FULL_OBJECT",
                        "kms_key_id": KMS_ARN,
                    }
                    for row in freeze_rows
                ],
                "checks": {
                    "execution_receipt_bound": True,
                    "complete_source_inventory_unchanged": True,
                    "destination_exact_history_and_receipt_match": True,
                },
                "objects": freeze_rows,
            },
        )
        freeze_receipt = self.aux / "final-freeze.json"
        freeze_receipt_sha = sha256(freeze_receipt)
        write_json(
            self.aux / "final-freeze-anchor.json",
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": RUN_ID,
                "batch_job_id": "synthetic-job",
                "receipt_sha256": freeze_receipt_sha,
                "receipt_bytes": freeze_receipt.stat().st_size,
                "receipt_uri": (
                    f"s3://diana-omics-private-results-test/runs/subject01/{RUN_ID}/"
                    "deterministic/provenance/final-artifact-freeze-receipts/"
                    f"{freeze_receipt_sha}.json"
                ),
                "receipt_version_id": "final-freeze-receipt-version",
                "checks": {
                    "version_exact": True,
                    "bytes_exact": True,
                    "sha256_exact": True,
                    "sha256_checksum_exact": True,
                    "exact_kms": True,
                    "single_create_only_version": True,
                },
            },
        )
        write_json(
            self.aux / "exact-materialization.json",
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": RUN_ID,
                "batch_job_id": "synthetic-job",
                "script_sha256": "f" * 64,
                "freeze_receipt_sha256": sha256(freeze_receipt),
                "expected_kms_key_arn": KMS_ARN,
                "materialization_dir": str(self.artifacts),
                "object_count": len(freeze_rows),
                "passed_count": len(freeze_rows),
                "objects": [
                    {
                        "relative_key": row["relative_key"],
                        "bucket": row["destination"]["bucket"],
                        "key": row["destination"]["key"],
                        "bytes": row["destination"]["bytes"],
                        "version_id": row["destination"]["version_id"],
                        "checksums": row["destination"]["checksums"],
                        "checksum_type": "FULL_OBJECT",
                        "server_side_encryption": "aws:kms",
                        "kms_key_id": KMS_ARN,
                        "sha256": sha256(self.artifacts / row["relative_key"]),
                        "checks": {
                            "version_id": True,
                            "content_length": True,
                            "local_bytes": True,
                            "checksums": True,
                            "checksum_type": True,
                            "sse": True,
                            "kms": True,
                        },
                    }
                    for row in freeze_rows
                ],
            },
        )
        freeze_by_relative = {row["relative_key"]: row for row in freeze_rows}

        def final_source(relative: str) -> dict[str, Any]:
            freeze_row = freeze_by_relative[relative]
            return {
                "version_id": freeze_row["destination"]["version_id"],
                "bytes": freeze_row["destination"]["bytes"],
                "etag": "synthetic",
                "checksums": freeze_row["destination"]["checksums"],
                "sha256": sha256(self.artifacts / relative),
                "expected_sha256": None,
                "kms_key_arn": KMS_ARN,
            }

        def reference_source(
            artifact: str, digest: str, version_id: str
        ) -> dict[str, Any]:
            return {
                "version_id": version_id,
                "bytes": 100,
                "etag": "synthetic-reference",
                "checksums": {
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": base64.b64encode(
                        bytes.fromhex(digest)
                    ).decode("ascii")
                },
                "sha256": digest,
                "expected_sha256": digest,
                "kms_key_arn": KMS_ARN,
                "artifact": artifact,
            }

        final_prefix = (
            f"s3://diana-omics-private-results-test/runs/subject01/{RUN_ID}/"
            "deterministic/final/"
        )
        staged_path = self.aux / "staged-input-validation.json"
        output_digests = {
            "somatic.pass.vcf.gz": "1" * 64,
            "somatic.pass.vcf.gz.tbi": "2" * 64,
            "sbs96.csv": "3" * 64,
            "staged_input_validation.json": sha256(staged_path),
        }
        outputs = {
            name: {
                "uri": final_prefix + name,
                "version_id": f"canonical-version-{index}",
                "bytes": (
                    staged_path.stat().st_size
                    if name == "staged_input_validation.json"
                    else 100 + index
                ),
                "etag": "synthetic-output",
                "checksums": {
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": base64.b64encode(
                        bytes.fromhex(digest)
                    ).decode("ascii")
                },
                "sha256": digest,
                "kms_key_arn": KMS_ARN,
                "checks": dict(REPORT_MODULE.EXPECTED_CROSSCHECK_OUTPUT_CHECKS),
            }
            for index, (name, digest) in enumerate(output_digests.items(), 1)
        }
        destination_inventory = [
            {
                "filename": name,
                "key": outputs[name]["uri"].split(
                    "s3://diana-omics-private-results-test/",
                    1,
                )[1],
                "version_id": outputs[name]["version_id"],
                "bytes": outputs[name]["bytes"],
                "sha256": outputs[name]["sha256"],
                "checksums": outputs[name]["checksums"],
            }
            for name in outputs
        ]
        source_vcf = "variants/diana.wgs.mutect2.filtered.vcf.gz"
        source_vcf_index = source_vcf + ".tbi"
        source_matrix = "signatures/wgs_sbs96_matrix.csv"
        write_json(
            self.aux / "crosscheck-materialization.json",
            {
                "schema_version": 2,
                "status": "passed",
                "generated_at_utc": "2026-07-17T00:00:01+00:00",
                "run_alias": "subject01",
                "script_sha256": "f" * 64,
                "destination_prefix": final_prefix,
                "destination_bucket_versioning": "Enabled",
                "destination_initial_version_history_count": 0,
                "receipt_anchor_strategy": "sha256_content_addressed_create_only",
                "source_custody": {
                    "vcf": final_source(source_vcf),
                    "vcf_index": final_source(source_vcf_index),
                    "matrix": final_source(source_matrix),
                    "fasta": reference_source(
                        "reference.fa",
                        reference_fasta_sha256,
                        "reference-fasta-version",
                    ),
                    "fai": reference_source(
                        "reference.fa.fai",
                        reference_fai_sha256,
                        "reference-fai-version",
                    ),
                },
                "validation": {
                    "status": "passed",
                    "run_alias": "subject01",
                    "source_sample_names_retained": False,
                    "pass_snv_records": 1,
                    "pass_snv_alleles": 1,
                    "sbs96_contexts": 96,
                    "sbs96_burden": 1,
                    "matrix_matches_independent_pass_vcf_derivation": True,
                },
                "input_sha256": {
                    "filtered_vcf": sha256(self.artifacts / source_vcf),
                    "filtered_vcf_index": sha256(
                        self.artifacts / source_vcf_index
                    ),
                    "source_sbs96_matrix": sha256(
                        self.artifacts / source_matrix
                    ),
                    "reference_fasta": reference_fasta_sha256,
                    "reference_fai": reference_fai_sha256,
                },
                "outputs": outputs,
                "destination_inventory": destination_inventory,
                "checks": {
                    "all_sources_exact_version_and_sha256": True,
                    "alias_only_pass_snv_vcf": True,
                    "sbs96_matches_independent_pass_vcf_derivation": True,
                    "destination_prefix_initially_empty": True,
                    "all_outputs_create_only": True,
                    "destination_exact_single_version_history": True,
                },
                "classification_authorization": "none",
                "authorized_hrd_state": "no_call",
            },
        )
        write_json(
            self.aux / "input-contract.json",
            {
                "schema_version": 1,
                "run_alias": "subject01",
                "routes": ["sigprofiler_sbs3", "sequenza_scarhrd"],
                "method_parameters": {"sequenza": {"female": True}},
                "artifacts": {
                    "somatic_vcf": {
                        "sha256": outputs["somatic.pass.vcf.gz"]["sha256"],
                        "version_id": outputs["somatic.pass.vcf.gz"]["version_id"],
                    },
                    "somatic_vcf_index": {
                        "sha256": outputs["somatic.pass.vcf.gz.tbi"]["sha256"],
                        "version_id": outputs["somatic.pass.vcf.gz.tbi"]["version_id"],
                    },
                    "sbs96_matrix": {
                        "sha256": outputs["sbs96.csv"]["sha256"],
                        "version_id": outputs["sbs96.csv"]["version_id"],
                        "derived_from_final_pass_vcf": True,
                    },
                    "tumor_bam": {"sha256": "7" * 64, "version_id": "tumor-bam-version"},
                    "tumor_bai": {"sha256": "8" * 64, "version_id": "tumor-bai-version"},
                    "normal_bam": {"sha256": "9" * 64, "version_id": "normal-bam-version"},
                    "normal_bai": {"sha256": "a" * 64, "version_id": "normal-bai-version"},
                },
            },
        )
        crosscheck_receipt = self.aux / "crosscheck-materialization.json"
        crosscheck_receipt_sha = sha256(crosscheck_receipt)
        crosscheck_receipt_uri = (
            f"s3://diana-omics-private-results-test/runs/subject01/{RUN_ID}/"
            "deterministic/provenance/crosscheck-materialization-receipts/"
            f"{crosscheck_receipt_sha}.json"
        )
        write_json(
            self.aux / "crosscheck-materialization-anchor.json",
            {
                "schema_version": 1,
                "status": "passed",
                "receipt_sha256": crosscheck_receipt_sha,
                "receipt_bytes": crosscheck_receipt.stat().st_size,
                "receipt_uri": crosscheck_receipt_uri,
                "receipt_version_id": "crosscheck-receipt-version",
                "checks": {
                    "version_exact": True,
                    "bytes_exact": True,
                    "sha256_exact": True,
                    "sha256_checksum_exact": True,
                    "metadata_sha256_exact": True,
                    "exact_kms": True,
                    "single_create_only_version": True,
                },
            },
        )
        anchor_path = self.aux / "crosscheck-materialization-anchor.json"
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        write_json(
            self.aux / "crosscheck-materialization-capture.json",
            {
                "schema_version": 1,
                "status": "passed",
                "scope": "private read-only terminal materializer custody capture",
                "batch": {
                    "status": "SUCCEEDED",
                    "attempt_count": 1,
                    "exit_code": 0,
                    "log_group": "/aws/batch/job",
                    "checks": dict(REPORT_MODULE.EXPECTED_CROSSCHECK_BATCH_CHECKS),
                },
                "cloudwatch": {
                    "event_count": 3,
                    "messages_sha256": "1" * 64,
                    "terminal_payload_sha256": "2" * 64,
                    "terminal_json_sha256": "3" * 64,
                    "receipt_anchor": anchor,
                    "receipt_upload": {
                        "uri": crosscheck_receipt_uri,
                        "version_id": "crosscheck-receipt-version",
                        "sha256": crosscheck_receipt_sha,
                        "bytes": crosscheck_receipt.stat().st_size,
                        "kms_key_arn": KMS_ARN,
                    },
                },
                "receipt": {
                    "uri": crosscheck_receipt_uri,
                    "version_id": "crosscheck-receipt-version",
                    "sha256": crosscheck_receipt_sha,
                    "bytes": crosscheck_receipt.stat().st_size,
                    "local_sha256": crosscheck_receipt_sha,
                    "local_bytes": crosscheck_receipt.stat().st_size,
                    "kms_key_arn": KMS_ARN,
                    "history": [
                        {
                            "Key": (
                                f"runs/subject01/{RUN_ID}/deterministic/"
                                "provenance/crosscheck-materialization-receipts/"
                                f"{crosscheck_receipt_sha}.json"
                            ),
                            "VersionId": "crosscheck-receipt-version",
                            "IsLatest": True,
                            "history_kind": "version",
                        }
                    ],
                    "checks": dict(
                        REPORT_MODULE.EXPECTED_CROSSCHECK_RECEIPT_DOWNLOAD_CHECKS
                    ),
                },
                "local_anchor": {
                    "sha256": sha256(anchor_path),
                    "bytes": anchor_path.stat().st_size,
                },
                "classification_authorization": "none",
                "authorized_hrd_state": "no_call",
                "checks": dict(REPORT_MODULE.EXPECTED_CROSSCHECK_CAPTURE_CHECKS),
            },
        )
        staged_output = outputs["staged_input_validation.json"]
        write_json(
            self.aux / "staged-input-validation-download.json",
            {
                "schema_version": 1,
                "status": "passed",
                "materializer_receipt_sha256": crosscheck_receipt_sha,
                "expected_kms_key_arn": KMS_ARN,
                "checks": {
                    "version_exact": True,
                    "bytes_exact": True,
                    "sha256_exact": True,
                    "get_checksum_present": True,
                    "head_checksum_present": True,
                    "full_object_sha256_exact": True,
                    "exact_kms": True,
                },
                "object": {
                    "uri": staged_output["uri"],
                    "version_id": staged_output["version_id"],
                    "expected_sha256": staged_output["sha256"],
                    "expected_bytes": staged_output["bytes"],
                    "sha256": staged_output["sha256"],
                    "bytes": staged_output["bytes"],
                },
            },
        )

    def command(self) -> list[str]:
        return [
            sys.executable,
            str(GENERATOR),
            "--artifact-root", str(self.artifacts),
            "--preflight-json", str(self.aux / "preflight.json"),
            "--gather-json", str(self.aux / "gather.json"),
            "--sha-audit", str(self.aux / "sha-audit.json"),
            "--execution-json", str(self.aux / "execution.json"),
            "--executed-worker-freeze-receipt", str(self.aux / "executed-worker-freeze.json"),
            "--executed-worker-freeze-receipt-upload", str(self.aux / "executed-worker-freeze-upload.json"),
            "--final-freeze-receipt", str(self.aux / "final-freeze.json"),
            "--final-freeze-anchor", str(self.aux / "final-freeze-anchor.json"),
            "--exact-materialization-receipt", str(self.aux / "exact-materialization.json"),
            "--crosscheck-materialization-receipt", str(self.aux / "crosscheck-materialization.json"),
            "--input-contract", str(self.aux / "input-contract.json"),
            "--crosscheck-materialization-capture", str(self.aux / "crosscheck-materialization-capture.json"),
            "--crosscheck-materialization-anchor", str(self.aux / "crosscheck-materialization-anchor.json"),
            "--stage-provenance-receipt", str(self.aux / "stage-provenance.json"),
            "--stage-provenance-anchor", str(self.aux / "stage-provenance-anchor.json"),
            "--staged-input-validation-json", str(self.aux / "staged-input-validation.json"),
            "--staged-input-validation-download-receipt", str(self.aux / "staged-input-validation-download.json"),
            "--expected-kms-key-arn", KMS_ARN,
            "--early-look-root", str(self.early),
            "--output-dir", str(self.output),
        ]


def mutate_variant_json_count(
    fixture: SyntheticFixture,
    field: str,
    value: Any,
) -> None:
    def mutate_variants(variants: dict[str, Any]) -> None:
        variants[field] = value

    StageDeterministicWgsReportInstallTests._mutate_json(
        fixture.artifacts / "variants/mutect2_summary.json",
        mutate_variants,
    )
    StageDeterministicWgsReportInstallTests._mutate_json(
        fixture.artifacts / "diana_hrd_summary.json",
        lambda summary: mutate_variants(summary["variants"]),
    )


def mutate_signature_json_count(
    fixture: SyntheticFixture,
    field: str,
    value: Any,
) -> None:
    def mutate_signatures(signatures: dict[str, Any]) -> None:
        signatures[field] = value

    StageDeterministicWgsReportInstallTests._mutate_json(
        fixture.artifacts / "signatures/signature_assignment_summary.json",
        mutate_signatures,
    )
    StageDeterministicWgsReportInstallTests._mutate_json(
        fixture.artifacts / "diana_hrd_summary.json",
        lambda summary: mutate_signatures(summary["signatures"]),
    )


def mutate_staged_sbs96_json_count(
    fixture: SyntheticFixture,
    field: str,
    value: Any,
) -> None:
    def mutate_staged_sbs96(validation: dict[str, Any]) -> None:
        validation["checks"]["sbs96_equivalence"][field] = value

    StageDeterministicWgsReportInstallTests._mutate_json(
        fixture.aux / "staged-input-validation.json",
        mutate_staged_sbs96,
    )


def mutate_coverage_cnv_json_count(
    fixture: SyntheticFixture,
    field: str,
    value: Any,
) -> None:
    def mutate_coverage_cnv(cnv: dict[str, Any]) -> None:
        cnv[field] = value

    StageDeterministicWgsReportInstallTests._mutate_json(
        fixture.artifacts / "cnv/coverage_cnv_summary.json",
        mutate_coverage_cnv,
    )
    StageDeterministicWgsReportInstallTests._mutate_json(
        fixture.artifacts / "diana_hrd_summary.json",
        lambda summary: mutate_coverage_cnv(summary["coverage_cnv"]),
    )


def mutate_sv_json_count(
    fixture: SyntheticFixture,
    role: str,
    field: str,
    value: Any,
) -> None:
    def mutate_sv(sv: dict[str, Any]) -> None:
        for row in sv["rows"]:
            if row["role"] == role:
                row[field] = value

    StageDeterministicWgsReportInstallTests._mutate_json(
        fixture.artifacts / "sv/sv_evidence_summary.json",
        mutate_sv,
    )
    StageDeterministicWgsReportInstallTests._mutate_json(
        fixture.artifacts / "diana_hrd_summary.json",
        lambda summary: mutate_sv(summary["sv"]),
    )


def mutate_early_look_json_count(
    fixture: SyntheticFixture,
    section: str,
    field: str,
    value: Any,
) -> None:
    def mutate_early(early: dict[str, Any]) -> None:
        early[section][field] = value

    StageDeterministicWgsReportInstallTests._mutate_json(
        fixture.early / "early_look_summary.json",
        mutate_early,
    )


def mutate_early_look_bam_qc_count(
    fixture: SyntheticFixture,
    role: str,
    value: Any,
) -> None:
    def mutate_early(early: dict[str, Any]) -> None:
        early["bam_qc"][role]["total_reads"] = value

    StageDeterministicWgsReportInstallTests._mutate_json(
        fixture.early / "early_look_summary.json",
        mutate_early,
    )


@unittest.skipUnless(shutil.which("bcftools"), "bcftools is required for the indexed-VCF E2E fixture")
class StageDeterministicWgsReportTests(unittest.TestCase):
    def test_packet_file_install_is_create_only_and_fsynced(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-input-snapshot-") as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")

            with patch.object(
                REPORT_MODULE.os,
                "fsync",
                wraps=REPORT_MODULE.os.fsync,
            ) as fsync:
                REPORT_MODULE.copy_create_only(source, destination)

            self.assertEqual(destination.read_bytes(), b"one\n")
            self.assertEqual(fsync.call_count, 2)

            source.write_bytes(b"two\n")
            with self.assertRaisesRegex(
                ValueError,
                "report output packet already exists",
            ):
                REPORT_MODULE.copy_create_only(source, destination)

            self.assertEqual(destination.read_bytes(), b"one\n")

    def test_stable_snapshot_is_independent_of_later_source_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-input-snapshot-") as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            early = root / "early"
            auxiliary = root / "auxiliary.json"
            (artifacts / "nested").mkdir(parents=True)
            early.mkdir()
            source_artifact = artifacts / "nested/result.json"
            source_early = early / "summary.json"
            source_artifact.write_text('{"value":1}\n', encoding="utf-8")
            source_early.write_text('{"value":2}\n', encoding="utf-8")
            auxiliary.write_text('{"value":3}\n', encoding="utf-8")
            snapshot = REPORT_MODULE.create_stable_input_snapshot(
                artifacts,
                early,
                {"auxiliary": auxiliary},
                root / "snapshot",
            )
            frozen_artifact = snapshot["artifact_root"] / "nested/result.json"
            frozen_hash = sha256(frozen_artifact)
            source_artifact.write_text('{"value":99}\n', encoding="utf-8")
            auxiliary.write_text('{"value":99}\n', encoding="utf-8")
            self.assertEqual(sha256(frozen_artifact), frozen_hash)
            self.assertEqual(snapshot["manifest"]["status"], "passed")
            self.assertEqual(snapshot["manifest"]["file_count"], 3)

    def test_stable_snapshot_rejects_concurrent_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-input-snapshot-") as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            early = root / "early"
            auxiliary = root / "auxiliary.json"
            artifacts.mkdir()
            early.mkdir()
            target = artifacts / "result.json"
            target.write_text('{"value":1}\n', encoding="utf-8")
            (early / "summary.json").write_text('{"value":2}\n', encoding="utf-8")
            auxiliary.write_text('{"value":3}\n', encoding="utf-8")
            original_copy = REPORT_MODULE.copy_baseline_file
            changed = False

            def mutate_after_copy(
                source: Path,
                destination: Path,
                identity: tuple[int, int, int, int, int, int],
            ) -> None:
                nonlocal changed
                original_copy(source, destination, identity)
                if not changed and source.resolve() == target.resolve():
                    changed = True
                    source.write_text('{"value":99}\n', encoding="utf-8")

            with patch.object(
                REPORT_MODULE,
                "copy_baseline_file",
                side_effect=mutate_after_copy,
            ), self.assertRaisesRegex(
                ValueError, "file changed during stable snapshot"
            ):
                REPORT_MODULE.create_stable_input_snapshot(
                    artifacts,
                    early,
                    {"auxiliary": auxiliary},
                    root / "snapshot",
                )

    def test_deidentified_worker_schema_fixture_generates_no_call_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                {path.name for path in fixture.output.iterdir()},
                {
                    "crosscheck_input_plans.json",
                    "report.md",
                    "readiness.csv",
                    "evidence_checks.json",
                    "input_sha256.csv",
                    "report_manifest.json",
                },
            )
            report = (fixture.output / "report.md").read_text(encoding="utf-8")
            self.assertIn("Overall HRD status: `no_call`", report)
            self.assertIn("its 1 total targeted PASS record", report)
            self.assertNotIn("subject01", report)
            self.assertNotIn("Synthetic WGS", report)
            checks = json.loads((fixture.output / "evidence_checks.json").read_text(encoding="utf-8"))
            self.assertEqual(checks["status"], "passed")
            self.assertEqual(checks["overall_hrd_status"], "no_call")
            self.assertTrue(all(row["status"] == "passed" for row in checks["checks"]))
            self.assertIn("alignment_metric_bounds", {row["check_id"] for row in checks["checks"]})
            self.assertIn("final_artifact_freeze", {row["check_id"] for row in checks["checks"]})
            self.assertIn("exact_version_materialization", {row["check_id"] for row in checks["checks"]})
            self.assertIn("crosscheck_materialization_custody", {row["check_id"] for row in checks["checks"]})
            self.assertIn("crosscheck_terminal_custody", {row["check_id"] for row in checks["checks"]})
            self.assertIn("stable_input_snapshot", {row["check_id"] for row in checks["checks"]})
            self.assertIn("stage_provenance_custody", {row["check_id"] for row in checks["checks"]})
            self.assertEqual(checks["crosscheck_terminal"]["status"], "passed")
            self.assertEqual(checks["stage_provenance"]["status"], "passed")
            self.assertEqual(checks["input_snapshot"]["strategy"], "open_no_follow_fstat_copy_global_restat")
            crosscheck_input_plans = json.loads(
                (fixture.output / "crosscheck_input_plans.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(crosscheck_input_plans["status"], "contract_ready")
            self.assertFalse(crosscheck_input_plans["classification_authorized"])
            self.assertEqual(
                set(crosscheck_input_plans["routes"]),
                {"sequenza_scarhrd", "sigprofiler_sbs3"},
            )
            self.assertEqual(
                crosscheck_input_plans["routes"]["sigprofiler_sbs3"][
                    "source_artifacts"
                ]["somatic_vcf"]["path"],
                "somatic.pass.vcf.gz",
            )
            self.assertEqual(
                crosscheck_input_plans["routes"]["sequenza_scarhrd"]["status"],
                "contract_ready",
            )
            self.assertEqual(
                crosscheck_input_plans["routes"]["sequenza_scarhrd"][
                    "source_sha256"
                ],
                {
                    "tumor_bam": "7" * 64,
                    "tumor_bai": "8" * 64,
                    "normal_bam": "9" * 64,
                    "normal_bai": "a" * 64,
                },
            )
            self.assertNotIn(
                "s3://", json.dumps(crosscheck_input_plans, sort_keys=True)
            )
            with (fixture.output / "input_sha256.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                input_rows = list(csv.DictReader(handle))
            self.assertTrue(input_rows)
            self.assertTrue(
                all(not row["path"].startswith("/") for row in input_rows)
            )
            manifest = json.loads((fixture.output / "report_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["method_id"], "deterministic_full_wgs")
            self.assertEqual(manifest["evidence_status"], "partial_evidence")
            self.assertEqual(manifest["authorized_hrd_state"], "no_call")
            self.assertFalse(manifest["classification_authorized"])
            self.assertEqual(manifest["review_summary"]["sbs96"]["matrix_equivalence"], "passed")
            self.assertEqual(
                set(manifest["support_sha256"]),
                {
                    "crosscheck_input_plans.json",
                    "readiness.csv",
                    "evidence_checks.json",
                    "input_sha256.csv",
                },
            )
            for relative, expected_hash in manifest["support_sha256"].items():
                self.assertEqual(expected_hash, sha256(fixture.output / relative))
            self.assertEqual(manifest["review_summary"]["custody"]["private_freeze_status"], "passed")
            self.assertGreater(manifest["review_summary"]["custody"]["report_consumed_versioned_artifacts"], 0)
            self.assertTrue(
                manifest["review_summary"]["custody"]["exact_materialization_receipt_sha256"]
            )
            self.assertTrue(
                manifest["review_summary"]["custody"]
                ["crosscheck_materialization_receipt_sha256"]
            )
            self.assertTrue(
                manifest["review_summary"]["custody"]
                ["crosscheck_materialization_capture_sha256"]
            )
            self.assertTrue(
                manifest["review_summary"]["custody"]
                ["crosscheck_materialization_anchor_sha256"]
            )
            self.assertTrue(
                manifest["review_summary"]["custody"]
                ["staged_input_validation_download_receipt_sha256"]
            )
            self.assertEqual(
                manifest["review_summary"]["custody"]
                ["stage_provenance_receipt_version_id"],
                "stage-receipt-version",
            )
            self.assertEqual(
                manifest["review_summary"]["custody"]
                ["freeze_receipt_version_id"],
                "final-freeze-receipt-version",
            )
            self.assertTrue(
                manifest["review_summary"]["custody"]
                ["input_snapshot_receipt_sha256"]
            )
            self.assertEqual(manifest["report_sha256"], sha256(fixture.output / "report.md"))
            self.assertTrue(manifest["source_sha256"])
            rows = PUBLISH.validate_packet_dir(
                fixture.output,
                "deterministic_full_wgs",
                ("subject01", "Synthetic WGS"),
            )
            self.assertEqual(
                [row["relative_path"] for row in rows],
                sorted(PUBLISH.METHOD_CONTRACTS["deterministic_full_wgs"]["files"]),
            )
            self.assertFalse(
                any(
                    fixture.root.glob(
                        "deterministic-full-input-snapshot-*"
                    )
                )
            )

    def test_terminal_source_schema_versions_must_be_exact_integers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            materialization = load_json(fixture.aux / "exact-materialization.json")
            materialization["schema_version"] = 1.0
            write_json(fixture.aux / "exact-materialization.json", materialization)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact_version_materialization", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_final_freeze_counts_must_be_exact_integers(self) -> None:
        for field, value in (
            ("object_count", True),
            ("object_count", 3.0),
            ("object_count", "3"),
            ("passed_count", True),
            ("passed_count", 3.0),
            ("passed_count", "3"),
        ):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                receipt = load_json(fixture.aux / "final-freeze.json")
                receipt[field] = value
                write_json(fixture.aux / "final-freeze.json", receipt)

                result = subprocess.run(
                    fixture.command(), text=True, capture_output=True
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "final_artifact_freeze", result.stdout + result.stderr
                )
                self.assertFalse((fixture.output / "report.md").exists())

    def test_exact_materialization_counts_must_be_exact_integers(self) -> None:
        for field, value in (
            ("object_count", True),
            ("object_count", 3.0),
            ("object_count", "3"),
            ("passed_count", True),
            ("passed_count", 3.0),
            ("passed_count", "3"),
        ):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                materialization = load_json(
                    fixture.aux / "exact-materialization.json"
                )
                materialization[field] = value
                write_json(
                    fixture.aux / "exact-materialization.json",
                    materialization,
                )

                result = subprocess.run(
                    fixture.command(), text=True, capture_output=True
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "exact_version_materialization",
                    result.stdout + result.stderr,
                )
                self.assertFalse((fixture.output / "report.md").exists())

    def test_terminal_capture_validators_require_exact_schema_integers(self) -> None:
        cases = (
            (
                "stage provenance receipt",
                lambda fixture: REPORT_MODULE.validate_stage_provenance(
                    {
                        **load_json(fixture.aux / "stage-provenance.json"),
                        "schema_version": 1.0,
                    },
                    load_json(fixture.aux / "stage-provenance-anchor.json"),
                    receipt_path=fixture.aux / "stage-provenance.json",
                    execution_path=fixture.aux / "execution.json",
                    preflight_path=fixture.aux / "preflight.json",
                    gather_path=fixture.aux / "gather.json",
                    run_id=RUN_ID,
                    batch_job_id="synthetic-job",
                    expected_kms_key_arn=KMS_ARN,
                ),
                "receipt_schema_status",
            ),
            (
                "final freeze anchor",
                lambda fixture: REPORT_MODULE.validate_final_freeze_provenance(
                    load_json(fixture.aux / "final-freeze.json"),
                    {
                        **load_json(fixture.aux / "final-freeze-anchor.json"),
                        "schema_version": 1.0,
                    },
                    receipt_path=fixture.aux / "final-freeze.json",
                    execution_path=fixture.aux / "execution.json",
                    run_id=RUN_ID,
                    batch_job_id="synthetic-job",
                    expected_kms_key_arn=KMS_ARN,
                ),
                "anchor_schema_status",
            ),
            (
                "crosscheck terminal capture",
                lambda fixture: REPORT_MODULE.validate_crosscheck_terminal_capture(
                    {
                        **load_json(
                            fixture.aux / "crosscheck-materialization-capture.json"
                        ),
                        "schema_version": 1.0,
                    },
                    load_json(fixture.aux / "crosscheck-materialization-anchor.json"),
                    load_json(fixture.aux / "crosscheck-materialization.json"),
                    load_json(fixture.aux / "staged-input-validation-download.json"),
                    capture_path=fixture.aux / "crosscheck-materialization-capture.json",
                    anchor_path=fixture.aux / "crosscheck-materialization-anchor.json",
                    receipt_path=fixture.aux / "crosscheck-materialization.json",
                    download_path=fixture.aux / "staged-input-validation-download.json",
                    staged_input_validation_path=(
                        fixture.aux / "staged-input-validation.json"
                    ),
                    expected_kms_key_arn=KMS_ARN,
                    run_id=RUN_ID,
                ),
                "capture_schema_status",
            ),
        )
        for label, validate, check_id in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                evidence = validate(SyntheticFixture(Path(temporary)))

                self.assertEqual(evidence["status"], "failed")
                self.assertIs(evidence["checks"][check_id], False)
    def test_forbidden_token_file_findings_fail_before_report_install(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            token_file = fixture.root / "forbidden_tokens.json"
            write_json(token_file, ["Overall HRD status"])
            command = [
                *fixture.command(),
                "--forbidden-tokens-file",
                str(token_file),
            ]

            result = subprocess.run(command, text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "sample/vendor identifier scan failed",
                result.stdout + result.stderr,
            )
            self.assertIn(
                "report.md: Overall HRD status",
                result.stdout + result.stderr,
            )
            self.assertFalse((fixture.output / "report.md").exists())

    def test_variant_count_inconsistency_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary), inconsistent_variant_count=True)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("variant_summary_counts", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_variant_counts_reject_coercible_json_counts(self) -> None:
        mutations = (
            (
                "total filtered records float",
                "total_filtered_records",
                2.0,
                "variant_summary_counts",
            ),
            (
                "pass records string",
                "pass_records",
                "1",
                "variant_summary_counts",
            ),
            (
                "pass snvs bool",
                "pass_snvs",
                True,
                "variant_summary_counts",
            ),
            (
                "pass indels string",
                "pass_indels",
                "0",
                "variant_summary_counts",
            ),
            (
                "brca region records bool",
                "brca1_brca2_pass_region_records",
                True,
                "brca_region_rows",
            ),
        )
        for name, field, value, expected_check in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                mutate_variant_json_count(fixture, field, value)

                result = subprocess.run(
                    fixture.command(),
                    text=True,
                    capture_output=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_check, result.stdout + result.stderr)
                self.assertFalse((fixture.output / "report.md").exists())

    def test_variant_guards_avoid_raw_int_coercion(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        module = ast.parse(source)
        raw_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "variants.get('total_filtered_records'",
                    'variants.get("total_filtered_records"',
                    "variants.get('pass_records'",
                    'variants.get("pass_records"',
                    "variants.get('pass_snvs'",
                    'variants.get("pass_snvs"',
                    "variants.get('pass_indels'",
                    'variants.get("pass_indels"',
                    "variants.get('brca1_brca2_pass_region_records'",
                    'variants.get("brca1_brca2_pass_region_records"',
                )
            )
        ]

        self.assertEqual(raw_coercions, [])

    def test_sbs96_counts_reject_coercible_json_counts(self) -> None:
        mutations = (
            (
                "signature rows float",
                lambda fixture: mutate_signature_json_count(
                    fixture, "sbs96_rows", 96.0
                ),
                "sbs96_matrix",
            ),
            (
                "signature usable alleles string",
                lambda fixture: mutate_signature_json_count(
                    fixture, "usable_snv_records", "1"
                ),
                "sbs96_matrix",
            ),
            (
                "signature usable alleles bool",
                lambda fixture: mutate_signature_json_count(
                    fixture, "usable_snv_records", True
                ),
                "sbs96_matrix",
            ),
            (
                "signature skipped alleles string",
                lambda fixture: mutate_signature_json_count(
                    fixture, "skipped_snv_records", "0"
                ),
                "sbs96_matrix",
            ),
            (
                "signature skipped alleles bool",
                lambda fixture: mutate_signature_json_count(
                    fixture, "skipped_snv_records", False
                ),
                "sbs96_matrix",
            ),
            (
                "staged contexts string",
                lambda fixture: mutate_staged_sbs96_json_count(
                    fixture, "contexts", "96"
                ),
                "independent_vcf_sbs96_validation",
            ),
            (
                "staged usable alleles float",
                lambda fixture: mutate_staged_sbs96_json_count(
                    fixture, "usable_pass_snv_alleles", 1.0
                ),
                "independent_vcf_sbs96_validation",
            ),
            (
                "staged matrix burden bool",
                lambda fixture: mutate_staged_sbs96_json_count(
                    fixture, "matrix_burden", True
                ),
                "independent_vcf_sbs96_validation",
            ),
        )
        for name, mutate, expected_check in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                mutate(fixture)

                result = subprocess.run(
                    fixture.command(),
                    text=True,
                    capture_output=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_check, result.stdout + result.stderr)
                self.assertFalse((fixture.output / "report.md").exists())

    def test_sbs96_guards_avoid_raw_int_coercion(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        module = ast.parse(source)
        raw_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "signatures.get('sbs96_rows'",
                    'signatures.get("sbs96_rows"',
                    "signatures.get('usable_snv_records'",
                    'signatures.get("usable_snv_records"',
                    "signatures.get('skipped_snv_records'",
                    'signatures.get("skipped_snv_records"',
                    "signatures['skipped_snv_records'",
                    'signatures["skipped_snv_records"',
                    "staged_sbs96.get('contexts'",
                    'staged_sbs96.get("contexts"',
                    "staged_sbs96.get('usable_pass_snv_alleles'",
                    'staged_sbs96.get("usable_pass_snv_alleles"',
                    "staged_sbs96.get('matrix_burden'",
                    'staged_sbs96.get("matrix_burden"',
                )
            )
        ]

        self.assertEqual(raw_coercions, [])

    def test_coverage_cnv_counts_reject_coercible_json_counts(self) -> None:
        mutations = (
            ("bin count float", "bin_count", 3.0),
            ("bin count string", "bin_count", "3"),
            ("gain bins string", "relative_gain_bins", "1"),
            ("loss bins bool", "relative_loss_bins", True),
        )
        for name, field, value in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                mutate_coverage_cnv_json_count(fixture, field, value)

                result = subprocess.run(
                    fixture.command(),
                    text=True,
                    capture_output=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("coverage_cnv", result.stdout + result.stderr)
                self.assertFalse((fixture.output / "report.md").exists())

    def test_coverage_cnv_guards_avoid_raw_int_coercion(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        module = ast.parse(source)

        def coerces_coverage_cnv_field(node: ast.Call) -> bool:
            argument = node.args[0]
            if (
                isinstance(argument, ast.Call)
                and isinstance(argument.func, ast.Attribute)
                and argument.func.attr == "get"
                and isinstance(argument.func.value, ast.Name)
                and argument.func.value.id == "cnv"
                and argument.args
                and isinstance(argument.args[0], ast.Constant)
            ):
                return argument.args[0].value in {
                    "bin_count",
                    "relative_gain_bins",
                    "relative_loss_bins",
                }
            if (
                isinstance(argument, ast.Subscript)
                and isinstance(argument.value, ast.Name)
                and argument.value.id == "cnv"
                and isinstance(argument.slice, ast.Constant)
            ):
                return argument.slice.value in {
                    "bin_count",
                    "relative_gain_bins",
                    "relative_loss_bins",
                }
            return False

        raw_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and coerces_coverage_cnv_field(node)
        ]

        self.assertEqual(raw_coercions, [])

    def test_sv_counts_reject_coercible_json_counts(self) -> None:
        mutations = (
            ("tumor total alignments string", "tumor", "total_alignments", "100"),
            (
                "tumor supplementary alignments string",
                "tumor",
                "supplementary_alignments",
                "2",
            ),
            (
                "tumor discordant pairs string",
                "tumor",
                "discordant_mapped_pairs",
                "3",
            ),
            (
                "tumor interchromosomal pairs string",
                "tumor",
                "interchromosomal_pairs",
                "1",
            ),
            (
                "normal large insert pairs string",
                "normal",
                "large_insert_pairs",
                "0",
            ),
        )
        for name, role, field, value in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                mutate_sv_json_count(fixture, role, field, value)

                result = subprocess.run(
                    fixture.command(),
                    text=True,
                    capture_output=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("sv_evidence", result.stdout + result.stderr)
                self.assertFalse((fixture.output / "report.md").exists())

    def test_sv_guards_avoid_raw_int_coercion(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        module = ast.parse(source)
        raw_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "json_row.get('total_alignments'",
                    'json_row.get("total_alignments"',
                    "sv_json_by_role[role]['supplementary_alignments'",
                    'sv_json_by_role[role]["supplementary_alignments"',
                    "sv_json_by_role[role]['discordant_mapped_pairs'",
                    'sv_json_by_role[role]["discordant_mapped_pairs"',
                    "sv_json_by_role[role]['interchromosomal_pairs'",
                    'sv_json_by_role[role]["interchromosomal_pairs"',
                    "sv_json_by_role[role]['large_insert_pairs'",
                    'sv_json_by_role[role]["large_insert_pairs"',
                )
            )
        ]

        self.assertEqual(raw_coercions, [])

    def test_early_baseline_counts_reject_coercible_json_counts(self) -> None:
        mutations = (
            ("HRR pass records string", "core_hrr_variants", "pass_records", "1"),
            (
                "BRCA pass records bool",
                "core_hrr_variants",
                "brca1_brca2_pass_records",
                False,
            ),
            ("coverage bins float", "coverage_cnv", "bin_count", 1.0),
            ("coverage gain bins string", "coverage_cnv", "relative_gain_bins", "0"),
            ("coverage loss bins bool", "coverage_cnv", "relative_loss_bins", False),
        )
        for name, section, field, value in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                mutate_early_look_json_count(fixture, section, field, value)

                result = subprocess.run(
                    fixture.command(),
                    text=True,
                    capture_output=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "early_baseline_boundary",
                    result.stdout + result.stderr,
                )
                self.assertFalse((fixture.output / "report.md").exists())

    def test_early_baseline_guards_avoid_raw_int_coercion(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        module = ast.parse(source)
        raw_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "early.get('core_hrr_variants'",
                    'early.get("core_hrr_variants"',
                    "early_variants.get('pass_records'",
                    'early_variants.get("pass_records"',
                    "early_variants.get('brca1_brca2_pass_records'",
                    'early_variants.get("brca1_brca2_pass_records"',
                    "early_cnv.get('bin_count'",
                    'early_cnv.get("bin_count"',
                    "early_cnv.get('relative_gain_bins'",
                    'early_cnv.get("relative_gain_bins"',
                    "early_cnv.get('relative_loss_bins'",
                    'early_cnv.get("relative_loss_bins"',
                    "early_cnv['bin_count'",
                    'early_cnv["bin_count"',
                    "early_cnv['relative_gain_bins'",
                    'early_cnv["relative_gain_bins"',
                    "early_cnv['relative_loss_bins'",
                    'early_cnv["relative_loss_bins"',
                )
            )
        ]

        self.assertEqual(raw_coercions, [])

    def test_early_bam_qc_counts_reject_coercible_json_counts(self) -> None:
        mutations = (
            ("tumor total reads string", "tumor", "10"),
            ("normal total reads float", "normal", 12.0),
            ("tumor total reads bool", "tumor", True),
        )
        for name, role, value in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                fixture = SyntheticFixture(Path(temporary))
                mutate_early_look_bam_qc_count(fixture, role, value)

                result = subprocess.run(
                    fixture.command(),
                    text=True,
                    capture_output=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "early_baseline_boundary",
                    result.stdout + result.stderr,
                )
                self.assertFalse((fixture.output / "report.md").exists())

    def test_early_bam_qc_guards_avoid_raw_int_coercion(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        module = ast.parse(source)
        raw_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "early['bam_qc'",
                    'early["bam_qc"',
                    "early_bam_qc.get('tumor'",
                    'early_bam_qc.get("tumor"',
                    "early_bam_qc.get('normal'",
                    'early_bam_qc.get("normal"',
                    "early_tumor_bam_qc.get('total_reads'",
                    'early_tumor_bam_qc.get("total_reads"',
                    "early_normal_bam_qc.get('total_reads'",
                    'early_normal_bam_qc.get("total_reads"',
                    "early_tumor_total_reads",
                    "early_normal_total_reads",
                )
            )
        ]

        self.assertEqual(raw_coercions, [])

    def test_existing_packet_files_fail_create_only_and_remain_unchanged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            first = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            original_hashes = {
                path.name: sha256(path)
                for path in fixture.output.iterdir()
                if path.is_file()
            }
            summary_path = fixture.artifacts / "diana_hrd_summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["overall_hrd_status"] = "unexpected"
            write_json(summary_path, summary)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "report output already contains packet files",
                result.stdout + result.stderr,
            )
            self.assertEqual(
                {
                    path.name: sha256(path)
                    for path in fixture.output.iterdir()
                    if path.is_file()
                },
                original_hashes,
            )

    def test_preexisting_report_fails_create_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            fixture.output.mkdir()
            stale_report = fixture.output / "report.md"
            stale_report.write_text("stale report\n", encoding="utf-8")

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "report output already contains packet files: report.md",
                result.stdout + result.stderr,
            )
            self.assertEqual(stale_report.read_text(encoding="utf-8"), "stale report\n")

    def test_stale_extra_output_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            fixture.output.mkdir()
            (fixture.output / "unexpected.txt").write_text("stale\n", encoding="utf-8")

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "report output contains unexpected existing files",
                result.stdout + result.stderr,
            )
            self.assertEqual(
                sorted(path.name for path in fixture.output.iterdir()),
                ["unexpected.txt"],
            )

    def test_symlinked_output_parent_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            root = Path(temporary)
            fixture = SyntheticFixture(root / "case")
            real_parent = root / "report-parent-real"
            real_parent.mkdir()
            link_parent = root / "report-parent"
            link_parent.symlink_to(real_parent, target_is_directory=True)
            fixture.output = link_parent / "report-output"

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "report output parent may not be a symlink",
                result.stdout + result.stderr,
            )
            self.assertFalse((real_parent / "report-output" / "report.md").exists())

    def test_output_below_symlinked_parent_fails_before_report_publication(self) -> None:
        self.assertFalse(REPORT_MODULE.is_platform_root_alias(Path("report-parent")))

        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory(
                prefix="synthetic-hrd-report-"
            ) as temporary:
                root = Path(temporary)
                fixture = SyntheticFixture(root / "case")
                real_parent = root / "report-parent-real"
                if nested == "existing":
                    (real_parent / nested).mkdir(parents=True)
                else:
                    real_parent.mkdir()
                link_parent = root / "report-parent"
                link_parent.symlink_to(real_parent, target_is_directory=True)
                fixture.output = link_parent / nested / "report-output"

                result = subprocess.run(fixture.command(), text=True, capture_output=True)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "report output parent may not be a symlink",
                    result.stdout + result.stderr,
                )
                self.assertFalse((real_parent / nested / "report-output").exists())

    def test_input_below_symlinked_parent_fails_before_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            root = Path(temporary)
            fixture = SyntheticFixture(root / "case")
            real_parent = root / "real-aux"
            real_parent.mkdir()
            redirected = real_parent / "preflight.json"
            redirected.write_bytes((fixture.aux / "preflight.json").read_bytes())
            linked_parent = root / "linked-aux"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            command = fixture.command()
            command[command.index("--preflight-json") + 1] = str(
                linked_parent / "preflight.json"
            )

            result = subprocess.run(command, text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "external input preflight parent may not be a symlink",
                result.stdout + result.stderr,
            )
            self.assertFalse((fixture.output / "report.md").exists())

    def test_expected_output_name_directory_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            (fixture.output / "report.md").mkdir(parents=True)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "report output contains invalid existing packet paths",
                result.stdout + result.stderr,
            )
            self.assertTrue((fixture.output / "report.md").is_dir())

    def test_missing_effective_job_timeout_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            execution_path = fixture.aux / "execution.json"
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
            execution["batch"]["timeout"] = {}
            write_json(execution_path, execution)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_execution_provenance", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_malformed_sha_audit_row_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            audit_path = fixture.aux / "sha-audit.json"
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["objects"].append("not-a-row")
            audit["object_count"] += 1
            write_json(audit_path, audit)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("intake_sha256", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_missing_frozen_version_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "final-freeze.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["destination"]["version_id"] = ""
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("final_artifact_freeze", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_final_freeze_anchor_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            anchor_path = fixture.aux / "final-freeze-anchor.json"
            anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            anchor["receipt_version_id"] = ""
            write_json(anchor_path, anchor)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("final_artifact_freeze", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_incomplete_final_freeze_row_checks_fail_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "final-freeze.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["checks"].pop("copy_response_version_matches")
            write_json(receipt_path, receipt)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("final_artifact_freeze", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_unexpected_final_freeze_row_check_fails_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "final-freeze.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["checks"]["future_check"] = True
            write_json(receipt_path, receipt)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("final_artifact_freeze", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_failed_final_freeze_row_check_fails_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "final-freeze.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["checks"]["copy_response_version_matches"] = False
            write_json(receipt_path, receipt)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("final_artifact_freeze", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_unexpected_final_freeze_receipt_checks_fail_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "final-freeze.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["checks"]["future_check"] = True
            write_json(receipt_path, receipt)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("final_artifact_freeze", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_unexpected_final_freeze_anchor_checks_fail_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            anchor_path = fixture.aux / "final-freeze-anchor.json"
            anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            anchor["checks"]["future_check"] = True
            write_json(anchor_path, anchor)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("final_artifact_freeze", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_exact_version_materialization_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "exact-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["sha256"] = "0" * 64
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact_version_materialization", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_stale_exact_version_materialization_envelope_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "exact-materialization.json"
            base_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

            for label, mutate in (
                (
                    "missing-script",
                    lambda receipt: receipt.pop("script_sha256"),
                ),
                (
                    "extra-legacy",
                    lambda receipt: receipt.__setitem__("legacy_note", "accepted"),
                ),
                (
                    "missing-row-checks",
                    lambda receipt: receipt["objects"][0].pop("checks"),
                ),
                (
                    "extra-row",
                    lambda receipt: receipt["objects"][0].__setitem__(
                        "legacy_note",
                        "accepted",
                    ),
                ),
            ):
                with self.subTest(label=label):
                    receipt = json.loads(json.dumps(base_receipt))
                    mutate(receipt)
                    write_json(receipt_path, receipt)

                    result = subprocess.run(
                        fixture.command(), text=True, capture_output=True
                    )

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        "exact_version_materialization",
                        result.stdout + result.stderr,
                    )
                    self.assertFalse((fixture.output / "report.md").exists())

    def test_missing_exact_version_materialization_check_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "exact-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["checks"].pop("checksum_type")
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact_version_materialization", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_unexpected_exact_version_materialization_check_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "exact-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["checks"]["future_check"] = True
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact_version_materialization", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_failed_exact_version_materialization_check_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "exact-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["checks"]["checksum_type"] = False
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact_version_materialization", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_unconsumed_frozen_artifact_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "exact-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            extra = next(
                row
                for row in receipt["objects"]
                if row["relative_key"] == "logs/worker-extra.log"
            )
            extra["sha256"] = "0" * 64
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact_version_materialization", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_crosscheck_source_version_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["source_custody"]["vcf"]["version_id"] = "wrong-version"
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_materialization_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_crosscheck_source_sha_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["source_custody"]["matrix"]["sha256"] = "0" * 64
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_materialization_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_staged_output_hash_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["outputs"]["staged_input_validation.json"]["sha256"] = "0" * 64
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_materialization_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_crosscheck_output_checksum_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["outputs"]["sbs96.csv"]["checksums"]["ChecksumSHA256"] = (
                base64.b64encode(bytes.fromhex("0" * 64)).decode("ascii")
            )
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "crosscheck_materialization_custody", result.stdout + result.stderr
            )
            self.assertFalse((fixture.output / "report.md").exists())

    def test_stale_crosscheck_destination_inventory_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["destination_inventory"][0]["key"] = (
                "runs/subject01/stale-run/deterministic/final/sbs96.csv"
            )
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "crosscheck_materialization_custody", result.stdout + result.stderr
            )
            self.assertFalse((fixture.output / "report.md").exists())

    def test_stale_crosscheck_receipt_envelope_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["checks"].pop("destination_exact_single_version_history")
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "crosscheck_materialization_custody", result.stdout + result.stderr
            )
            self.assertFalse((fixture.output / "report.md").exists())

    def test_missing_crosscheck_output_check_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["outputs"]["sbs96.csv"]["checks"].pop(
                "single_version_history"
            )
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "crosscheck_materialization_custody", result.stdout + result.stderr
            )
            self.assertFalse((fixture.output / "report.md").exists())

    def test_unexpected_crosscheck_output_check_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["outputs"]["sbs96.csv"]["checks"]["future_check"] = True
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "crosscheck_materialization_custody", result.stdout + result.stderr
            )
            self.assertFalse((fixture.output / "report.md").exists())

    def test_failed_crosscheck_output_check_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["outputs"]["sbs96.csv"]["checks"]["version_exact"] = False
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "crosscheck_materialization_custody", result.stdout + result.stderr
            )
            self.assertFalse((fixture.output / "report.md").exists())

    def test_stale_staged_download_checksum_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "staged-input-validation-download.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["checks"] = {
                "version_exact": True,
                "bytes_exact": True,
                "sha256_exact": True,
                "get_checksum_present": True,
                "head_checksum_present": True,
                "receipt_checksum_observed": True,
                "exact_kms": True,
            }
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_terminal_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_canonical_output_kms_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["outputs"]["sbs96.csv"]["kms_key_arn"] = (
                "arn:aws:kms:us-east-1:000000000000:key/wrong"
            )
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_materialization_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_missing_executable_route_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            contract_path = fixture.aux / "input-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["routes"] = ["sigprofiler_sbs3"]
            write_json(contract_path, contract)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "input contract is missing executable cross-check routes: "
                "sequenza_scarhrd",
                result.stdout + result.stderr,
            )
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_terminal_anchor_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            anchor_path = fixture.aux / "crosscheck-materialization-anchor.json"
            anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            anchor["receipt_sha256"] = "0" * 64
            write_json(anchor_path, anchor)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_terminal_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_incomplete_terminal_capture_checks_fail_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            capture_path = fixture.aux / "crosscheck-materialization-capture.json"
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            capture["checks"].pop("single_terminal_anchor")
            write_json(capture_path, capture)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_terminal_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_unexpected_terminal_receipt_download_checks_fail_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            capture_path = fixture.aux / "crosscheck-materialization-capture.json"
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            capture["receipt"]["checks"]["future_check"] = True
            write_json(capture_path, capture)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_terminal_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_stale_terminal_receipt_download_checks_fail_before_report_publication(
        self,
    ) -> None:
        stale_pre_materializer_schema2_checks = {
            "logged_local_sha256_exact": True,
            "logged_local_bytes_exact": True,
            "get_version_exact": True,
            "head_version_exact": True,
            "get_bytes_exact": True,
            "head_bytes_exact": True,
            "get_sha256_checksum_exact": True,
            "head_sha256_checksum_exact": True,
            "get_kms_exact": True,
            "head_kms_exact": True,
            "get_metadata_sha256_exact": True,
            "head_metadata_sha256_exact": True,
            "single_version_no_delete_history": True,
            "receipt_schema_status": True,
            "receipt_script_exact": True,
            "receipt_checks_passed": True,
            "receipt_boundary_no_call": True,
        }
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            capture_path = fixture.aux / "crosscheck-materialization-capture.json"
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            capture["receipt"]["checks"] = stale_pre_materializer_schema2_checks
            write_json(capture_path, capture)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_terminal_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_incomplete_terminal_batch_checks_fail_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            capture_path = fixture.aux / "crosscheck-materialization-capture.json"
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            capture["batch"]["checks"].pop("definition_log_exact")
            write_json(capture_path, capture)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_terminal_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_staged_validation_download_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            download_path = fixture.aux / "staged-input-validation-download.json"
            download = json.loads(download_path.read_text(encoding="utf-8"))
            download["object"]["sha256"] = "0" * 64
            write_json(download_path, download)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_terminal_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_unexpected_staged_validation_download_checks_fail_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            download_path = fixture.aux / "staged-input-validation-download.json"
            download = json.loads(download_path.read_text(encoding="utf-8"))
            download["checks"]["future_check"] = True
            write_json(download_path, download)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_terminal_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_stage_provenance_version_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "stage-provenance.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["destination"]["version_id"] = ""
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stage_provenance_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_stage_anchor_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            anchor_path = fixture.aux / "stage-provenance-anchor.json"
            anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            anchor["receipt_sha256"] = "0" * 64
            write_json(anchor_path, anchor)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stage_provenance_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_incomplete_stage_row_checks_fail_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "stage-provenance.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["checks"].pop("semantic_binding")
            write_json(receipt_path, receipt)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stage_provenance_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_unexpected_stage_anchor_checks_fail_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            anchor_path = fixture.aux / "stage-provenance-anchor.json"
            anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            anchor["checks"]["future_check"] = True
            write_json(anchor_path, anchor)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stage_provenance_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_local_preflight_fails_frozen_stage_binding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            preflight_path = fixture.aux / "preflight.json"
            preflight_path.write_text(
                preflight_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stage_provenance_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_executed_worker_receipt_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "executed-worker-freeze.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["source"]["sha256"] = "0" * 64
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_worker_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_missing_executed_worker_freeze_check_fails_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "executed-worker-freeze.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["checks"].pop("container_file_uploaded_directly")
            write_json(receipt_path, receipt)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_worker_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_unexpected_executed_worker_freeze_check_fails_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "executed-worker-freeze.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["checks"]["future_check"] = True
            write_json(receipt_path, receipt)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_worker_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_failed_executed_worker_freeze_check_fails_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "executed-worker-freeze.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["checks"]["s3_exact_version_present"] = False
            write_json(receipt_path, receipt)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_worker_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_missing_executed_worker_freeze_upload_check_fails_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "executed-worker-freeze-upload.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["checks"].pop("local_sha256_matches_s3_checksum")
            write_json(receipt_path, receipt)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_worker_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_unexpected_executed_worker_freeze_upload_check_fails_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "executed-worker-freeze-upload.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["checks"]["future_check"] = True
            write_json(receipt_path, receipt)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_worker_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_failed_executed_worker_freeze_upload_check_fails_before_report_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "executed-worker-freeze-upload.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["checks"]["exact_version"] = False
            write_json(receipt_path, receipt)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_worker_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_missing_batch_worker_check_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            execution_path = fixture.aux / "execution.json"
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
            execution["worker"]["checks"].pop("live_freeze_command")
            write_json(execution_path, execution)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_worker_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_unexpected_batch_worker_check_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            execution_path = fixture.aux / "execution.json"
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
            execution["worker"]["checks"]["future_check"] = True
            write_json(execution_path, execution)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_worker_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_failed_batch_worker_check_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            execution_path = fixture.aux / "execution.json"
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
            execution["worker"]["checks"]["live_freeze_command"] = False
            write_json(execution_path, execution)

            result = subprocess.run(fixture.command(), text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_worker_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
