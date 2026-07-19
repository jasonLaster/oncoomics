from __future__ import annotations

import copy
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import export_phase3_fast_small_variant_artifacts as export_small_variants
from diana_omics.commands.phase3_wgs import join_phase3_fast_evidence as join_evidence
from diana_omics.commands.phase3_wgs import run_phase3_fast_bam_qc as run_bam_qc
from diana_omics.commands.phase3_wgs import run_phase3_fast_cnv_evidence as run_cnv
from diana_omics.commands.phase3_wgs import run_phase3_fast_filter_mutect as run_filter
from diana_omics.commands.phase3_wgs import run_phase3_fast_sv_evidence as run_sv
from diana_omics.utils import write_json
from tests.test_phase3_fast_bam_qc_run import MaterializingSamtoolsRunner as BamQcRunner
from tests.test_phase3_fast_bam_qc_run import phase3_fast_bam_qc_plan
from tests.test_phase3_fast_cnv_evidence_run import MaterializingBedcovRunner, phase3_fast_cnv_evidence_plan
from tests.test_phase3_fast_filter_mutect_run import FilterMutectRunner, filter_plan_and_parabricks_receipt
from tests.test_phase3_fast_input_manifest import SHA_1
from tests.test_phase3_fast_small_variant_export import SHA_2, SHA_3
from tests.test_phase3_fast_sv_evidence_run import MaterializingSamtoolsRunner as SvEvidenceRunner
from tests.test_phase3_fast_sv_evidence_run import phase3_fast_sv_evidence_plan

SHA_4 = "d" * 64
SHA_5 = "e" * 64
SHA_6 = "f" * 64
SHA_7 = "1" * 64
ENV_PATHS = {
    "small_variant_artifact_export": "PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT",
    "bam_qc": "PHASE3_WGS_FAST_BAM_QC_RECEIPT",
    "cnv_evidence": "PHASE3_WGS_FAST_CNV_EVIDENCE_RECEIPT",
    "sv_evidence": "PHASE3_WGS_FAST_SV_EVIDENCE_RECEIPT",
}


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_phase3_fast_receipt_files(root: Path) -> dict[str, Path]:
    paths = {
        "small_variant_artifact_export": root / "small-export.json",
        "bam_qc": root / "bam-qc.json",
        "cnv_evidence": root / "cnv.json",
        "sv_evidence": root / "sv.json",
    }
    receipts = phase3_fast_receipts(root)
    for path, receipt in zip(paths.values(), receipts):
        write_json(path, receipt)
    return paths


def evidence_join_env(paths: dict[str, Path], output: Path) -> dict[str, str]:
    return {
        **{
            env_name: str(paths[key])
            for key, env_name in ENV_PATHS.items()
        },
        "PHASE3_WGS_FAST_EVIDENCE_JOIN_OUTPUT": str(output),
    }


def phase3_fast_receipts(root: Path) -> tuple[dict, dict, dict, dict]:
    filter_plan, parabricks_receipt = filter_plan_and_parabricks_receipt(root)
    filter_receipt = run_filter.run_phase3_fast_filter_mutect(
        filter_plan,
        parabricks_receipt,
        runner=FilterMutectRunner(),
        filter_mutect_plan_sha256=SHA_1,
        parabricks_mutect_receipt_sha256=SHA_2,
    )
    small_variant_export = export_small_variants.export_phase3_fast_small_variant_artifacts(
        parabricks_receipt,
        filter_receipt,
        parabricks_mutect_receipt_sha256=SHA_2,
        filter_mutect_receipt_sha256=SHA_3,
        output_root=root / "small_variant_export",
    )
    bam_qc_receipt = run_bam_qc.run_phase3_fast_bam_qc(
        phase3_fast_bam_qc_plan(root),
        runner=BamQcRunner(),
        bam_qc_plan_sha256=SHA_4,
    )
    cnv_evidence_receipt = run_cnv.run_phase3_fast_cnv_evidence(
        phase3_fast_cnv_evidence_plan(root),
        runner=MaterializingBedcovRunner(),
        cnv_evidence_plan_sha256=SHA_5,
    )
    sv_evidence_receipt = run_sv.run_phase3_fast_sv_evidence(
        phase3_fast_sv_evidence_plan(root),
        runner=SvEvidenceRunner(),
        sv_evidence_plan_sha256=SHA_6,
    )
    return small_variant_export, bam_qc_receipt, cnv_evidence_receipt, sv_evidence_receipt


