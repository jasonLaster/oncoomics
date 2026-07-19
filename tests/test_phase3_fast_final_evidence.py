from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import join_phase3_fast_evidence as join_evidence
from diana_omics.commands.phase3_wgs import publish_phase3_fast_final_evidence as final_evidence
from diana_omics.utils import write_json
from tests.test_phase3_fast_evidence_join import SHA_4, SHA_5, SHA_6, SHA_7, phase3_fast_receipts


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _poison_artifact_as_boolean_byte(row: dict) -> None:
    path = Path(row.get("exported_path") or row["local_path"])
    path.write_bytes(b"1")
    row["bytes"] = True
    row["sha256"] = _sha256_path(path)


def _join_manifest(root: Path) -> dict:
    return join_evidence.build_phase3_fast_evidence_join_manifest(
        *phase3_fast_receipts(root),
        small_variant_artifact_export_sha256=SHA_4,
        bam_qc_receipt_sha256=SHA_5,
        cnv_evidence_receipt_sha256=SHA_6,
        sv_evidence_receipt_sha256=SHA_7,
    )


class Phase3FastFinalEvidenceTests(unittest.TestCase):
    def test_copies_joined_artifacts_into_portable_final_tree(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "final"
            manifest = final_evidence.build_phase3_fast_final_evidence_manifest(
                _join_manifest(root),
                evidence_join_sha256=SHA_4,
                small_variant_artifact_root=root / "small_variant_export",
                bam_qc_artifact_root=root / "bam_qc",
                cnv_evidence_artifact_root=root / "cnv_evidence",
                sv_evidence_artifact_root=root / "sv_evidence",
                output_root=output_root,
            )

            filtered_vcf = output_root / manifest["artifacts"]["small_variants"]["filter_mutect"]["filtered_vcf"][
                "relative_path"
            ]
            cnv_bins = output_root / manifest["artifacts"]["cnv_evidence"]["coverage_bins"]["relative_path"]
            sbs96 = output_root / manifest["artifacts"]["small_variants"]["filter_mutect"]["sbs96_matrix"][
                "relative_path"
            ]
            sv_discordant = output_root / manifest["artifacts"]["sv_evidence"]["normal"]["discordant_mapped_pairs"][
                "relative_path"
            ]
            filtered_vcf_group = filtered_vcf.parent.parent.parent.as_posix().rsplit("/final/", 1)[1]
            cnv_bins_sha256 = _sha256_path(cnv_bins)
            sbs96_rows = sbs96.read_text(encoding="utf-8").splitlines()
            sv_discordant_bytes = sv_discordant.stat().st_size

        self.assertEqual("phase3_wgs_fast_final_evidence_manifest", manifest["manifest_type"])
        self.assertEqual("completed", manifest["status"])
        self.assertEqual("no_call", manifest["interpretation"]["authorized_hrd_state"])
        self.assertEqual(35, manifest["artifact_count"])
        self.assertEqual("artifacts/small_variants", filtered_vcf_group)
        self.assertEqual(manifest["artifacts"]["cnv_evidence"]["coverage_bins"]["sha256"], cnv_bins_sha256)
        self.assertEqual(97, len(sbs96_rows))
        self.assertEqual(0, sv_discordant_bytes)
        self.assertEqual("copy-version-5", manifest["input_sources"]["reference"]["fasta"]["version_id"])
        self.assertEqual("copy-version-13", manifest["input_sources"]["caller_resources"]["mutect2_interval_set"]["version_id"])
        self.assertNotIn(str(root), json.dumps(manifest))
        self.assertNotIn("commands", manifest)
        self.assertNotIn("inputs", manifest)

    def test_environment_command_writes_final_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            join_path = root / "join.json"
            output_path = root / "final-manifest.json"
            output_root = root / "final"
            write_json(join_path, _join_manifest(root))

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_EVIDENCE_JOIN": str(join_path),
                    "PHASE3_WGS_FAST_SMALL_VARIANT_ARTIFACT_ROOT": str(root / "small_variant_export"),
                    "PHASE3_WGS_FAST_BAM_QC_ARTIFACT_ROOT": str(root / "bam_qc"),
                    "PHASE3_WGS_FAST_CNV_EVIDENCE_ARTIFACT_ROOT": str(root / "cnv_evidence"),
                    "PHASE3_WGS_FAST_SV_EVIDENCE_ARTIFACT_ROOT": str(root / "sv_evidence"),
                    "PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT": str(output_root),
                    "PHASE3_WGS_FAST_FINAL_EVIDENCE_OUTPUT": str(output_path),
                },
                clear=False,
            ):
                manifest, output = final_evidence.load_manifest_from_environment()
                final_evidence.write_manifest(output, manifest)
            output_text = output_path.read_text(encoding="utf-8")
            expected_join_sha256 = _sha256_path(join_path)

        self.assertEqual(output_path, output)
        self.assertEqual(expected_join_sha256, manifest["source"]["evidence_join_manifest_sha256"])
        self.assertIn('"manifest_type": "phase3_wgs_fast_final_evidence_manifest"', output_text)

    def test_environment_command_rejects_missing_directory_or_symlinked_join(self) -> None:
        cases = ("missing", "directory", "symlink")
        for bad_kind in cases:
            with self.subTest(bad_kind=bad_kind), TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_join = root / "real-join.json"
                bad_join = root / f"join-{bad_kind}.json"
                write_json(real_join, _join_manifest(root))
                if bad_kind == "directory":
                    bad_join.mkdir()
                elif bad_kind == "symlink":
                    bad_join.symlink_to(real_join)

                with patch.dict(
                    "os.environ",
                    {
                        "PHASE3_WGS_FAST_EVIDENCE_JOIN": str(bad_join),
                        "PHASE3_WGS_FAST_SMALL_VARIANT_ARTIFACT_ROOT": str(root / "small_variant_export"),
                        "PHASE3_WGS_FAST_BAM_QC_ARTIFACT_ROOT": str(root / "bam_qc"),
                        "PHASE3_WGS_FAST_CNV_EVIDENCE_ARTIFACT_ROOT": str(root / "cnv_evidence"),
                        "PHASE3_WGS_FAST_SV_EVIDENCE_ARTIFACT_ROOT": str(root / "sv_evidence"),
                        "PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT": str(root / "final"),
                        "PHASE3_WGS_FAST_FINAL_EVIDENCE_OUTPUT": str(root / "final-manifest.json"),
                    },
                    clear=False,
                ):
                    with self.assertRaisesRegex(final_evidence.ManifestError, "evidence_join"):
                        final_evidence.load_manifest_from_environment()

    def test_environment_command_rejects_join_below_symlinked_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-inputs"
            linked_parent = root / "linked-inputs"
            real_parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            join_path = linked_parent / "join.json"
            write_json(join_path, _join_manifest(root))

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_EVIDENCE_JOIN": str(join_path),
                    "PHASE3_WGS_FAST_SMALL_VARIANT_ARTIFACT_ROOT": str(root / "small_variant_export"),
                    "PHASE3_WGS_FAST_BAM_QC_ARTIFACT_ROOT": str(root / "bam_qc"),
                    "PHASE3_WGS_FAST_CNV_EVIDENCE_ARTIFACT_ROOT": str(root / "cnv_evidence"),
                    "PHASE3_WGS_FAST_SV_EVIDENCE_ARTIFACT_ROOT": str(root / "sv_evidence"),
                    "PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT": str(root / "final"),
                    "PHASE3_WGS_FAST_FINAL_EVIDENCE_OUTPUT": str(root / "final-manifest.json"),
                },
                clear=False,
            ):
                with self.assertRaisesRegex(final_evidence.ManifestError, "evidence_join parent may not be a symlink"):
                    final_evidence.load_manifest_from_environment()

    def test_sha256_path_rejects_symlinked_hash_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-parent"
            real_parent.mkdir()

            real_join = root / "real-join.json"
            real_join.write_text("{}\n", encoding="utf-8")
            symlinked_join = root / "join.json"
            symlinked_join.symlink_to(real_join)

            parent_join = real_parent / "join.json"
            parent_join.write_text("{}\n", encoding="utf-8")
            symlinked_parent = root / "symlinked-parent"
            symlinked_parent.symlink_to(real_parent, target_is_directory=True)

            cases = (
                (symlinked_join, "SHA-256 input"),
                (symlinked_parent / parent_join.name, "parent may not be a symlink"),
            )
            for hash_input, message in cases:
                with self.subTest(hash_input=hash_input), self.assertRaisesRegex(final_evidence.ManifestError, message):
                    final_evidence._sha256_path(hash_input)

    def test_rejects_non_completed_join(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            join = _join_manifest(root)
            join["status"] = "stubbed"

            with self.assertRaisesRegex(final_evidence.ManifestError, "status"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    join,
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=root / "final",
                )

    def test_rejects_promoted_hrd_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            join = _join_manifest(root)
            join["interpretation"]["chord_use"] = "ready"

            with self.assertRaisesRegex(final_evidence.ManifestError, "chord_use"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    join,
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=root / "final",
                )

    def test_rejects_artifact_tampering_before_copy(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            join = _join_manifest(root)
            (root / "bam_qc" / "normal" / "idxstats.tsv").write_text("changed\n", encoding="utf-8")

            with self.assertRaisesRegex(final_evidence.ManifestError, "bam_qc.normal.idxstats"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    join,
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=root / "final",
                )

    def test_rejects_boolean_small_variant_export_bytes_before_copy(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            join = _join_manifest(root)
            _poison_artifact_as_boolean_byte(
                join["evidence"]["small_variants"]["exports"]["filter_mutect"]["filtered_vcf"]
            )

            with self.assertRaisesRegex(
                final_evidence.ManifestError,
                "small_variants.filter_mutect.filtered_vcf.bytes",
            ):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    join,
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=root / "final",
                )

    def test_rejects_boolean_side_evidence_bytes_before_copy(self) -> None:
        cases = (
            (
                "bam_qc.normal.idxstats.bytes",
                lambda join: join["evidence"]["bam_qc"]["materialized_outputs"]["normal"]["idxstats"],
            ),
            (
                "cnv_evidence.coverage_bins.bytes",
                lambda join: join["evidence"]["cnv_evidence"]["materialized_outputs"]["coverage_bins"],
            ),
            (
                "cnv_evidence.interval_shards.chr1.bedcov_tsv.bytes",
                lambda join: join["evidence"]["cnv_evidence"]["materialized_outputs"]["interval_shards"]["chr1"][
                    "bedcov_tsv"
                ],
            ),
            (
                "sv_evidence.tumor.idxstats.bytes",
                lambda join: join["evidence"]["sv_evidence"]["materialized_outputs"]["tumor"]["idxstats"],
            ),
        )

        for label, select_row in cases:
            with self.subTest(label=label), TemporaryDirectory() as tmp:
                root = Path(tmp)
                join = _join_manifest(root)
                _poison_artifact_as_boolean_byte(select_row(join))

                with self.assertRaisesRegex(final_evidence.ManifestError, label):
                    final_evidence.build_phase3_fast_final_evidence_manifest(
                        join,
                        evidence_join_sha256=SHA_4,
                        small_variant_artifact_root=root / "small_variant_export",
                        bam_qc_artifact_root=root / "bam_qc",
                        cnv_evidence_artifact_root=root / "cnv_evidence",
                        sv_evidence_artifact_root=root / "sv_evidence",
                        output_root=root / "final",
                    )

    def test_rejects_symlinked_source_before_copy(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            join = _join_manifest(root)
            source = root / "bam_qc" / "normal" / "idxstats.tsv"
            redirected = source.parent / "idxstats.redirected.tsv"
            source.rename(redirected)
            source.symlink_to(redirected)

            with self.assertRaisesRegex(final_evidence.ManifestError, "source may not be a symlink"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    join,
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=root / "final",
                )

    def test_rejects_unexpected_existing_final_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            unexpected = root / "final" / "artifacts" / "unexpected.txt"
            unexpected.parent.mkdir(parents=True)
            unexpected.write_text("stale\n", encoding="utf-8")

            with self.assertRaisesRegex(final_evidence.ManifestError, "unexpected existing final artifact"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    _join_manifest(root),
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=root / "final",
                )

    def test_rejects_unexpected_symlink_in_existing_final_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "final"
            linked_dir = output_root / "artifacts" / "old"
            real_dir = root / "real-old"
            real_dir.mkdir()
            linked_dir.parent.mkdir(parents=True)
            linked_dir.symlink_to(real_dir, target_is_directory=True)

            with self.assertRaisesRegex(final_evidence.ManifestError, "output_root contains a symlink"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    _join_manifest(root),
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=output_root,
                )

            self.assertEqual([], list(real_dir.rglob("*")))

    def test_removes_partial_temporary_copy_after_copy_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "final"

            def fail_after_partial_copy(_source: Path, destination: Path) -> None:
                Path(destination).write_bytes(b"partial final artifact")
                raise OSError("simulated copy interruption")

            with patch.object(final_evidence.shutil, "copyfile", side_effect=fail_after_partial_copy):
                with self.assertRaisesRegex(OSError, "simulated copy interruption"):
                    final_evidence.build_phase3_fast_final_evidence_manifest(
                        _join_manifest(root),
                        evidence_join_sha256=SHA_4,
                        small_variant_artifact_root=root / "small_variant_export",
                        bam_qc_artifact_root=root / "bam_qc",
                        cnv_evidence_artifact_root=root / "cnv_evidence",
                        sv_evidence_artifact_root=root / "sv_evidence",
                        output_root=output_root,
                    )

            self.assertEqual([], [path for path in output_root.rglob("*") if path.is_file()])

    def test_rejects_symlinked_temporary_copy_before_installing_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "final"
            redirected = root / "redirected-final-artifact"

            def write_symlink(_source: Path, destination: Path) -> None:
                redirected.write_bytes(b"redirected final artifact")
                Path(destination).symlink_to(redirected)

            with patch.object(final_evidence.shutil, "copyfile", side_effect=write_symlink):
                with self.assertRaisesRegex(final_evidence.ManifestError, "may not be a symlink"):
                    final_evidence.build_phase3_fast_final_evidence_manifest(
                        _join_manifest(root),
                        evidence_join_sha256=SHA_4,
                        small_variant_artifact_root=root / "small_variant_export",
                        bam_qc_artifact_root=root / "bam_qc",
                        cnv_evidence_artifact_root=root / "cnv_evidence",
                        sv_evidence_artifact_root=root / "sv_evidence",
                        output_root=output_root,
                    )

            self.assertEqual([], [path for path in output_root.rglob("*") if path.is_file()])

    def test_rejects_and_removes_tampered_installed_final_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "final"
            join_manifest = _join_manifest(root)
            original_replace = Path.replace

            def replace_then_tamper(source: Path, target: Path) -> Path:
                installed = original_replace(source, target)
                Path(target).write_bytes(b"tampered installed final artifact\n")
                return installed

            with patch.object(Path, "replace", replace_then_tamper):
                with self.assertRaisesRegex(
                    final_evidence.ManifestError,
                    "installed bytes and sha256",
                ):
                    final_evidence.build_phase3_fast_final_evidence_manifest(
                        join_manifest,
                        evidence_join_sha256=SHA_4,
                        small_variant_artifact_root=root / "small_variant_export",
                        bam_qc_artifact_root=root / "bam_qc",
                        cnv_evidence_artifact_root=root / "cnv_evidence",
                        sv_evidence_artifact_root=root / "sv_evidence",
                        output_root=output_root,
                    )

            self.assertEqual([], [path for path in output_root.rglob("*") if path.is_file()])

    def test_rejects_symlinked_output_root_without_copying_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_output = root / "real-final"
            real_output.mkdir()
            output_root = root / "final"
            output_root.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(final_evidence.ManifestError, "output_root.*symlink"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    _join_manifest(root),
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=output_root,
                )

            self.assertEqual([], list(real_output.rglob("*")))

    def test_rejects_output_root_below_symlinked_parent_without_copying_outputs(self) -> None:
        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_output = root / "real-final"
                if nested == "existing":
                    (real_output / nested).mkdir(parents=True)
                else:
                    real_output.mkdir()
                linked_output = root / "linked-final"
                linked_output.symlink_to(real_output, target_is_directory=True)

                with self.assertRaisesRegex(final_evidence.ManifestError, "parent may not be a symlink"):
                    final_evidence.build_phase3_fast_final_evidence_manifest(
                        _join_manifest(root),
                        evidence_join_sha256=SHA_4,
                        small_variant_artifact_root=root / "small_variant_export",
                        bam_qc_artifact_root=root / "bam_qc",
                        cnv_evidence_artifact_root=root / "cnv_evidence",
                        sv_evidence_artifact_root=root / "sv_evidence",
                        output_root=linked_output / nested / "final",
                    )

                self.assertEqual([], [path for path in real_output.rglob("*") if path.is_file()])


if __name__ == "__main__":
    unittest.main()
