from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import render_phase3_fast_input_manifest as render
from diana_omics.utils import write_json

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
SHA_1 = "1" * 64
SHA_2 = "2" * 64
SHA_3 = "3" * 64
SHA_4 = "4" * 64
SHA_5 = "5" * 64
SHA_6 = "6" * 64
SHA_7 = "7" * 64
SHA_8 = "8" * 64


def freeze_receipt(artifacts: dict[str, tuple[str, str, str, int]]) -> dict:
    return {
        "schema_version": 1,
        "status": "passed",
        "object_count": len(artifacts),
        "objects": [
            {
                "status": "passed",
                "checks": {
                    "content_length_matches": True,
                    "crc64nvme_matches": True,
                    "crc64nvme_present": True,
                    "destination_bucket_matches": True,
                    "destination_kms_key_matches": True,
                    "destination_sse_kms": True,
                    "destination_versioned": True,
                },
                "destination": {
                    "uri": f"s3://private-cache/{artifact}",
                    "version_id": version,
                    "bytes": bytes_,
                    "crc64nvme": crc,
                    "etag": f'"{artifact}"',
                    "kms_key_id": "arn:aws:kms:us-east-1:111111111111:key/test",
                },
            }
            for artifact, (_sha, version, crc, bytes_) in artifacts.items()
        ],
    }


def sha_receipt(artifacts: dict[str, tuple[str, str, str, int]]) -> dict:
    return {
        "schema_version": 1,
        "status": "passed",
        "object_count": len(artifacts),
        "objects": [
            {
                "artifact": artifact,
                "status": "passed",
                "sha256": sha,
                "version_id": version,
                "bytes": bytes_,
                "crc64nvme": crc,
                "server_side_encryption": "aws:kms",
                "kms_key_id": "arn:aws:kms:us-east-1:111111111111:key/test",
            }
            for artifact, (sha, version, crc, bytes_) in artifacts.items()
        ],
    }


def resource_receipt() -> dict:
    sha_by_artifact = {
        "common_sites_index": SHA_1,
        "common_sites_vcf": SHA_2,
        "gatk_jar": SHA_3,
        "germline_resource_index": SHA_4,
        "germline_resource_vcf": SHA_5,
        "mutect2_interval_set": SHA_6,
        "panel_of_normals_index": SHA_7,
        "panel_of_normals_vcf": SHA_8,
    }
    return {
        "schema_version": 1,
        "status": "passed",
        "checks": {
            "common_sites_index_matches_vcf": True,
            "germline_resource_index_matches_vcf": True,
            "panel_of_normals_index_matches_vcf": True,
        },
        "objects": [
            {
                "artifact": artifact,
                "bytes": index + 1,
                "server_side_encryption": "aws:kms",
                "sha256": sha,
                "status": "passed",
                "uri": f"s3://private-cache/resources/{artifact}",
                "version_id": f"{artifact}-version",
            }
            for index, (artifact, sha) in enumerate(sha_by_artifact.items())
        ],
    }


def bam_validation_receipt() -> dict:
    return {
        "schema_version": 1,
        "status": "passed",
        "checks": {
            "bam_bai_pairing": True,
            "reference_contigs_match": True,
            "sample_names_match_manifest": True,
            "samtools_quickcheck": True,
        },
        "samples": {
            "normal": {
                "role": "normal",
                "sample_id": "subject01_normal",
                "bam_artifact": "normal.markdup.bam",
                "bai_artifact": "normal.markdup.bam.bai",
                "bam": {
                    "artifact": "normal.markdup.bam",
                    "sha256": SHA_A,
                    "version_id": "normal-bam-version",
                },
                "bai": {
                    "artifact": "normal.markdup.bam.bai",
                    "sha256": SHA_B,
                    "version_id": "normal-bai-version",
                },
                "samtools_quickcheck": {
                    "status": "passed",
                    "stderr_sha256": SHA_B,
                },
            },
            "tumor": {
                "role": "tumor",
                "sample_id": "subject01_tumor",
                "bam_artifact": "tumor.markdup.bam",
                "bai_artifact": "tumor.markdup.bam.bai",
                "bam": {
                    "artifact": "tumor.markdup.bam",
                    "sha256": SHA_C,
                    "version_id": "tumor-bam-version",
                },
                "bai": {
                    "artifact": "tumor.markdup.bam.bai",
                    "sha256": SHA_D,
                    "version_id": "tumor-bai-version",
                },
                "samtools_quickcheck": {
                    "status": "passed",
                    "stderr_sha256": SHA_C,
                },
            },
        },
    }