class Phase3FastEvidenceJoinTests(unittest.TestCase):
    def test_joins_completed_receipts_into_pointer_only_no_call_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = phase3_fast_receipts(Path(tmp))

            manifest = join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

        self.assertEqual("phase3_wgs_fast_evidence_join_manifest", manifest["manifest_type"])
        self.assertEqual("completed", manifest["status"])
        self.assertEqual("phase3_wgs_fast", manifest["workflow"]["name"])
        self.assertEqual("no_call", manifest["interpretation"]["authorized_hrd_state"])
        self.assertEqual("deterministic_sample_evidence_not_scalar_hrd", manifest["interpretation"]["small_variants_use"])
        self.assertEqual("qc_only_not_hrd_evidence", manifest["interpretation"]["bam_qc_use"])
        self.assertEqual("no_call_requires_allele_specific_cnv_loh_segments", manifest["interpretation"]["scarhrd_use"])
        self.assertEqual("no_call_requires_validated_production_sv_caller_vcf", manifest["interpretation"]["chord_use"])
        self.assertEqual("no_call_requires_validated_structural_variant_features", manifest["interpretation"]["hrdetect_use"])
        self.assertEqual(SHA_1, manifest["source"]["receipt_sha256"]["small_variant_artifact_export"])
        self.assertIn("filter_mutect", manifest["evidence"]["small_variants"]["exports"])
        self.assertIn("tumor", manifest["evidence"]["bam_qc"]["materialized_outputs"])
        self.assertIn("coverage_bins", manifest["evidence"]["cnv_evidence"]["materialized_outputs"])
        self.assertEqual(7, manifest["evidence"]["sv_evidence"]["metrics"]["tumor"]["supplementary_alignments"])
        self.assertEqual("copy-version-5", manifest["input_sources"]["reference"]["fasta"]["version_id"])
        self.assertEqual("copy-version-8", manifest["input_sources"]["caller_resources"]["common_sites_index"]["version_id"])
        self.assertNotIn("commands", manifest)
        self.assertNotIn("inputs", manifest)

    def test_environment_command_writes_manifest_with_receipt_hashes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "joined.json"
            paths = write_phase3_fast_receipt_files(root)

            with patch.dict(
                "os.environ",
                evidence_join_env(paths, output_path),
                clear=False,
            ):
                manifest, output = join_evidence.load_manifest_from_environment()
                join_evidence.write_manifest(output, manifest)
            output_text = output_path.read_text(encoding="utf-8")
            expected_hashes = {
                key: _sha256_json(path)
                for key, path in paths.items()
            }

        self.assertEqual(output_path, output)
        self.assertEqual(expected_hashes, manifest["source"]["receipt_sha256"])
        self.assertIn('"manifest_type": "phase3_wgs_fast_evidence_join_manifest"', output_text)

    def test_environment_command_rejects_missing_directory_or_symlinked_receipts(self) -> None:
        cases = (
            ("small_variant_artifact_export", "symlink"),
            ("bam_qc", "directory"),
            ("cnv_evidence", "missing"),
            ("sv_evidence", "symlink"),
        )
        for key, bad_kind in cases:
            with self.subTest(key=key, bad_kind=bad_kind), TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = write_phase3_fast_receipt_files(root)
                bad_path = root / f"{key}-{bad_kind}.json"
                if bad_kind == "directory":
                    bad_path.mkdir()
                elif bad_kind == "symlink":
                    bad_path.symlink_to(paths[key])
                paths[key] = bad_path

                with patch.dict(
                    "os.environ",
                    evidence_join_env(paths, root / "joined.json"),
                    clear=False,
                ):
                    with self.assertRaisesRegex(join_evidence.ManifestError, key):
                        join_evidence.load_manifest_from_environment()

    def test_environment_command_rejects_receipt_below_symlinked_parent(self) -> None:
        for key in ENV_PATHS:
            with self.subTest(key=key), TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = write_phase3_fast_receipt_files(root)
                real_parent = root / "real-receipts"
                linked_parent = root / "linked-receipts"
                real_parent.mkdir()
                linked_parent.symlink_to(real_parent, target_is_directory=True)
                bad_path = linked_parent / f"{key}.json"
                bad_path.write_bytes(paths[key].read_bytes())
                paths[key] = bad_path

                with patch.dict(
                    "os.environ",
                    evidence_join_env(paths, root / "joined.json"),
                    clear=False,
                ):
                    with self.assertRaisesRegex(join_evidence.ManifestError, f"{key} parent may not be a symlink"):
                        join_evidence.load_manifest_from_environment()

    def test_sha256_path_rejects_symlinked_hash_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-parent"
            real_parent.mkdir()

            real_receipt = root / "real-bam-qc.json"
            real_receipt.write_text("{}\n", encoding="utf-8")
            symlinked_receipt = root / "bam-qc.json"
            symlinked_receipt.symlink_to(real_receipt)

            parent_receipt = real_parent / "bam-qc.json"
            parent_receipt.write_text("{}\n", encoding="utf-8")
            symlinked_parent = root / "symlinked-parent"
            symlinked_parent.symlink_to(real_parent, target_is_directory=True)

            cases = (
                (symlinked_receipt, "SHA-256 input"),
                (symlinked_parent / parent_receipt.name, "parent may not be a symlink"),
            )
            for hash_input, message in cases:
                with self.subTest(hash_input=hash_input), self.assertRaisesRegex(join_evidence.ManifestError, message):
                    join_evidence._sha256_path(hash_input)

    def test_rejects_non_completed_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[1]["status"] = "stubbed"

        with self.assertRaisesRegex(join_evidence.ManifestError, "bam_qc status"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_rejects_mismatched_run_identity(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[3]["run"]["run_id"] = "other"

        with self.assertRaisesRegex(join_evidence.ManifestError, "sv_evidence run"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_rejects_promoted_cnv_scarhrd_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[2]["interpretation"]["scarhrd_use"] = "ready"

        with self.assertRaisesRegex(join_evidence.ManifestError, "scarhrd_use"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_rejects_promoted_sv_chord_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[3]["interpretation"]["chord_use"] = "ready"

        with self.assertRaisesRegex(join_evidence.ManifestError, "chord_use"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_7,
            )

    def test_rejects_bam_qc_inputs_from_another_cached_bam_version(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[1]["inputs"]["tumor"]["bam"]["source"]["version_id"] = "other-copy-version"

        with self.assertRaisesRegex(join_evidence.ManifestError, "bam_qc tumor.bam input source"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_rejects_cnv_inputs_from_another_reference_version(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[2]["inputs"]["reference"]["fasta"]["source"][
            "uri"
        ] = "s3://diana-omics-private-cache-us-east-2/wgs-v2/references/reference.fa/other/reference.fa"

        with self.assertRaisesRegex(join_evidence.ManifestError, "cnv_evidence reference.fasta input source"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_rejects_sv_inputs_from_another_cached_bai_version(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[3]["inputs"]["normal"]["bai"]["source"]["version_id"] = "other-copy-version"

        with self.assertRaisesRegex(join_evidence.ManifestError, "sv_evidence normal.bai input source"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_rejects_unexpected_branch_output_keys(self) -> None:
        with TemporaryDirectory() as tmp:
            base_receipts = list(phase3_fast_receipts(Path(tmp)))

        cases = (
            (
                lambda receipts: receipts[0]["exports"]["filter_mutect"].__setitem__(
                    "stale_filtered_vcf",
                    copy.deepcopy(receipts[0]["exports"]["filter_mutect"]["filtered_vcf"]),
                ),
                "filter_mutect exports",
            ),
            (
                lambda receipts: receipts[1]["materialized_outputs"]["tumor"].__setitem__(
                    "stale_idxstats",
                    copy.deepcopy(receipts[1]["materialized_outputs"]["tumor"]["idxstats"]),
                ),
                "bam_qc materialized_outputs.tumor",
            ),
            (
                lambda receipts: receipts[2]["materialized_outputs"].__setitem__(
                    "stale_coverage_bins",
                    copy.deepcopy(receipts[2]["materialized_outputs"]["coverage_bins"]),
                ),
                "cnv_evidence materialized_outputs",
            ),
            (
                lambda receipts: receipts[2]["materialized_outputs"]["interval_shards"]["chr1"].__setitem__(
                    "stale_bedcov_tsv",
                    copy.deepcopy(
                        receipts[2]["materialized_outputs"]["interval_shards"]["chr1"]["bedcov_tsv"]
                    ),
                ),
                "cnv_evidence interval_shards.chr1",
            ),
            (
                lambda receipts: receipts[3]["materialized_outputs"]["normal"].__setitem__(
                    "stale_discordant_mapped_pairs",
                    copy.deepcopy(
                        receipts[3]["materialized_outputs"]["normal"]["discordant_mapped_pairs"]
                    ),
                ),
                "sv_evidence materialized_outputs.normal",
            ),
        )

        for mutate, message in cases:
            with self.subTest(message=message):
                receipts = copy.deepcopy(base_receipts)
                mutate(receipts)

                with self.assertRaisesRegex(join_evidence.ManifestError, message):
                    join_evidence.build_phase3_fast_evidence_join_manifest(
                        *receipts,
                        small_variant_artifact_export_sha256=SHA_1,
                        bam_qc_receipt_sha256=SHA_2,
                        cnv_evidence_receipt_sha256=SHA_3,
                        sv_evidence_receipt_sha256=SHA_4,
                    )

    def test_manifest_output_rejects_symlinked_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_output = root / "real-output"
            real_output.mkdir()
            linked_output = root / "linked-output"
            linked_output.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(join_evidence.ManifestError, "parent may not be a symlink"):
                join_evidence.write_manifest(
                    linked_output / "evidence-join.json",
                    {"status": "redirected"},
                )

            self.assertEqual([], list(real_output.rglob("*")))


if __name__ == "__main__":
    unittest.main()
