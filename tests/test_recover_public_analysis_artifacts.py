from __future__ import annotations

import ast
import gzip
import importlib.util
import json
import subprocess
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

    def test_materialize_source_rejects_symlinked_public_output_parent(
        self,
    ) -> None:
        source = {
            "bucket": "source-bucket",
            "key": "preserved/artifacts/qc/tumor.flagstat.txt",
            "bytes": len(b"public\n"),
            "checksum_crc64nvme": "crc64",
        }

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE, "download", return_value=b"public\n"
        ):
            root = Path(temporary)
            real_public = root / "real-public"
            real_public.mkdir()
            (root / "public").symlink_to(real_public, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.materialize_source(
                    source,
                    MODULE.DESTINATION_PREFIX
                    + "early-look/artifacts/qc/tumor.flagstat.txt",
                    root,
                )

            self.assertFalse(
                (real_public / "early-look/artifacts/qc/tumor.flagstat.txt").exists()
            )

    def test_generated_object_rejects_symlinked_public_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_public = root / "real-public"
            real_public.mkdir()
            (root / "public").symlink_to(real_public, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.generated_object(
                    root,
                    "publication_manifest.json",
                    b'{"status": "public"}\n',
                )

            self.assertFalse((real_public / "publication_manifest.json").exists())

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

    def test_public_manifest_rows_omit_private_source_locations(self) -> None:
        source = {
            "bucket": "private-source-bucket",
            "key": "private/source/key.json",
            "bytes": 123,
            "checksum_crc64nvme": "private-crc64",
        }
        items = [
            {
                "source": source,
                "destination_key": MODULE.DESTINATION_PREFIX
                + "early-look/artifacts/summary.json",
                "bytes": 42,
                "sha256": "a" * 64,
                "transformed": True,
            },
            {
                "source": None,
                "destination_key": MODULE.DESTINATION_PREFIX + "README.md",
                "bytes": 12,
                "sha256": "b" * 64,
                "transformed": False,
            },
        ]

        self.assertEqual(
            MODULE.publication_manifest_rows(items),
            [
                {
                    "destination_key": MODULE.DESTINATION_PREFIX + "README.md",
                    "bytes": 12,
                    "sha256": "b" * 64,
                    "transformed": False,
                },
                {
                    "destination_key": MODULE.DESTINATION_PREFIX
                    + "early-look/artifacts/summary.json",
                    "bytes": 42,
                    "sha256": "a" * 64,
                    "transformed": True,
                },
            ],
        )
        self.assertEqual(MODULE.private_receipt_source(source), source)
        self.assertIsNone(MODULE.private_receipt_source(None))

        manifest = MODULE.canonical_bytes(
            {
                "schema_version": 1,
                "objects": MODULE.publication_manifest_rows(items),
            }
        )
        self.assertNotIn(b"private-source-bucket", manifest)
        self.assertNotIn(b"private/source/key", manifest)
        self.assertNotIn(b"private-crc64", manifest)

    def test_inventory_total_bytes_requires_exact_s3_sizes(self) -> None:
        self.assertEqual(
            MODULE.inventory_total_bytes(
                [
                    {"Key": MODULE.WORK_PREFIX + "a.json", "Size": 12},
                    {"Key": MODULE.WORK_PREFIX + "b.json", "Size": 30},
                ],
                "preserved early-look",
            ),
            42,
        )

        for value in (True, 42.0, "42", -1, None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "exact nonnegative S3 size"):
                    MODULE.inventory_total_bytes(
                        [{"Key": MODULE.WORK_PREFIX + "a.json", "Size": value}],
                        "preserved early-look",
                    )

    def test_object_inventory_requires_exact_s3_keys(self) -> None:
        self.assertEqual(
            MODULE.inventory_total_bytes(
                [{"Key": MODULE.WORK_PREFIX + "a.json", "Size": 42}],
                "preserved early-look",
            ),
            42,
        )
        for value in (True, 1, 1.0, "", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "exact nonempty S3 key"):
                    MODULE.inventory_total_bytes(
                        [{"Key": value, "Size": 42}],
                        "preserved early-look",
                    )

    def test_list_objects_rejects_malformed_rows_without_sort_coercion(self) -> None:
        cases = (
            ("boolean Key", {"Contents": [{"Key": True, "Size": 1}]}, "S3 key"),
            ("empty Key", {"Contents": [{"Key": "", "Size": 1}]}, "S3 key"),
            (
                "float Size",
                {"Contents": [{"Key": MODULE.WORK_PREFIX + "a.json", "Size": 1.0}]},
                "S3 size",
            ),
        )
        for label, payload, expected_error in cases:
            with self.subTest(label=label):
                with (
                    mock.patch.object(MODULE, "aws_json", return_value=payload),
                    self.assertRaisesRegex(ValueError, expected_error),
                ):
                    MODULE.list_objects(MODULE.WORK_BUCKET, MODULE.WORK_PREFIX)

    def test_list_objects_sort_avoids_raw_string_coercion(self) -> None:
        module = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        parent_by_child = {
            child: parent
            for parent in ast.walk(module)
            for child in ast.iter_child_nodes(parent)
        }

        def in_list_objects(node: ast.AST) -> bool:
            parent = parent_by_child.get(node)
            while parent is not None:
                if isinstance(parent, ast.FunctionDef):
                    return parent.name == "list_objects"
                parent = parent_by_child.get(parent)
            return False

        raw_string_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and in_list_objects(node)
        ]

        self.assertEqual(raw_string_coercions, [])

    def test_exact_version_id_rejects_non_string_or_null_versions(self) -> None:
        self.assertEqual(
            MODULE.exact_version_id("version-1", "upload VersionId"),
            "version-1",
        )

        for value in (True, 1, 1.0, "", "null", None):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "non-null S3 VersionId"),
            ):
                MODULE.exact_version_id(value, "upload VersionId")

    def test_exact_crc64nvme_rejects_non_string_checksums(self) -> None:
        self.assertEqual(
            MODULE.exact_crc64nvme("crc64", "source ChecksumCRC64NVME"),
            "crc64",
        )

        for value in (True, 1, 1.0, "", None):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "exact CRC64NVME"),
            ):
                MODULE.exact_crc64nvme(value, "source ChecksumCRC64NVME")

    def test_source_evidence_requires_exact_s3_sizes(self) -> None:
        head = {
            "ContentLength": 42,
            "ChecksumCRC64NVME": "crc64",
            "ChecksumType": "FULL_OBJECT",
            "ContentType": "application/json",
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": MODULE.EXPECTED_KMS_KEY,
        }

        with mock.patch.object(MODULE, "head", return_value=head):
            self.assertEqual(
                MODULE.source_evidence(
                    "source-bucket",
                    {"Key": MODULE.WORK_PREFIX + "a.json", "Size": 42},
                ),
                {
                    "bucket": "source-bucket",
                    "key": MODULE.WORK_PREFIX + "a.json",
                    "bytes": 42,
                    "checksum_crc64nvme": "crc64",
                    "content_type": "application/json",
                },
            )

        cases = (
            (
                "listing bool",
                {"Key": MODULE.WORK_PREFIX + "a.json", "Size": True},
                head,
            ),
            (
                "listing float",
                {"Key": MODULE.WORK_PREFIX + "a.json", "Size": 42.0},
                head,
            ),
            (
                "listing string",
                {"Key": MODULE.WORK_PREFIX + "a.json", "Size": "42"},
                head,
            ),
            (
                "head bool",
                {"Key": MODULE.WORK_PREFIX + "a.json", "Size": 42},
                {**head, "ContentLength": True},
            ),
            (
                "head float",
                {"Key": MODULE.WORK_PREFIX + "a.json", "Size": 42},
                {**head, "ContentLength": 42.0},
            ),
            (
                "head string",
                {"Key": MODULE.WORK_PREFIX + "a.json", "Size": 42},
                {**head, "ContentLength": "42"},
            ),
        )
        for label, row, head_response in cases:
            with (
                self.subTest(label=label),
                mock.patch.object(MODULE, "head", return_value=head_response),
                self.assertRaisesRegex(ValueError, "exact nonnegative S3 size"),
            ):
                MODULE.source_evidence("source-bucket", row)

    def test_source_evidence_requires_exact_s3_key(self) -> None:
        for value in (True, 1, 1.0, "", None):
            with (
                self.subTest(value=value),
                mock.patch.object(
                    MODULE,
                    "head",
                    side_effect=AssertionError("HEAD called"),
                ),
                self.assertRaisesRegex(ValueError, "exact nonempty S3 key"),
            ):
                MODULE.source_evidence("source-bucket", {"Key": value, "Size": 42})

    def test_source_evidence_requires_exact_crc64nvme_checksum(self) -> None:
        head = {
            "ContentLength": 42,
            "ChecksumCRC64NVME": "crc64",
            "ChecksumType": "FULL_OBJECT",
            "ContentType": "application/json",
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": MODULE.EXPECTED_KMS_KEY,
        }

        for value in (True, 1, 1.0, "", None):
            with (
                self.subTest(value=value),
                mock.patch.object(
                    MODULE,
                    "head",
                    return_value={**head, "ChecksumCRC64NVME": value},
                ),
                self.assertRaisesRegex(ValueError, "exact CRC64NVME"),
            ):
                MODULE.source_evidence(
                    "source-bucket",
                    {"Key": MODULE.WORK_PREFIX + "a.json", "Size": 42},
                )

    def test_download_rejects_symlinked_output_before_aws(self) -> None:
        source = {
            "bucket": "source-bucket",
            "key": "preserved/artifacts/README.md",
            "bytes": len(b"public\n"),
            "checksum_crc64nvme": "crc64",
        }

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE.subprocess, "run"
        ) as run:
            root = Path(temporary)
            target = root / "redirected.txt"
            target.write_text("private\n", encoding="utf-8")
            output = root / "download.txt"
            output.symlink_to(target)

            with self.assertRaisesRegex(ValueError, "may not be a symlink"):
                MODULE.download(source, output)

            run.assert_not_called()
            self.assertEqual(target.read_text(encoding="utf-8"), "private\n")

    def test_download_rejects_symlinked_output_parent_before_aws(self) -> None:
        source = {
            "bucket": "source-bucket",
            "key": "preserved/artifacts/README.md",
            "bytes": len(b"public\n"),
            "checksum_crc64nvme": "crc64",
        }

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE.subprocess, "run"
        ) as run:
            root = Path(temporary)
            real_parent = root / "real-downloads"
            real_parent.mkdir()
            linked_parent = root / "downloads"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.download(source, linked_parent / "download.txt")

            run.assert_not_called()
            self.assertFalse((real_parent / "download.txt").exists())

    def test_download_rejects_symlink_swap_before_readback(self) -> None:
        source = {
            "bucket": "source-bucket",
            "key": "preserved/artifacts/README.md",
            "bytes": len(b"public\n"),
            "checksum_crc64nvme": "crc64",
        }

        def create_symlink(
            command: list[str],
            **_: object,
        ) -> subprocess.CompletedProcess[str]:
            output = Path(command[-1])
            redirected = output.with_name("redirected.txt")
            redirected.write_bytes(b"public\n")
            output.symlink_to(redirected)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='{"ChecksumCRC64NVME": "crc64"}\n',
                stderr="",
            )

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE.subprocess,
            "run",
            side_effect=create_symlink,
        ):
            with self.assertRaisesRegex(ValueError, "may not be a symlink"):
                MODULE.download(source, Path(temporary) / "download.txt")

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

    def test_public_upload_rejects_missing_classification_metadata(
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

    def test_public_upload_requires_exact_destination_content_length(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            payload = b"# public recovery\n"
            path = Path(temporary) / "README.md"
            path.write_bytes(payload)
            digest = MODULE.hashlib.sha256(payload).hexdigest()
            item = {
                "source": None,
                "destination_key": MODULE.DESTINATION_PREFIX + "README.md",
                "path": str(path),
                "bytes": len(payload),
                "sha256": digest,
                "content_type": "text/markdown; charset=utf-8",
                "transformed": False,
            }

            for value in (True, float(len(payload)), str(len(payload))):
                with (
                    self.subTest(value=value),
                    mock.patch.object(
                        MODULE, "aws_json", return_value={"VersionId": "v1"}
                    ),
                    mock.patch.object(
                        MODULE,
                        "head",
                        return_value={
                            "ContentLength": value,
                            "ChecksumSHA256": MODULE.checksum_sha256(digest),
                            "ChecksumType": "FULL_OBJECT",
                            "ServerSideEncryption": "AES256",
                            "VersionId": "v1",
                            "Metadata": {
                                "classification": MODULE.CLASSIFICATION,
                                "sha256": digest,
                            },
                        },
                    ),
                    self.assertRaisesRegex(ValueError, "exact nonnegative S3 size"),
                ):
                    MODULE.upload(item)

    def test_public_upload_requires_exact_put_version_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            payload = b"# public recovery\n"
            path = Path(temporary) / "README.md"
            path.write_bytes(payload)
            digest = MODULE.hashlib.sha256(payload).hexdigest()
            item = {
                "source": None,
                "destination_key": MODULE.DESTINATION_PREFIX + "README.md",
                "path": str(path),
                "bytes": len(payload),
                "sha256": digest,
                "content_type": "text/markdown; charset=utf-8",
                "transformed": False,
            }

            for value in (True, 1, 1.0, "", "null", None):
                with (
                    self.subTest(value=value),
                    mock.patch.object(
                        MODULE,
                        "aws_json",
                        return_value={"VersionId": value},
                    ),
                    mock.patch.object(MODULE, "head") as mocked_head,
                    self.assertRaisesRegex(ValueError, "non-null S3 VersionId"),
                ):
                    MODULE.upload(item)

                mocked_head.assert_not_called()

    def test_final_destination_history_binds_uploaded_versions_and_sizes(
        self,
    ) -> None:
        records = [
            {
                "destination_key": MODULE.DESTINATION_PREFIX + "README.md",
                "bytes": 14,
                "upload": {"version_id": "readme-version"},
            },
            {
                "destination_key": MODULE.DESTINATION_PREFIX
                + "early-look/artifacts/summary.json",
                "bytes": 21,
                "upload": {"version_id": "summary-version"},
            },
        ]
        versions = [
            {
                "Key": MODULE.DESTINATION_PREFIX
                + "early-look/artifacts/summary.json",
                "VersionId": "summary-version",
                "Size": 21,
                "IsLatest": True,
            },
            {
                "Key": MODULE.DESTINATION_PREFIX + "README.md",
                "VersionId": "readme-version",
                "Size": 14,
                "IsLatest": True,
            },
        ]

        MODULE.validate_final_destination_history(versions, [], records)

        cases = (
            ("delete marker", versions, [{"Key": "deleted"}], records),
            ("missing row", versions[:-1], [], records),
            (
                "duplicate key",
                [versions[0], {**versions[0], "VersionId": "other-version"}],
                [],
                records,
            ),
            (
                "unexpected key",
                [
                    versions[0],
                    {
                        **versions[1],
                        "Key": MODULE.DESTINATION_PREFIX + "unexpected.json",
                    },
                ],
                [],
                records,
            ),
            (
                "non-latest",
                [versions[0], {**versions[1], "IsLatest": False}],
                [],
                records,
            ),
            (
                "wrong VersionId",
                [versions[0], {**versions[1], "VersionId": "old-version"}],
                [],
                records,
            ),
            (
                "boolean VersionId",
                [versions[0], {**versions[1], "VersionId": True}],
                [],
                records,
            ),
            (
                "float Size",
                [versions[0], {**versions[1], "Size": 14.0}],
                [],
                records,
            ),
            (
                "string Size",
                [versions[0], {**versions[1], "Size": "14"}],
                [],
                records,
            ),
            (
                "missing upload evidence",
                versions,
                [],
                [{key: value for key, value in records[0].items() if key != "upload"}],
            ),
        )
        for label, final_versions, final_markers, final_records in cases:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(ValueError, "final destination"),
            ):
                MODULE.validate_final_destination_history(
                    list(final_versions),
                    list(final_markers),
                    list(final_records),
                )

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
