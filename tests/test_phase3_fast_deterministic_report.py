from __future__ import annotations

import ast
import csv
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import plan_phase3_fast_crosscheck_inputs as crosscheck_plan
from diana_omics.commands.phase3_wgs import publish_phase3_fast_final_evidence as final_evidence
from diana_omics.commands.phase3_wgs import stage_phase3_fast_deterministic_report as stage_report
from diana_omics.utils import read_json, write_json
from tests.test_phase3_fast_final_evidence import _join_manifest


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _flatten_artifacts(value: dict) -> list[dict]:
    if {"relative_path", "bytes", "sha256"}.issubset(value):
        return [value]
    rows = []
    for child in value.values():
        rows.extend(_flatten_artifacts(child))
    return rows


def _write_final_manifest(root: Path) -> tuple[Path, Path, dict]:
    final_root = root / "final"
    manifest = final_evidence.build_phase3_fast_final_evidence_manifest(
        _join_manifest(root),
        evidence_join_sha256="a" * 64,
        small_variant_artifact_root=root / "small_variant_export",
        bam_qc_artifact_root=root / "bam_qc",
        cnv_evidence_artifact_root=root / "cnv_evidence",
        sv_evidence_artifact_root=root / "sv_evidence",
        output_root=final_root,
    )
    manifest_path = root / "final_evidence_manifest.json"
    write_json(manifest_path, manifest)
    return manifest_path, final_root, manifest


