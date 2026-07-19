from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import render_phase3_fast_cache_manifest as cache
from diana_omics.commands.phase3_wgs import replicate_phase3_fast_inputs as replicate
from diana_omics.utils import write_json
from tests.test_phase3_fast_input_manifest import SHA_1, SHA_3
from tests.test_phase3_fast_replicate_inputs import FakeS3CopyClient
from tests.test_phase3_fast_replication_plan import Phase3FastReplicationPlanTests


def applied_receipt() -> dict:
    plan = Phase3FastReplicationPlanTests().build_plan()
    receipt = replicate.build_phase3_fast_replication_receipt(
        plan,
        mode="apply",
        replication_plan_sha256=SHA_3,
    )
    return replicate.apply_phase3_fast_replication_receipt(receipt, FakeS3CopyClient())


class Phase3FastCacheManifestTests(unittest.TestCase):
    def test_cache_manifest_groups_applied_cache_objects_for_downstream_callers(self) -> None:
        manifest = cache.build_phase3_fast_cache_manifest(
            applied_receipt(),
            replication_receipt_sha256=SHA_1,
        )

        self.assertEqual("phase3_wgs_fast_cache_manifest", manifest["manifest_type"])
        self.assertEqual("ready", manifest["status"])
        self.assertEqual("phase3_wgs_fast", manifest["workflow"]["name"])
        self.assertEqual("parabricks_mutectcaller", manifest["runtime"]["caller"])
        self.assertEqual("subject01_tumor_normal", manifest["run"]["pair_id"])
        self.assertEqual("no_call", manifest["interpretation"]["authorized_hrd_state"])
        self.assertEqual(15, manifest["object_count"])
        self.assertEqual(179, manifest["total_bytes"])

        self.assertEqual("s3://diana-omics-private-cache-us-east-2/wgs-v2/inputs/tumor.bam/" + ("c" * 64) + "/tumor.markdup.bam", manifest["bam_pair"]["tumor"]["bam"]["uri"])
        self.assertEqual("copy-version-1", manifest["bam_pair"]["tumor"]["bam"]["version_id"])
        self.assertEqual("subject01_tumor", manifest["bam_pair"]["tumor"]["bam"]["sample_id"])
        self.assertEqual("s3://diana-omics-private-cache-us-east-2/wgs-v2/references/reference.fa/" + ("f" * 64) + "/reference.fa", manifest["reference"]["fasta"]["uri"])
        self.assertEqual("s3://diana-omics-private-cache-us-east-2/wgs-v2/resources/panel_of_normals_vcf/" + ("8" * 64) + "/panel_of_normals_vcf", manifest["caller_resources"]["panel_of_normals_vcf"]["uri"])

    def test_rejects_dry_run_receipt(self) -> None:
        plan = Phase3FastReplicationPlanTests().build_plan()
        receipt = replicate.build_phase3_fast_replication_receipt(
            plan,
            mode="dry_run",
            replication_plan_sha256=SHA_3,
        )

        with self.assertRaisesRegex(cache.ManifestError, "applied"):
            cache.build_phase3_fast_cache_manifest(
                receipt,
                replication_receipt_sha256=SHA_1,
            )

    def test_rejects_planned_apply_receipt(self) -> None:
        plan = Phase3FastReplicationPlanTests().build_plan()
        receipt = replicate.build_phase3_fast_replication_receipt(
            plan,
            mode="apply",
            replication_plan_sha256=SHA_3,
        )

        with self.assertRaisesRegex(cache.ManifestError, "applied"):
            cache.build_phase3_fast_cache_manifest(
                receipt,
                replication_receipt_sha256=SHA_1,
            )

    def test_rejects_rows_without_durable_source_or_destination_version(
        self,
    ) -> None:
        cases = (
            (
                "source",
                lambda row, version_id: row.__setitem__(
                    "source_version_id",
                    version_id,
                ),
            ),
            (
                "destination",
                lambda row, version_id: row.__setitem__(
                    "destination_version_id",
                    version_id,
                ),
            ),
        )

        for field, mutate in cases:
            for version_id in ("null", "None", "none", "has space"):
                with self.subTest(field=field, version_id=version_id):
                    receipt = applied_receipt()
                    mutate(receipt["copy_results"][0], version_id)

                    with self.assertRaisesRegex(cache.ManifestError, "durable"):
                        cache.build_phase3_fast_cache_manifest(
                            receipt,
                            replication_receipt_sha256=SHA_1,
                        )

    def test_rejects_rows_without_destination_metadata_check(self) -> None:
        receipt = applied_receipt()
        receipt["copy_results"][0]["checks"]["destination_metadata_matches"] = False

        with self.assertRaisesRegex(cache.ManifestError, "destination_metadata_matches"):
            cache.build_phase3_fast_cache_manifest(
                receipt,
                replication_receipt_sha256=SHA_1,
            )

    def test_receipt_counts_must_be_exact_integers(self) -> None:
        receipt = applied_receipt()
        receipt["object_count"] = float(receipt["object_count"])

        with self.assertRaisesRegex(cache.ManifestError, "object_count"):
            cache.build_phase3_fast_cache_manifest(
                receipt,
                replication_receipt_sha256=SHA_1,
            )

        receipt = applied_receipt()
        receipt["total_bytes"] = float(receipt["total_bytes"])

        with self.assertRaisesRegex(cache.ManifestError, "total_bytes"):
            cache.build_phase3_fast_cache_manifest(
                receipt,
                replication_receipt_sha256=SHA_1,
            )

    def test_receipt_bytes_must_be_exact_positive_integers(self) -> None:
        receipt = applied_receipt()
        old_bytes = receipt["copy_results"][0]["bytes"]
        receipt["copy_results"][0]["bytes"] = True
        receipt["total_bytes"] = receipt["total_bytes"] - old_bytes + 1

        with self.assertRaisesRegex(cache.ManifestError, "positive integer"):
            cache.build_phase3_fast_cache_manifest(
                receipt,
                replication_receipt_sha256=SHA_1,
            )

    def test_environment_command_writes_cache_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "replication-receipt.json"
            output_path = root / "cache-manifest.json"
            write_json(input_path, applied_receipt())

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_REPLICATION_RECEIPT": str(input_path),
                    "PHASE3_WGS_FAST_CACHE_MANIFEST_OUTPUT": str(output_path),
                },
                clear=False,
            ):
                manifest, manifest_path = cache.load_manifest_from_environment()
                cache.write_manifest(manifest_path, manifest)

            self.assertEqual(output_path, manifest_path)
            self.assertEqual("ready", manifest["status"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_cache_manifest"', output_path.read_text(encoding="utf-8"))

    def test_environment_command_rejects_redirected_replication_receipt(self) -> None:
        for bad_kind in ("missing", "directory", "symlink"):
            with self.subTest(bad_kind=bad_kind), TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_receipt = root / "real-replication-receipt.json"
                bad_receipt = root / f"replication-receipt-{bad_kind}.json"
                write_json(real_receipt, applied_receipt())
                if bad_kind == "directory":
                    bad_receipt.mkdir()
                elif bad_kind == "symlink":
                    bad_receipt.symlink_to(real_receipt)

                with patch.dict(
                    "os.environ",
                    {
                        "PHASE3_WGS_FAST_REPLICATION_RECEIPT": str(bad_receipt),
                        "PHASE3_WGS_FAST_CACHE_MANIFEST_OUTPUT": str(root / "cache-manifest.json"),
                    },
                    clear=False,
                ):
                    with self.assertRaisesRegex(cache.ManifestError, "replication_receipt"):
                        cache.load_manifest_from_environment()


if __name__ == "__main__":
    unittest.main()
