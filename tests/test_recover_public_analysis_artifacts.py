from __future__ import annotations

import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/recover_public_analysis_artifacts.py"
)
SPEC = importlib.util.spec_from_file_location(
    "recover_public_analysis_artifacts", SCRIPT
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RecoverPublicAnalysisArtifactsTests(unittest.TestCase):
    def test_selected_early_look_keeps_public_analysis_and_excludes_raw_artifacts(
        self,
    ) -> None:
        for relative in (
            "artifacts/README.md",
            "artifacts/qc/tumor.flagstat.txt",
            "artifacts/coverage_cnv/coverage_cnv_summary.json",
            "artifacts/contamination/contamination.table",
            "artifacts/variants/core_hrr_pass_variants.csv",
            "handoff/VARIANT_REVIEW.tsv",
            "handoff/annotations/core_hrr.mutect2.filtered.ensembl116.vcf.gz",
        ):
            with self.subTest(relative=relative):
                self.assertTrue(MODULE.selected_early_look(relative))

        for relative in (
            "artifacts/variants/diana.wgs.mutect2.filtered.vcf.gz",
            "artifacts/contamination/tumor.pileups.table",
            "inputs/validated_bams/tumor.markdup.bam",
            "handoff/provenance/aws_batch_jobs.json",
            "artifacts/qc/../../../../escaped.txt",
            "artifacts/variants/../../../../core_hrr_pass_variants.csv",
            "/artifacts/qc/tumor.flagstat.txt",
            "artifacts/qc/./tumor.flagstat.txt",
        ):
            with self.subTest(relative=relative):
                self.assertFalse(MODULE.selected_early_look(relative))

    def test_materialize_source_rewrites_gzipped_vcf_sample_identifiers(
        self,
    ) -> None:
        raw_vcf = gzip.compress(
            b"##fileformat=VCFv4.2\n"
            b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t"
            b"DRF-PSN49561_tumor\tDRF-PSN49561_normal\n"
            b"chr17\t43115780\t.\tC\tT\t.\tPASS\t.\tGT\t0/1\t0/0\n"
        )
        source = {
            "bucket": "source-bucket",
            "key": "preserved/artifacts/variants/core_hrr.mutect2.filtered.vcf.gz",
            "bytes": len(raw_vcf),
            "checksum_crc64nvme": "crc64",
        }

        def fake_download(_: dict[str, object], path: Path) -> bytes:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw_vcf)
            return raw_vcf

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE, "download", side_effect=fake_download
        ), mock.patch.object(MODULE, "bgzip", side_effect=gzip.compress):
            staged = MODULE.materialize_source(
                source,
                MODULE.DESTINATION_PREFIX
                + "early-look/artifacts/variants/core_hrr.mutect2.filtered.vcf.gz",
                Path(temporary),
            )
            rewritten = gzip.decompress(Path(staged["path"]).read_bytes())

        self.assertIn(b"subject01_tumor", rewritten)
        self.assertIn(b"subject01_normal", rewritten)
        self.assertNotIn(b"DRF-PSN49561", rewritten)
        self.assertTrue(staged["transformed"])

    def test_materialize_source_rejects_destination_traversal_without_downloading(
        self,
    ) -> None:
        source = {
            "bucket": "source-bucket",
            "key": "preserved/artifacts/qc/escaped.txt",
            "bytes": len(b"public\n"),
            "checksum_crc64nvme": "crc64",
        }

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE, "download", return_value=b"public\n"
        ) as download:
            with self.assertRaisesRegex(ValueError, "destination key is unsafe"):
                MODULE.materialize_source(
                    source,
                    MODULE.DESTINATION_PREFIX
                    + "early-look/artifacts/qc/../../../../escaped.txt",
                    Path(temporary),
                )

            download.assert_not_called()
            self.assertFalse((Path(temporary) / "escaped.txt").exists())

    def test_materialize_source_rejects_forbidden_text_identifiers(self) -> None:
        raw = b"# Personalis Echo handoff\n"
        source = {
            "bucket": "source-bucket",
            "key": "preserved/artifacts/README.md",
            "bytes": len(raw),
            "checksum_crc64nvme": "crc64",
        }

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE, "download", return_value=raw
        ):
            with self.assertRaisesRegex(ValueError, "forbidden identifiers"):
                MODULE.materialize_source(
                    source,
                    MODULE.DESTINATION_PREFIX + "early-look/artifacts/README.md",
                    Path(temporary),
                )

    def test_public_upload_pins_exact_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            payload = b"# public recovery\n"
            path = Path(temporary) / "README.md"
            path.write_bytes(payload)
            digest = MODULE.hashlib.sha256(payload).hexdigest()
            item = {
                "source": {
                    "bucket": "source-bucket",
                    "key": "source-key",
                    "checksum_crc64nvme": "crc64",
                },
                "destination_key": MODULE.DESTINATION_PREFIX + "README.md",
                "path": str(path),
                "bytes": len(payload),
                "sha256": digest,
                "content_type": "text/markdown; charset=utf-8",
                "transformed": False,
            }
            metadata = {
                "classification": MODULE.CLASSIFICATION,
                "sha256": digest,
                "source-crc64nvme": "crc64",
            }
            head_response = {
                "ContentLength": len(payload),
                "ChecksumSHA256": MODULE.checksum_sha256(digest),
                "ChecksumType": "FULL_OBJECT",
                "ServerSideEncryption": "AES256",
                "VersionId": "v1",
                "Metadata": metadata,
            }

            with (
                mock.patch.object(
                    MODULE, "aws_json", return_value={"VersionId": "v1"}
                ) as aws_json,
                mock.patch.object(MODULE, "head", return_value=head_response),
            ):
                self.assertEqual(
                    MODULE.upload(item),
                    {
                        "version_id": "v1",
                        "checks": {
                            "bytes": True,
                            "checksum": True,
                            "checksum_type": True,
                            "encryption": True,
                            "version": True,
                            "metadata": True,
                        },
                    },
                )

        self.assertEqual(
            aws_json.call_args.args,
            (
                "s3api",
                "put-object",
                "--bucket",
                MODULE.DESTINATION_BUCKET,
                "--key",
                item["destination_key"],
                "--body",
                str(path),
                "--content-type",
                item["content_type"],
                "--server-side-encryption",
                "AES256",
                "--checksum-algorithm",
                "SHA256",
                "--checksum-sha256",
                MODULE.checksum_sha256(digest),
                "--metadata",
                json.dumps(metadata, sort_keys=True, separators=(",", ":")),
            ),
        )

    def test_public_upload_rejects_missing_classification_or_source_crc_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            payload = b"# public recovery\n"
            path = Path(temporary) / "README.md"
            path.write_bytes(payload)
            digest = MODULE.hashlib.sha256(payload).hexdigest()
            item = {
                "source": {
                    "bucket": "source-bucket",
                    "key": "source-key",
                    "checksum_crc64nvme": "crc64",
                },
                "destination_key": MODULE.DESTINATION_PREFIX + "README.md",
                "path": str(path),
                "bytes": len(payload),
                "sha256": digest,
                "content_type": "text/markdown; charset=utf-8",
                "transformed": False,
            }
            head_response = {
                "ContentLength": len(payload),
                "ChecksumSHA256": MODULE.checksum_sha256(digest),
                "ChecksumType": "FULL_OBJECT",
                "ServerSideEncryption": "AES256",
                "VersionId": "v1",
                "Metadata": {"sha256": digest},
            }

            with (
                mock.patch.object(
                    MODULE, "aws_json", return_value={"VersionId": "v1"}
                ),
                mock.patch.object(MODULE, "head", return_value=head_response),
                self.assertRaisesRegex(ValueError, "destination verification failed"),
            ):
                MODULE.upload(item)

    def test_private_receipt_rejects_output_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            (real_parent / "existing").mkdir()

            for path in (
                linked_parent / "missing" / "receipt.json",
                linked_parent / "existing" / "receipt.json",
            ):
                with self.subTest(path=path):
                    with self.assertRaisesRegex(
                        ValueError,
                        "parent may not be a symlink",
                    ):
                        MODULE.write_private(
                            path, {"status": "redirected"}, create=True
                        )

            self.assertFalse((real_parent / "missing" / "receipt.json").exists())
            self.assertFalse((real_parent / "existing" / "receipt.json").exists())

    def test_private_receipt_fsyncs_file_and_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"

            with mock.patch.object(
                MODULE.os,
                "fsync",
                wraps=MODULE.os.fsync,
            ) as fsync:
                MODULE.write_private(receipt, {"status": "observing"}, create=True)

            self.assertEqual(fsync.call_count, 2)

    def test_private_receipt_removes_partial_after_file_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"

            with (
                mock.patch.object(
                    MODULE.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                MODULE.write_private(receipt, {"status": "observing"}, create=True)

            self.assertFalse(receipt.exists())

    def test_private_receipt_removes_partial_after_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"

            with (
                mock.patch.object(
                    MODULE.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                MODULE.write_private(receipt, {"status": "observing"}, create=True)

            self.assertFalse(receipt.exists())

    def test_private_receipt_replacement_fsyncs_parent_after_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            MODULE.write_private(receipt, {"status": "observing"}, create=True)

            with mock.patch.object(
                MODULE,
                "fsync_directory",
                wraps=MODULE.fsync_directory,
            ) as fsync_directory:
                MODULE.write_private(receipt, {"status": "ready"}, create=False)

            fsync_directory.assert_called_once_with(receipt.parent)
            self.assertEqual(
                json.loads(receipt.read_text(encoding="utf-8")),
                {"status": "ready"},
            )

    def test_main_rejects_receipt_symlink_parent_before_aws_observation(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            real_parent = root / "real-parent"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            path = linked_parent / "existing" / "receipt.json"

            with (
                mock.patch(
                    "sys.argv",
                    [
                        "recover_public_analysis_artifacts.py",
                        "--receipt-output",
                        str(path),
                    ],
                ),
                mock.patch.object(MODULE, "aws_json") as mocked_aws,
                self.assertRaisesRegex(SystemExit, "parent may not be a symlink"),
            ):
                MODULE.main()

            mocked_aws.assert_not_called()


if __name__ == "__main__":
    unittest.main()