def _crosscheck_materialization_plan(manifest: dict, manifest_path: Path) -> dict:
    return crosscheck_plan.build_phase3_fast_crosscheck_materialization_plan(
        manifest,
        final_evidence_sha256=_sha256_path(manifest_path),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_minimal_staged_report(staging: Path) -> None:
    stage_report._write_staged_text(staging / "report.md", "# Deterministic report\n")
    for name in stage_report.SUPPORT_NAMES:
        stage_report._write_staged_text(staging / name, f"{name}\n")
    stage_report._write_staged_json(
        staging / "report_manifest.json",
        {
            "report_sha256": _sha256_path(staging / "report.md"),
            "support_sha256": {
                name: _sha256_path(staging / name)
                for name in sorted(stage_report.SUPPORT_NAMES)
            },
        },
    )


def _write_one_byte_final_artifact(final_root: Path, artifact_row: dict) -> None:
    path = final_root / artifact_row["relative_path"]
    path.write_bytes(b"1")
    artifact_row["bytes"] = 1
    artifact_row["sha256"] = _sha256_path(path)


class Phase3FastDeterministicReportTests(unittest.TestCase):
    def test_schema_version_checks_use_exact_integer_helper(self) -> None:
        for value, expected, accepted in (
            (1, 1, True),
            (2, 2, True),
            (True, 1, False),
            (1.0, 1, False),
            ("1", 1, False),
            (None, 1, False),
        ):
            with self.subTest(value=value):
                self.assertIs(stage_report._is_exact_int(value, expected), accepted)

    def test_schema_version_checks_avoid_raw_comparisons(self) -> None:
        source = Path(stage_report.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(stage_report.__file__))

        raw_schema_version_comparisons = [
            f"{node.lineno}: {ast.get_source_segment(source, node)}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Compare)
            and "schema_version" in (ast.get_source_segment(source, node) or "")
        ]

        self.assertEqual(raw_schema_version_comparisons, [])

    def test_rejects_non_exact_source_manifest_schemas(self) -> None:
        cases = (
            (
                "final_manifest",
                lambda final_manifest, _plan: final_manifest.update(
                    {"schema_version": 1.0}
                ),
                "final evidence schema_version must be 1",
            ),
            (
                "crosscheck_materialization_plan",
                lambda _final_manifest, plan: plan.update({"schema_version": True}),
                "cross-check materialization plan schema_version must be 1",
            ),
        )
        for label, mutation, error in cases:
            with self.subTest(label=label), TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, final_root, final_manifest = _write_final_manifest(root)
                materialization_plan = _crosscheck_materialization_plan(
                    final_manifest,
                    manifest_path,
                )
                mutation(final_manifest, materialization_plan)
                output = root / "deterministic"

                with self.assertRaisesRegex(stage_report.ManifestError, error):
                    stage_report.stage_phase3_fast_deterministic_report(
                        final_manifest,
                        materialization_plan,
                        final_manifest_sha256=_sha256_path(manifest_path),
                        final_manifest_bytes=manifest_path.stat().st_size,
                        final_root=final_root,
                        output_dir=output,
                    )

                self.assertFalse((output / "report_manifest.json").exists())

    def test_stages_no_compute_deterministic_report_from_final_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            output = root / "deterministic"

            report_manifest = stage_report.stage_phase3_fast_deterministic_report(
                final_manifest,
                _crosscheck_materialization_plan(final_manifest, manifest_path),
                final_manifest_sha256=_sha256_path(manifest_path),
                final_manifest_bytes=manifest_path.stat().st_size,
                final_root=final_root,
                output_dir=output,
            )
            output_names = {path.name for path in output.iterdir()}
            report = (output / "report.md").read_text(encoding="utf-8")
            evidence_checks = read_json(output / "evidence_checks.json")
            input_rows = _read_csv(output / "input_sha256.csv")
            crosscheck_input_plans = read_json(output / "crosscheck_input_plans.json")
            artifact_paths = [
                final_root / row["path"].removeprefix("final/")
                for row in input_rows[1:]
            ]
            artifact_hashes = [_sha256_path(path) for path in artifact_paths]
            artifact_sizes = [path.stat().st_size for path in artifact_paths]
            artifact_exists = [path.is_file() for path in artifact_paths]

        self.assertEqual(stage_report.OUTPUT_NAMES, output_names)
        self.assertEqual("deterministic_full_wgs", report_manifest["method_id"])
        self.assertEqual("phase3_fast_deterministic_evidence", report_manifest["report_kind"])
        self.assertEqual("partial_evidence", report_manifest["evidence_status"])
        self.assertEqual("no_call", report_manifest["authorized_hrd_state"])
        self.assertIs(report_manifest["classification_authorized"], False)
        self.assertIn("overall HRD remains `no_call`", report)
        self.assertIn("SigProfiler/SBS3 route has a plan-ready alias materialization recipe", report)
        self.assertIn("explicit sex-model parameter", report)
        self.assertIn("`4` depth bins", report)
        self.assertIn("no production SV VCF/BEDPE", report)
        self.assertEqual(
            "SigProfiler/SBS3 input materialization is bound to the "
            "post-freeze plan; Sequenza/scarHRD has an explicit sex-model "
            "parameter but remains blocked on a finalized BAM contract and "
            "validated runtime.",
            next(
                check["detail"]
                for check in evidence_checks["checks"]
                if check["check_id"] == "crosscheck_input_materialization_plan"
            ),
        )
        self.assertNotIn(str(root), json.dumps(report_manifest))
        self.assertNotIn(str(root), report)
        self.assertEqual(
            "awaiting_private_results_freeze",
            crosscheck_input_plans["routes"]["sigprofiler_sbs3"]["status"],
        )
        self.assertEqual(
            "copy-version-5",
            crosscheck_input_plans["routes"]["sigprofiler_sbs3"]["reference"]["fasta"]["version_id"],
        )
        self.assertEqual(
            "final/artifacts/small_variants/filter_mutect/filtered_vcf/diana.wgs.mutect2.parabricks.filtered.vcf.gz",
            crosscheck_input_plans["routes"]["sigprofiler_sbs3"]["source_artifacts"]["source_vcf"]["path"],
        )
        self.assertEqual(
            "blocked",
            crosscheck_input_plans["routes"]["sequenza_scarhrd"]["status"],
        )
        self.assertEqual(
            [
                "A finalized alias-only BAM/BAM-index contract has not been published for the Sequenza route.",
                "Sequenza execution, purity/ploidy, and scarHRD interpretation thresholds are not validated.",
            ],
            crosscheck_input_plans["routes"]["sequenza_scarhrd"]["blockers"],
        )
        self.assertEqual(
            {"sequenza": {"female": True}},
            crosscheck_input_plans["routes"]["sequenza_scarhrd"]["method_parameters"],
        )
        self.assertEqual(
            {
                "tumor_sample": "subject01_tumor",
                "normal_sample": "subject01_normal",
            },
            crosscheck_input_plans["routes"]["sequenza_scarhrd"]["alias_input_contract"]["planned_aliases"],
        )
        self.assertEqual(
            "copy-version-7",
            crosscheck_input_plans["routes"]["sequenza_scarhrd"]["alias_input_contract"]["reference"][
                "sequence_dictionary"
            ]["version_id"],
        )
        self.assertEqual(
            "tumor.bam",
            crosscheck_input_plans["routes"]["sequenza_scarhrd"]["alias_input_contract"]["planned_alias_outputs"][
                "tumor_bam"
            ],
        )
        self.assertNotIn(
            "sample_id",
            crosscheck_input_plans["routes"]["sequenza_scarhrd"]["alias_input_contract"]["artifacts"]["tumor_bam"],
        )
        self.assertFalse(
            crosscheck_input_plans["routes"]["sequenza_scarhrd"]["alias_input_contract"]["attestations"][
                "validated_sequenza_scarhrd_runtime"
            ],
        )
        self.assertEqual(
            "awaiting_private_results_freeze",
            report_manifest["review_summary"]["crosscheck_input_plans"]["sigprofiler_sbs3"],
        )

        artifacts = _flatten_artifacts(final_manifest["artifacts"])
        self.assertEqual(final_manifest["artifact_count"] + 1, len(input_rows))
        self.assertEqual("final_evidence_manifest", input_rows[0]["input_id"])
        for row, exists, digest, size in zip(input_rows[1:], artifact_exists, artifact_hashes, artifact_sizes):
            self.assertTrue(exists)
            self.assertEqual(str(size), row["bytes"])
            self.assertEqual(digest, row["sha256"])
        self.assertEqual(
            {"final_evidence_manifest", *(row["input_id"] for row in input_rows[1:])},
            set(report_manifest["source_sha256"]),
        )
        self.assertEqual(len(artifacts), len(input_rows) - 1)

    def test_environment_command_writes_report_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, _ = _write_final_manifest(root)
            plan_path = root / "crosscheck_materialization_plan.json"
            write_json(
                plan_path,
                _crosscheck_materialization_plan(
                    read_json(manifest_path),
                    manifest_path,
                ),
            )
            output = root / "deterministic"

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST": str(manifest_path),
                    "PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN": str(plan_path),
                    "PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT": str(final_root),
                    "PHASE3_WGS_FAST_DETERMINISTIC_REPORT_OUTPUT": str(output),
                },
                clear=False,
            ):
                report_manifest, report_output = stage_report.load_report_from_environment()
                report_kind = read_json(output / "report_manifest.json")["report_kind"]

        self.assertEqual(output, report_output)
        self.assertEqual("deterministic_full_wgs", report_manifest["method_id"])
        self.assertEqual("phase3_fast_deterministic_evidence", report_kind)

    def test_environment_command_rejects_redirected_input_manifests(self) -> None:
        cases = (
            ("PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST", "final_evidence_manifest", "missing"),
            ("PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST", "final_evidence_manifest", "directory"),
            ("PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST", "final_evidence_manifest", "symlink"),
            ("PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN", "crosscheck_materialization_plan", "missing"),
            ("PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN", "crosscheck_materialization_plan", "directory"),
            ("PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN", "crosscheck_materialization_plan", "symlink"),
        )
        for env_key, label, bad_kind in cases:
            with self.subTest(env_key=env_key, bad_kind=bad_kind), TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, final_root, final_manifest = _write_final_manifest(root)
                plan_path = root / "crosscheck_materialization_plan.json"
                write_json(
                    plan_path,
                    _crosscheck_materialization_plan(
                        final_manifest,
                        manifest_path,
                    ),
                )
                bad_path = root / f"{label}-{bad_kind}.json"
                if bad_kind == "directory":
                    bad_path.mkdir()
                elif bad_kind == "symlink":
                    bad_path.symlink_to(manifest_path if env_key == "PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST" else plan_path)

                with patch.dict(
                    "os.environ",
                    {
                        "PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST": str(manifest_path),
                        "PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN": str(plan_path),
                        "PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT": str(final_root),
                        "PHASE3_WGS_FAST_DETERMINISTIC_REPORT_OUTPUT": str(root / "deterministic"),
                        env_key: str(bad_path),
                    },
                    clear=False,
                ):
                    with self.assertRaisesRegex(stage_report.ManifestError, label):
                        stage_report.load_report_from_environment()

    def test_environment_command_rejects_manifest_below_symlinked_parent(self) -> None:
        cases = (
            ("PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST", "final_evidence_manifest"),
            ("PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN", "crosscheck_materialization_plan"),
        )
        for env_key, label in cases:
            with self.subTest(env_key=env_key), TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, final_root, final_manifest = _write_final_manifest(root)
                plan_path = root / "crosscheck_materialization_plan.json"
                write_json(
                    plan_path,
                    _crosscheck_materialization_plan(
                        final_manifest,
                        manifest_path,
                    ),
                )
                linked_parent = root / "linked-inputs"
                real_parent = root / "real-inputs"
                real_parent.mkdir()
                linked_parent.symlink_to(real_parent, target_is_directory=True)
                bad_path = linked_parent / f"{label}.json"
                bad_path.write_bytes(
                    manifest_path.read_bytes()
                    if env_key == "PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST"
                    else plan_path.read_bytes()
                )

                with patch.dict(
                    "os.environ",
                    {
                        "PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST": str(manifest_path),
                        "PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN": str(plan_path),
                        "PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT": str(final_root),
                        "PHASE3_WGS_FAST_DETERMINISTIC_REPORT_OUTPUT": str(root / "deterministic"),
                        env_key: str(bad_path),
                    },
                    clear=False,
                ):
                    with self.assertRaisesRegex(stage_report.ManifestError, f"{label} parent may not be a symlink"):
                        stage_report.load_report_from_environment()

    def test_sha256_path_rejects_symlinked_hash_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_manifest = root / "final-evidence.json"
            write_json(real_manifest, {"status": "partial_evidence"})

            linked_manifest = root / "final-evidence-link.json"
            linked_manifest.symlink_to(real_manifest)

            with self.assertRaisesRegex(
                stage_report.ManifestError,
                "final-evidence-link\\.json SHA-256 input is missing or a symlink",
            ):
                stage_report._sha256_path(linked_manifest)

            real_parent = root / "real-inputs"
            real_parent.mkdir()
            parent_manifest = real_parent / "final-evidence.json"
            write_json(parent_manifest, {"status": "partial_evidence"})

            linked_parent = root / "linked-inputs"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(
                stage_report.ManifestError,
                "final-evidence\\.json SHA-256 input parent may not be a symlink",
            ):
                stage_report._sha256_path(linked_parent / "final-evidence.json")

    def test_rejects_promoted_hrd_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            final_manifest["interpretation"]["scarhrd_use"] = "ready"

            with self.assertRaisesRegex(stage_report.ManifestError, "scarhrd_use"):
                stage_report.stage_phase3_fast_deterministic_report(
                    final_manifest,
                    _crosscheck_materialization_plan(final_manifest, manifest_path),
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=manifest_path.stat().st_size,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )

    def test_rejects_crosscheck_plan_bound_to_another_final_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            materialization_plan = _crosscheck_materialization_plan(
                final_manifest,
                manifest_path,
            )
            materialization_plan["source"]["final_evidence_manifest_sha256"] = "b" * 64

            with self.assertRaisesRegex(stage_report.ManifestError, "not bound"):
                stage_report.stage_phase3_fast_deterministic_report(
                    final_manifest,
                    materialization_plan,
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=manifest_path.stat().st_size,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )

    def test_rejects_crosscheck_plan_that_promotes_sequenza(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            materialization_plan = _crosscheck_materialization_plan(
                final_manifest,
                manifest_path,
            )
            materialization_plan["sequenza_scarhrd"]["status"] = "ready"

            with self.assertRaisesRegex(stage_report.ManifestError, "Sequenza/scarHRD"):
                stage_report.stage_phase3_fast_deterministic_report(
                    final_manifest,
                    materialization_plan,
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=manifest_path.stat().st_size,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )

    def test_rejects_crosscheck_plan_that_unblocks_blocked_model_routes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            materialization_plan = _crosscheck_materialization_plan(
                final_manifest,
                manifest_path,
            )
            materialization_plan["blocked_routes"]["hrdetect"] = "ready"

            with self.assertRaisesRegex(stage_report.ManifestError, "blocked routes"):
                stage_report.stage_phase3_fast_deterministic_report(
                    final_manifest,
                    materialization_plan,
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=manifest_path.stat().st_size,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )

    def test_rejects_tampered_final_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            (final_root / "artifacts/cnv_evidence/coverage_bins/coverage_cnv_bins.csv").write_text("changed\n", encoding="utf-8")

            with self.assertRaisesRegex(stage_report.ManifestError, "cnv_evidence.coverage_bins"):
                stage_report.stage_phase3_fast_deterministic_report(
                    final_manifest,
                    _crosscheck_materialization_plan(final_manifest, manifest_path),
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=manifest_path.stat().st_size,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )

    def test_rejects_boolean_final_artifact_bytes_before_hash_validation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            artifact = final_manifest["artifacts"]["small_variants"]["filter_mutect"]["filtered_vcf"]
            _write_one_byte_final_artifact(final_root, artifact)
            artifact["bytes"] = True

            with self.assertRaisesRegex(
                stage_report.ManifestError,
                "small_variants.filter_mutect.filtered_vcf.bytes",
            ):
                stage_report.stage_phase3_fast_deterministic_report(
                    final_manifest,
                    _crosscheck_materialization_plan(final_manifest, manifest_path),
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=manifest_path.stat().st_size,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )

    def test_rejects_non_lowercase_sha256_before_install(self) -> None:
        cases = (
            (
                "final-artifact",
                lambda final_manifest, materialization_plan: final_manifest[
                    "artifacts"
                ]["small_variants"]["filter_mutect"]["filtered_vcf"].__setitem__(
                    "sha256",
                    final_manifest["artifacts"]["small_variants"]["filter_mutect"][
                        "filtered_vcf"
                    ]["sha256"].upper(),
                ),
                lambda manifest_path: _sha256_path(manifest_path),
            ),
            (
                "crosscheck-source",
                lambda final_manifest, materialization_plan: materialization_plan[
                    "sigprofiler_sbs3"
                ]["final_sources"]["source_vcf"].__setitem__(
                    "sha256",
                    final_manifest["artifacts"]["small_variants"]["filter_mutect"][
                        "filtered_vcf"
                    ]["sha256"].upper(),
                ),
                lambda manifest_path: _sha256_path(manifest_path),
            ),
            (
                "final-manifest",
                lambda final_manifest, materialization_plan: None,
                lambda manifest_path: _sha256_path(manifest_path).upper(),
            ),
        )

        for label, mutate, manifest_sha256 in cases:
            with self.subTest(label=label), TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, final_root, final_manifest = _write_final_manifest(root)
                materialization_plan = _crosscheck_materialization_plan(
                    final_manifest,
                    manifest_path,
                )
                mutate(final_manifest, materialization_plan)
                output = root / "deterministic"

                with self.assertRaisesRegex(
                    stage_report.ManifestError,
                    "must be 64 hex characters",
                ):
                    stage_report.stage_phase3_fast_deterministic_report(
                        final_manifest,
                        materialization_plan,
                        final_manifest_sha256=manifest_sha256(manifest_path),
                        final_manifest_bytes=manifest_path.stat().st_size,
                        final_root=final_root,
                        output_dir=output,
                    )

                self.assertFalse((output / "report_manifest.json").exists())

    def test_rejects_boolean_crosscheck_plan_final_source_bytes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            artifact = final_manifest["artifacts"]["small_variants"]["filter_mutect"]["filtered_vcf"]
            _write_one_byte_final_artifact(final_root, artifact)
            materialization_plan = _crosscheck_materialization_plan(
                final_manifest,
                manifest_path,
            )
            materialization_plan["sigprofiler_sbs3"]["final_sources"]["source_vcf"]["bytes"] = True

            with self.assertRaisesRegex(stage_report.ManifestError, "source_vcf.bytes"):
                stage_report.stage_phase3_fast_deterministic_report(
                    final_manifest,
                    materialization_plan,
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=manifest_path.stat().st_size,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )

    def test_rejects_boolean_crosscheck_reference_bytes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            final_manifest["input_sources"]["reference"]["fasta"]["bytes"] = 1
            materialization_plan = _crosscheck_materialization_plan(
                final_manifest,
                manifest_path,
            )
            materialization_plan["sigprofiler_sbs3"]["reference_sources"]["reference_fasta"]["bytes"] = True

            with self.assertRaisesRegex(stage_report.ManifestError, "reference_fasta.bytes"):
                stage_report.stage_phase3_fast_deterministic_report(
                    final_manifest,
                    materialization_plan,
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=manifest_path.stat().st_size,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )

    def test_rejects_boolean_final_manifest_bytes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)

            with self.assertRaisesRegex(stage_report.ManifestError, "final_manifest_bytes"):
                stage_report.stage_phase3_fast_deterministic_report(
                    final_manifest,
                    _crosscheck_materialization_plan(final_manifest, manifest_path),
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=True,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )

    def test_rejects_unmanifested_final_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            unexpected = final_root / "artifacts/unexpected.txt"
            unexpected.write_text("stale\n", encoding="utf-8")

            with self.assertRaisesRegex(stage_report.ManifestError, "unmanifested"):
                stage_report.stage_phase3_fast_deterministic_report(
                    final_manifest,
                    _crosscheck_materialization_plan(final_manifest, manifest_path),
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=manifest_path.stat().st_size,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )

    def test_rejects_final_artifact_below_symlinked_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            linked_cnv_evidence = final_root / "artifacts/cnv_evidence"
            real_cnv_evidence = root / "real-cnv-evidence"
            linked_cnv_evidence.replace(real_cnv_evidence)
            linked_cnv_evidence.symlink_to(real_cnv_evidence, target_is_directory=True)

            with self.assertRaisesRegex(stage_report.ManifestError, "final artifact parent may not be a symlink"):
                stage_report.stage_phase3_fast_deterministic_report(
                    final_manifest,
                    _crosscheck_materialization_plan(final_manifest, manifest_path),
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=manifest_path.stat().st_size,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )

    def test_rejects_output_below_symlinked_parent_before_writing_report(self) -> None:
        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, final_root, final_manifest = _write_final_manifest(root)
                real_output = root / "real-output"
                if nested == "existing":
                    (real_output / nested).mkdir(parents=True)
                else:
                    real_output.mkdir()
                linked_output = root / "linked-output"
                linked_output.symlink_to(real_output, target_is_directory=True)

                with self.assertRaisesRegex(stage_report.ManifestError, "parent may not be a symlink"):
                    stage_report.stage_phase3_fast_deterministic_report(
                        final_manifest,
                        _crosscheck_materialization_plan(final_manifest, manifest_path),
                        final_manifest_sha256=_sha256_path(manifest_path),
                        final_manifest_bytes=manifest_path.stat().st_size,
                        final_root=final_root,
                        output_dir=linked_output / nested / "deterministic",
                    )

                self.assertEqual([], [path for path in real_output.rglob("*") if path.is_file()])

    def test_preserves_unexpected_child_after_copy_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            output = root / "deterministic"

            def fail_after_partial_copy(_source, destination_handle) -> None:
                destination_handle.write(b"partial deterministic report")
                (output / "unexpected.tmp").write_text(
                    "stray partial file\n",
                    encoding="utf-8",
                )
                raise OSError("simulated deterministic report interruption")

            with patch.object(stage_report.shutil, "copyfileobj", side_effect=fail_after_partial_copy):
                with self.assertRaisesRegex(OSError, "simulated deterministic report interruption"):
                    stage_report.stage_phase3_fast_deterministic_report(
                        final_manifest,
                        _crosscheck_materialization_plan(final_manifest, manifest_path),
                        final_manifest_sha256=_sha256_path(manifest_path),
                        final_manifest_bytes=manifest_path.stat().st_size,
                        final_root=final_root,
                        output_dir=output,
                    )

            self.assertTrue(output.is_dir())
            self.assertEqual(
                (output / "unexpected.tmp").read_text(encoding="utf-8"),
                "stray partial file\n",
            )
            for name in stage_report.OUTPUT_NAMES:
                self.assertFalse((output / name).exists())

    def test_staged_packet_write_rehashes_after_parent_fsync(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "report.md"
            real_fsync_directory = stage_report._fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_bytes(b"tampered\n")

            with patch.object(
                stage_report,
                "_fsync_directory",
                side_effect=tamper_after_parent_fsync,
            ):
                with self.assertRaisesRegex(stage_report.ManifestError, "changed during write"):
                    stage_report._write_staged_text(output, "# Report\n")

            self.assertFalse(output.exists())

    def test_install_packet_rehashes_after_output_fsync(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            output = root / "deterministic"
            staging.mkdir()
            output.mkdir()
            _write_minimal_staged_report(staging)
            real_fsync_directory = stage_report._fsync_directory

            def tamper_after_output_fsync(path: Path) -> None:
                real_fsync_directory(path)
                for name in sorted(stage_report.OUTPUT_NAMES):
                    destination = path / name
                    if destination.exists():
                        destination.write_bytes(b"tampered\n")
                        return

            with patch.object(
                stage_report,
                "_fsync_directory",
                side_effect=tamper_after_output_fsync,
            ):
                with self.assertRaisesRegex(stage_report.ManifestError, "changed during copy"):
                    stage_report._install_packet(output, staging=staging)

            self.assertEqual([], list(output.iterdir()))

    def test_rejects_stale_staged_report_manifest_binding(self) -> None:
        with TemporaryDirectory() as tmp:
            staging = Path(tmp)
            _write_minimal_staged_report(staging)

            (staging / "report.md").write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(
                stage_report.ManifestError,
                "deterministic report manifest is stale for report.md",
            ):
                stage_report._require_staged_report_manifest(staging)

    def test_rejects_stale_staged_support_manifest_binding(self) -> None:
        with TemporaryDirectory() as tmp:
            staging = Path(tmp)
            _write_minimal_staged_report(staging)

            (staging / "readiness.csv").write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(
                stage_report.ManifestError,
                "deterministic report manifest is stale for readiness.csv",
            ):
                stage_report._require_staged_report_manifest(staging)

    def test_cleans_packet_files_after_directory_fsync_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            output = root / "deterministic"

            with patch.object(
                stage_report,
                "_fsync_directory",
                side_effect=[
                    *([None] * len(stage_report.OUTPUT_NAMES)),
                    OSError("simulated deterministic directory fsync failure"),
                ],
            ):
                with self.assertRaisesRegex(OSError, "simulated deterministic directory fsync failure"):
                    stage_report.stage_phase3_fast_deterministic_report(
                        final_manifest,
                        _crosscheck_materialization_plan(final_manifest, manifest_path),
                        final_manifest_sha256=_sha256_path(manifest_path),
                        final_manifest_bytes=manifest_path.stat().st_size,
                        final_root=final_root,
                        output_dir=output,
                    )

            self.assertTrue(output.is_dir())
            self.assertEqual([], list(output.iterdir()))


if __name__ == "__main__":
    unittest.main()
