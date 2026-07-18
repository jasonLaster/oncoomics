from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_final_evidence import _join_manifest

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
                final_manifest_sha256=_sha256_path(manifest_path),
                final_manifest_bytes=manifest_path.stat().st_size,
                final_root=final_root,
                output_dir=output,
            )
            output_names = {path.name for path in output.iterdir()}
            report = (output / "report.md").read_text(encoding="utf-8")
            input_rows = _read_csv(output / "input_sha256.csv")
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
        self.assertIn("no production SV VCF/BEDPE", report)
        self.assertNotIn(str(root), json.dumps(report_manifest))
        self.assertNotIn(str(root), report)

        artifacts = _flatten_artifacts(final_manifest["artifacts"])
        self.assertEqual(final_manifest["artifact_count"] + 1, len(input_rows))
        self.assertEqual("final_evidence_manifest", input_rows[0]["input_id"])
        for row, exists, digest, size in zip(input_rows[1:], artifact_exists, artifact_hashes, artifact_sizes, strict=True):
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
            output = root / "deterministic"

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST": str(manifest_path),
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
                    final_manifest_sha256=_sha256_path(manifest_path),
                    final_manifest_bytes=manifest_path.stat().st_size,
                    final_root=final_root,
                    output_dir=root / "deterministic",
                )


if __name__ == "__main__":
    unittest.main()