def contig_compatibility_receipt() -> dict:
    return {
        "schema_version": 1,
        "status": "passed",
        "reference_sequence_dictionary_sha256": SHA_E,
        "checks": {
            "bam_fasta_contigs_compatible": True,
            "common_sites_contigs_compatible": True,
            "germline_resource_contigs_compatible": True,
            "intervals_on_reference": True,
            "panel_of_normals_contigs_compatible": True,
        },
    }


def receipts() -> tuple[dict, dict, dict, dict, dict, dict, dict]:
    private = {
        "normal.markdup.bam": (SHA_A, "normal-bam-version", "normal-bam-crc", 13),
        "normal.markdup.bam.bai": (SHA_B, "normal-bai-version", "normal-bai-crc", 11),
        "tumor.markdup.bam": (SHA_C, "tumor-bam-version", "tumor-bam-crc", 17),
        "tumor.markdup.bam.bai": (SHA_D, "tumor-bai-version", "tumor-bai-crc", 19),
    }
    reference = {
        "reference.dict": (SHA_E, "dict-version", "dict-crc", 23),
        "reference.fa": (SHA_F, "fasta-version", "fasta-crc", 29),
        "reference.fa.fai": (SHA_1, "fai-version", "fai-crc", 31),
    }
    return (
        freeze_receipt(private),
        sha_receipt(private),
        freeze_receipt(reference),
        sha_receipt(reference),
        bam_validation_receipt(),
        contig_compatibility_receipt(),
        resource_receipt(),
    )


def metadata() -> dict[str, str]:
    return {
        "source_commit": "abcd1234",
        "parameter_sha256": SHA_2,
        "parabricks_container": (
            "172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@sha256:" + SHA_3
        ),
        "parabricks_container_digest": "sha256:" + SHA_3,
        "parabricks_version": "4.5.1-1",
        "sequenza_female": "true",
    }


def write_environment_receipts(root: Path) -> dict[str, Path]:
    private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
    receipt_paths = {
        "PHASE3_WGS_FAST_PRIVATE_FREEZE_RECEIPT": root / "private-freeze.json",
        "PHASE3_WGS_FAST_PRIVATE_SHA256_RECEIPT": root / "private-sha256.json",
        "PHASE3_WGS_FAST_REFERENCE_FREEZE_RECEIPT": root / "reference-freeze.json",
        "PHASE3_WGS_FAST_REFERENCE_SHA256_RECEIPT": root / "reference-sha256.json",
        "PHASE3_WGS_FAST_BAM_VALIDATION_RECEIPT": root / "bam-validation.json",
        "PHASE3_WGS_FAST_CONTIG_COMPATIBILITY_RECEIPT": root / "contig-compatibility.json",
        "PHASE3_WGS_FAST_CALLER_RESOURCE_RECEIPT": root / "caller-resources.json",
    }
    for path, payload in zip(
        receipt_paths.values(),
        (private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources),
    ):
        write_json(path, payload)
    return receipt_paths


def input_manifest_environment(receipt_paths: dict[str, Path], output: Path) -> dict[str, str]:
    return {
        **{key: str(path) for key, path in receipt_paths.items()},
        "PHASE3_WGS_FAST_OUTPUT": str(output),
        "PHASE3_WGS_FAST_PARAMETER_SHA256": SHA_2,
        "PHASE3_WGS_FAST_PARABRICKS_CONTAINER": (
            "172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@sha256:" + SHA_3
        ),
        "PHASE3_WGS_FAST_PARABRICKS_CONTAINER_DIGEST": "sha256:" + SHA_3,
        "PHASE3_WGS_FAST_PARABRICKS_VERSION": "4.5.1-1",
        "PHASE3_WGS_FAST_SEQUENZA_FEMALE": "true",
        "PHASE3_WGS_FAST_SOURCE_COMMIT": "abcd1234",
    }


