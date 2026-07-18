from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.test_phase3_fast_final_evidence import _join_manifest

from diana_omics.commands.phase3_wgs import plan_phase3_fast_crosscheck_inputs as crosscheck_plan
from diana_omics.commands.phase3_wgs import publish_phase3_fast_final_evidence as final_evidence
from diana_omics.commands.phase3_wgs import stage_phase3_fast_deterministic_report as stage_report
from diana_omics.utils import read_json, write_json


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


class Phase3FastDeterministicReportTests(unittest.TestCase):
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
            linked_coverage_bins = final_root / "artifacts/cnv_evidence/coverage_bins"
            real_coverage_bins = root / "real-coverage-bins"
            linked_coverage_bins.replace(real_coverage_bins)
            linked_coverage_bins.symlink_to(real_coverage_bins, target_is_directory=True)

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
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, final_root, final_manifest = _write_final_manifest(root)
            real_output = root / "real-output"
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
                    output_dir=linked_output / "deterministic",
                )

            self.assertEqual([], list(real_output.rglob("*")))

    def test_removes_partially_installed_report_after_copy_failure(self) -> None:
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

            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