class Phase3FastInputManifestTests(unittest.TestCase):
    def build_manifest(self) -> dict:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        return render.build_phase3_wgs_fast_input_manifest(
            private_freeze_receipt=private_freeze,
            private_sha256_receipt=private_sha,
            reference_freeze_receipt=reference_freeze,
            reference_sha256_receipt=reference_sha,
            bam_validation_receipt=validation,
            contig_compatibility_receipt=contigs,
            caller_resource_receipt=resources,
            metadata=metadata(),
        )

    def test_manifest_binds_versioned_bam_reference_and_resource_inputs(self) -> None:
        manifest = self.build_manifest()

        self.assertEqual(manifest["status"], "ready")
        self.assertEqual(manifest["run"]["run_id"], "diana-wgs-hrd-20260716T033101Z")
        self.assertEqual(manifest["bam_pair"]["tumor"]["bam"]["sha256"], SHA_C)
        self.assertEqual(manifest["bam_pair"]["tumor"]["sample_id"], "subject01_tumor")
        self.assertEqual(manifest["bam_pair"]["tumor"]["bai"]["version_id"], "tumor-bai-version")
        self.assertEqual(manifest["bam_pair"]["tumor"]["samtools_quickcheck"]["stderr_sha256"], SHA_C)
        self.assertEqual(manifest["reference"]["sequence_dictionary_sha256"], SHA_E)
        self.assertEqual(manifest["caller_resources"]["panel_of_normals_vcf"]["sha256"], SHA_8)
        self.assertEqual(manifest["runtime"]["parabricks_container_digest"], "sha256:" + SHA_3)
        self.assertEqual({"sequenza": {"female": True}}, manifest["method_parameters"])
        self.assertEqual(manifest["validation"]["bam"]["samples"]["tumor"]["bam"]["sha256"], SHA_C)
        self.assertTrue(manifest["validation"]["contig_compatibility"]["checks"]["panel_of_normals_contigs_compatible"])
        self.assertEqual(manifest["interpretation"]["authorized_hrd_state"], "no_call")
        self.assertIn("scarHRD", manifest["interpretation"]["required_no_call_policy"])

    def test_missing_private_sha256_fails_closed(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        private_sha["objects"][0].pop("sha256")

        with self.assertRaisesRegex(render.ManifestError, "sha256"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=metadata(),
            )

    def test_null_private_version_fails_closed(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        private_sha["objects"][1]["version_id"] = "null"

        with self.assertRaisesRegex(render.ManifestError, "version_id"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=metadata(),
            )

    def test_missing_bam_index_mate_fails_closed(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        private_freeze["objects"] = private_freeze["objects"][:-1]
        private_freeze["object_count"] = len(private_freeze["objects"])

        with self.assertRaisesRegex(render.ManifestError, "expected exact artifacts"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=metadata(),
            )

    def test_source_receipt_object_counts_must_be_exact_integers(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        private_freeze["object_count"] = float(len(private_freeze["objects"]))

        with self.assertRaisesRegex(render.ManifestError, "object_count"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=metadata(),
            )

    def test_source_receipt_bytes_must_be_exact_positive_integers(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        private_freeze["objects"][0]["destination"]["bytes"] = 13.0

        with self.assertRaisesRegex(render.ManifestError, "positive integer"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=metadata(),
            )

        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        resources["objects"][0]["bytes"] = True

        with self.assertRaisesRegex(render.ManifestError, "positive integer"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=metadata(),
            )

    def test_malformed_caller_resource_sha_fails_closed(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        resources["objects"][0]["sha256"] = "not-a-sha"

        with self.assertRaisesRegex(render.ManifestError, "caller resource common_sites_index sha256"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=metadata(),
            )

    def test_failed_quickcheck_fails_closed(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        validation["samples"]["tumor"]["samtools_quickcheck"]["status"] = "failed"

        with self.assertRaisesRegex(render.ManifestError, "quickcheck"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=metadata(),
            )

    def test_sample_metadata_must_match_bam_validation_receipt(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        mismatched_metadata = {**metadata(), "tumor_sample_id": "wrong_tumor"}

        with self.assertRaisesRegex(render.ManifestError, "tumor_sample_id"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=mismatched_metadata,
            )

    def test_sequenza_sex_model_must_be_explicit(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        incomplete_metadata = metadata()
        incomplete_metadata.pop("sequenza_female")

        with self.assertRaisesRegex(render.ManifestError, "sequenza_female"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=incomplete_metadata,
            )

    def test_parabricks_container_digest_must_match_container(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        mismatched_metadata = {
            **metadata(),
            "parabricks_container": (
                "172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@sha256:"
                + "9" * 64
            ),
        }

        with self.assertRaisesRegex(render.ManifestError, "parabricks_container_digest must match parabricks_container"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=mismatched_metadata,
            )

    def test_sequenza_sex_model_must_be_boolean(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        malformed_metadata = {**metadata(), "sequenza_female": "unknown"}

        with self.assertRaisesRegex(render.ManifestError, "explicitly true or false"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=malformed_metadata,
            )

    def test_bam_validation_must_match_frozen_object_identity(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        validation["samples"]["tumor"]["bam"]["sha256"] = SHA_4

        with self.assertRaisesRegex(render.ManifestError, "sha256"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=metadata(),
            )

    def test_failed_contig_compatibility_fails_closed(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        contigs["checks"]["panel_of_normals_contigs_compatible"] = False

        with self.assertRaisesRegex(render.ManifestError, "panel_of_normals"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=metadata(),
            )

    def test_failed_resource_index_pairing_fails_closed(self) -> None:
        private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
        resources["checks"]["germline_resource_index_matches_vcf"] = False

        with self.assertRaisesRegex(render.ManifestError, "germline_resource_index_matches_vcf"):
            render.build_phase3_wgs_fast_input_manifest(
                private_freeze_receipt=private_freeze,
                private_sha256_receipt=private_sha,
                reference_freeze_receipt=reference_freeze,
                reference_sha256_receipt=reference_sha,
                bam_validation_receipt=validation,
                contig_compatibility_receipt=contigs,
                caller_resource_receipt=resources,
                metadata=metadata(),
            )

    def test_environment_command_writes_source_bound_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt_paths = write_environment_receipts(root)
            output = root / "input-manifest.json"

            with patch.dict(
                "os.environ",
                input_manifest_environment(receipt_paths, output),
                clear=False,
            ):
                manifest, manifest_path = render.load_manifest_from_environment()
                render.write_manifest(manifest_path, manifest)

            self.assertEqual(output, manifest_path)
            written = output.read_text(encoding="utf-8")
            self.assertIn('"manifest_type": "phase3_wgs_fast_input_manifest"', written)
            self.assertIn('"bam_validation"', written)
            self.assertIn('"contig_compatibility"', written)

    def test_environment_command_rejects_redirected_source_receipt(self) -> None:
        for bad_kind in ("missing", "directory", "symlink"):
            with self.subTest(bad_kind=bad_kind), TemporaryDirectory() as tmp:
                root = Path(tmp)
                receipt_paths = write_environment_receipts(root)
                real_receipt = receipt_paths["PHASE3_WGS_FAST_PRIVATE_FREEZE_RECEIPT"]
                bad_receipt = root / f"bad-private-freeze-{bad_kind}.json"
                if bad_kind == "directory":
                    bad_receipt.mkdir()
                elif bad_kind == "symlink":
                    bad_receipt.symlink_to(real_receipt)
                receipt_paths["PHASE3_WGS_FAST_PRIVATE_FREEZE_RECEIPT"] = bad_receipt

                with patch.dict(
                    "os.environ",
                    input_manifest_environment(receipt_paths, root / "input-manifest.json"),
                    clear=False,
                ):
                    with self.assertRaisesRegex(render.ManifestError, "private_freeze receipt"):
                        render.load_manifest_from_environment()


if __name__ == "__main__":
    unittest.main()
