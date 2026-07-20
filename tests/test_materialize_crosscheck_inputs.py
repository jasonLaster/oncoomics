#!/usr/bin/env python3
from __future__ import annotations

import ast
import csv
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SPEC = importlib.util.spec_from_file_location(
    "materialize_crosscheck_inputs", SCRIPT_DIR / "materialize_crosscheck_inputs.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class MaterializeCrosscheckInputsTests(unittest.TestCase):
    def fixture(self, root: Path, *, wrong_matrix: bool = False):
        fasta = root / "reference.fa"
        with fasta.open("w", encoding="ascii") as handle:
            for contig in module.STANDARD_CONTIGS:
                handle.write(f">{contig}\n")
                handle.write("A" * 49 + "C" + "A" * 50 + "\n")
        subprocess.run(["samtools", "faidx", str(fasta)], check=True)
        fai = Path(f"{fasta}.fai")

        vcf_text = root / "source.vcf"
        contigs = "\n".join(
            f"##contig=<ID={contig},length=100>" for contig in module.STANDARD_CONTIGS
        )
        vcf_text.write_text(
            "##fileformat=VCFv4.2\n"
            "##FILTER=<ID=LowQual,Description=synthetic>\n"
            "##tumor_sample=SOURCE_TUMOR\n"
            "##normal_sample=SOURCE_NORMAL\n"
            f"{contigs}\n"
            "##FORMAT=<ID=GT,Number=1,Type=String,Description=Genotype>\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSOURCE_NORMAL\tSOURCE_TUMOR\n"
            "chr1\t50\t.\tC\tT\t60\tPASS\t.\tGT\t0/0\t0/1\n"
            "chr1\t60\t.\tA\tG\t10\tLowQual\t.\tGT\t0/0\t0/1\n",
            encoding="utf-8",
        )
        vcf = root / "source.filtered.vcf.gz"
        subprocess.run(["bcftools", "view", "-Oz", "-o", str(vcf), str(vcf_text)], check=True)
        subprocess.run(["bcftools", "index", "-t", str(vcf)], check=True)
        index = Path(f"{vcf}.tbi")

        matrix = root / "source.sbs96.csv"
        with matrix.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sample", "mutation_type", "trinucleotide", "count"])
            for context in sorted(module.CANONICAL):
                mutation = context[2:5]
                trinucleotide = context[0] + context[2] + context[-1]
                count = 1 if context == "A[C>T]A" else 0
                if wrong_matrix and context == "A[C>T]A":
                    count = 2
                writer.writerow(["SOURCE_TUMOR", mutation, trinucleotide, count])
        return vcf, index, matrix, fasta, fai

    def test_materializes_alias_only_pass_vcf_and_exact_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vcf, index, matrix, fasta, fai = self.fixture(root)
            output = root / "output"
            result = module.materialize(
                source_vcf=vcf,
                source_vcf_index=index,
                source_matrix=matrix,
                fasta=fasta,
                fai=fai,
                output_dir=output,
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["pass_snv_records"], 1)
            self.assertEqual(result["pass_snv_alleles"], 1)
            self.assertTrue(result["matrix_matches_independent_pass_vcf_derivation"])
            header = subprocess.check_output(
                ["bcftools", "view", "-h", str(output / "somatic.pass.vcf.gz")],
                text=True,
            )
            self.assertNotIn("SOURCE_TUMOR", header)
            self.assertNotIn("SOURCE_NORMAL", header)
            self.assertIn("subject01_tumor", header)
            self.assertIn("subject01_normal", header)
            filters = subprocess.check_output(
                ["bcftools", "query", "-f", "%FILTER\n", str(output / "somatic.pass.vcf.gz")],
                text=True,
            ).splitlines()
            self.assertEqual(filters, ["PASS"])
            matrix_text = (output / "sbs96.csv").read_text()
            self.assertNotIn("SOURCE_", matrix_text)
            self.assertEqual(matrix_text.splitlines()[0], "MutationType,count")
            self.assertEqual(len(matrix_text.splitlines()), 97)
            staged = module.staged_validation(result)
            self.assertEqual(staged["status"], "passed")
            self.assertEqual(staged["route"], "sigprofiler_sbs3")
            self.assertEqual(
                staged["checks"]["sbs96_equivalence"]["usable_pass_snv_alleles"],
                1,
            )
            self.assertTrue(
                staged["checks"]["sbs96_equivalence"]
                ["matrix_matches_independent_pass_vcf_derivation"]
            )
            self.assertEqual(staged["authorized_hrd_state"], "no_call")

    def test_matrix_mismatch_fails_before_publishable_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vcf, index, matrix, fasta, fai = self.fixture(root, wrong_matrix=True)
            with self.assertRaisesRegex(ValueError, "independent PASS-VCF derivation"):
                module.materialize(
                    source_vcf=vcf,
                    source_vcf_index=index,
                    source_matrix=matrix,
                    fasta=fasta,
                    fai=fai,
                    output_dir=root / "output",
                )

    def test_capture_replaces_invalid_utf8_from_external_tools(self):
        with patch.object(
            module.subprocess,
            "check_output",
            return_value=b"samtools\xab\n",
        ) as check_output:
            self.assertEqual(module.capture(["samtools", "--version"]), "samtools�")

        check_output.assert_called_once_with(
            ["samtools", "--version"],
            stderr=module.subprocess.STDOUT,
        )

    def test_custody_gate_requires_exact_frozen_version(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/input.vcf.gz"
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"
        metadata = {
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": kms,
            "VersionId": "frozen-version",
            "ContentLength": 10,
        }
        module.require_private_versioned_kms(uri, metadata, kms, "frozen-version")
        with self.assertRaisesRegex(ValueError, "VersionId differs"):
            module.require_private_versioned_kms(
                uri, metadata, kms, "different-version"
            )
        with self.assertRaisesRegex(ValueError, "exact VersionId"):
            module.require_private_versioned_kms(
                uri, {**metadata, "VersionId": True}, kms, "True"
            )

        for content_length in (True, 10.0, "10", 0):
            with self.subTest(content_length=content_length):
                malformed = {**metadata, "ContentLength": content_length}
                with self.assertRaisesRegex(ValueError, "ContentLength"):
                    module.require_private_versioned_kms(
                        uri, malformed, kms, "frozen-version"
                    )

    def test_exact_int_rejects_coerced_s3_byte_metadata(self):
        self.assertTrue(module.is_positive_exact_int(7))
        self.assertTrue(module.exact_int(7, 7))

        for value in (True, 7.0, "7", None):
            with self.subTest(value=value):
                self.assertFalse(module.is_positive_exact_int(value))
                self.assertFalse(module.exact_int(value, 7))

    def test_s3_etag_guard_requires_exact_strings(self):
        self.assertEqual(module.exact_s3_etag('"etag"', "object"), '"etag"')

        for value in (True, None, "", "None", "null", "has space"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "exact S3 ETag"):
                    module.exact_s3_etag(value, "object")

    def test_content_length_guards_avoid_raw_int_coercion(self):
        source = (SCRIPT_DIR / "materialize_crosscheck_inputs.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        raw_calls = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "int"
            ):
                segment = ast.get_source_segment(source, node) or ""
                if "ContentLength" in segment:
                    raw_calls.append(f"{node.lineno}: {segment}")

        self.assertEqual(raw_calls, [])

    def test_version_and_hash_guards_avoid_raw_string_coercion(self):
        source = (SCRIPT_DIR / "materialize_crosscheck_inputs.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        guarded_fields = (
            "metadata.get('VersionId'",
            'metadata.get("VersionId"',
            "response.get('VersionId'",
            'response.get("VersionId"',
            "output.get('version_id'",
            'output.get("version_id"',
            "output.get('sha256'",
            'output.get("sha256"',
            "metadata['VersionId']",
            'metadata["VersionId"]',
        )
        raw_calls = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and node.args
            and any(field in ast.unparse(node.args[0]) for field in guarded_fields)
        ]
        self.assertEqual(raw_calls, [])

    def test_etag_guards_avoid_raw_string_coercion(self):
        source = (SCRIPT_DIR / "materialize_crosscheck_inputs.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        guarded_fields = (
            "metadata.get('ETag'",
            'metadata.get("ETag"',
            "history[0].get('ETag'",
            'history[0].get("ETag"',
            "history_row.get('ETag'",
            'history_row.get("ETag"',
            "output.get('etag'",
            'output.get("etag"',
        )
        raw_calls = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and node.args
            and any(field in ast.unparse(node.args[0]) for field in guarded_fields)
        ]
        self.assertEqual(raw_calls, [])

    def test_versioned_head_and_download_bind_the_same_object_version(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/input.vcf.gz"
        with patch.object(module, "aws_json", return_value={}) as aws_json:
            module.head(uri, "us-east-1", "frozen-version")
        head_arguments, head_region = aws_json.call_args.args
        self.assertEqual(head_region, "us-east-1")
        self.assertEqual(
            head_arguments,
            [
                "s3api",
                "head-object",
                "--bucket",
                "diana-omics-private-results-000000000000-us-east-1",
                "--key",
                "runs/subject01/input.vcf.gz",
                "--checksum-mode",
                "ENABLED",
                "--version-id",
                "frozen-version",
            ],
        )

        with tempfile.TemporaryDirectory() as tmp, patch.object(module, "run") as run:
            destination = Path(tmp) / "input.vcf.gz"
            run.side_effect = lambda command: destination.write_bytes(b"downloaded\n")
            module.download(uri, destination, "us-east-1", "frozen-version")
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [
                module.AWS,
                "s3api",
                "get-object",
                "--bucket",
                "diana-omics-private-results-000000000000-us-east-1",
                "--key",
                "runs/subject01/input.vcf.gz",
                "--version-id",
                "frozen-version",
                "--checksum-mode",
                "ENABLED",
                str(destination),
                "--region",
                "us-east-1",
            ],
        )

    def test_version_history_rejects_non_string_pagination_markers(self):
        with self.assertRaisesRegex(
            ValueError,
            "NextVersionIdMarker.*non-empty string",
        ), patch.object(
            module,
            "aws_json",
            return_value={
                "Versions": [
                    {
                        "Key": "runs/subject01/materialized/sbs96.csv",
                        "VersionId": "output-version",
                    }
                ],
                "IsTruncated": True,
                "NextKeyMarker": "runs/subject01/materialized/sbs96.csv",
                "NextVersionIdMarker": True,
            },
        ):
            module.version_history(
                "diana-omics-private-results-000000000000-us-east-1",
                "runs/subject01/materialized/",
                "us-east-1",
            )

    def test_script_bytes_match_reviewed_next_materializer_revision(self):
        # Batch materializer v4 remains pinned by submit/capture tests to its
        # frozen registered script. This hash pins the reviewed local source
        # for the next materializer revision.
        self.assertEqual(
            module.sha256(SCRIPT_DIR / "materialize_crosscheck_inputs.py"),
            "1b4f74722b6d3fb8cfa918732566a8e62d5766ccb0e4ca28cc4d547c91fbb621",
        )

    def test_sha256_rejects_symlinked_hash_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_source = root / "real-receipt.json"
            receipt = root / "materialization-receipt.json"
            real_source.write_text('{"status":"passed"}\n', encoding="utf-8")
            receipt.symlink_to(real_source)

            with self.assertRaisesRegex(
                ValueError,
                "materialization-receipt.json SHA-256 input may not be a symlink",
            ):
                module.sha256(receipt)

            real_parent = root / "real-inputs"
            real_parent.mkdir()
            (real_parent / "source.vcf.gz").write_bytes(b"exact-vcf-bytes\n")
            linked_parent = root / "linked-inputs"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "source.vcf.gz SHA-256 input parent may not be a symlink",
            ):
                module.sha256(linked_parent / "source.vcf.gz")

    def test_sha256_rejects_hash_input_that_changes_during_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = root / "materialization-receipt.json"
            receipt.write_text('{"stable": true}\n', encoding="utf-8")

            original_sha256_file_once = module.sha256_file_once
            mutated = False

            def mutate_after_first_read(path: Path) -> str:
                nonlocal mutated
                digest = original_sha256_file_once(path)
                if path == receipt and not mutated:
                    mutated = True
                    path.write_text('{"stable": false}\n', encoding="utf-8")
                return digest

            with (
                patch.object(
                    module,
                    "sha256_file_once",
                    side_effect=mutate_after_first_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "materialization-receipt.json SHA-256 input changed during read",
                ),
            ):
                module.sha256(receipt)

    def test_json_output_removes_partial_file_after_file_fsync_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "receipt.json"

            with (
                patch.object(
                    module.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                module.write_json_create_only(
                    output,
                    {"status": "partial"},
                    "materialization receipt output",
                )

            self.assertFalse(output.exists())

    def test_json_output_removes_partial_file_after_directory_fsync_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "receipt.json"

            with (
                patch.object(
                    module,
                    "fsync_directory",
                    side_effect=OSError("synthetic directory fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                module.write_json_create_only(
                    output,
                    {"status": "partial"},
                    "materialization receipt output",
                )

            self.assertFalse(output.exists())

    def test_json_output_rehashes_after_parent_fsync(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "receipt.json"
            real_fsync_directory = module.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                patch.object(
                    module,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "materialization receipt output changed during write",
                ),
            ):
                module.write_json_create_only(
                    output,
                    {"status": "passed"},
                    "materialization receipt output",
                )

            self.assertFalse(output.exists())

    def test_upload_binds_local_sha256_in_object_metadata(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/output.json"
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "output.json"
            source.write_text("{}\n")
            digest = module.sha256(source)
            metadata = {
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": kms,
                "VersionId": "output-version",
                "ContentLength": source.stat().st_size,
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": module.checksum_sha256(digest),
                "ETag": "unit",
                "ChecksumCRC64NVME": "unit-crc",
                "Metadata": {"sha256": digest},
            }
            history = {
                "Versions": [{
                    "Key": "runs/subject01/output.json",
                    "VersionId": "output-version",
                    "IsLatest": True,
                    "Size": source.stat().st_size,
                    "ETag": "unit",
                }],
                "DeleteMarkers": [],
                "IsTruncated": False,
            }
            calls = iter([
                {"Versions": [], "DeleteMarkers": [], "IsTruncated": False},
                {"VersionId": "output-version"},
                history,
            ])
            with patch.object(
                module, "aws_json", side_effect=lambda arguments, region: next(calls)
            ) as aws_json, patch.object(module, "head", return_value=metadata):
                receipt = module.upload(source, uri, kms, "us-east-1")
        put_arguments = aws_json.call_args_list[1].args[0]
        self.assertEqual(
            put_arguments,
            [
                "s3api",
                "put-object",
                "--bucket",
                "diana-omics-private-results-000000000000-us-east-1",
                "--key",
                "runs/subject01/output.json",
                "--body",
                str(source),
                "--if-none-match",
                "*",
                "--server-side-encryption",
                "aws:kms",
                "--sse-kms-key-id",
                kms,
                "--checksum-algorithm",
                "SHA256",
                "--checksum-sha256",
                module.checksum_sha256(digest),
                "--metadata",
                f"sha256={digest}",
            ],
        )
        self.assertEqual(receipt["version_id"], "output-version")
        self.assertEqual(receipt["etag"], "unit")
        self.assertEqual(receipt["sha256"], digest)
        self.assertEqual(
            receipt["checksums"]["ChecksumSHA256"],
            module.checksum_sha256(digest),
        )
        self.assertEqual(receipt["checksums"]["ChecksumCRC64NVME"], "unit-crc")
        self.assertTrue(all(receipt["checks"].values()))

    def test_upload_rejects_non_string_put_version_id(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/output.json"

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "output.json"
            source.write_text('{"ok": true}\n', encoding="utf-8")
            with (
                patch.object(module, "version_history", return_value=[]),
                patch.object(
                    module,
                    "aws_json",
                    return_value={"VersionId": True},
                ),
                self.assertRaisesRegex(ValueError, "exact VersionId"),
            ):
                module.upload(
                    source,
                    uri,
                    "arn:aws:kms:us-east-1:000000000000:key/test",
                    "us-east-1",
                )

    def test_upload_rejects_non_exact_etag(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/output.json"
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"

        for etag in (True, None, "", "None", "null", "has space"):
            with self.subTest(etag=etag), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "output.json"
                source.write_text("{}\n", encoding="utf-8")
                digest = module.sha256(source)
                metadata = {
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": kms,
                    "VersionId": "output-version",
                    "ContentLength": source.stat().st_size,
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": module.checksum_sha256(digest),
                    "ETag": etag,
                    "Metadata": {"sha256": digest},
                }

                with (
                    patch.object(module, "version_history", return_value=[]),
                    patch.object(
                        module,
                        "aws_json",
                        return_value={"VersionId": "output-version"},
                    ),
                    patch.object(module, "head", return_value=metadata),
                    self.assertRaisesRegex(ValueError, "exact S3 ETag"),
                ):
                    module.upload(source, uri, kms, "us-east-1")

    def test_upload_rejects_non_exact_content_length(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/output.json"
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"

        for content_length in (True, 3.0, "3"):
            with self.subTest(content_length=content_length), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "output.json"
                source.write_text("{}\n")
                digest = module.sha256(source)
                metadata = {
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": kms,
                    "VersionId": "output-version",
                    "ContentLength": content_length,
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": module.checksum_sha256(digest),
                    "ETag": "output-etag",
                    "Metadata": {"sha256": digest},
                }
                calls = iter([
                    {"Versions": [], "DeleteMarkers": [], "IsTruncated": False},
                    {"VersionId": "output-version"},
                ])
                with (
                    patch.object(
                        module,
                        "aws_json",
                        side_effect=lambda arguments, region, calls=calls: next(calls),
                    ),
                    patch.object(module, "head", return_value=metadata),
                    self.assertRaisesRegex(ValueError, "ContentLength"),
                ):
                    module.upload(source, uri, kms, "us-east-1")

    def test_upload_rejects_non_exact_history_size(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/output.json"
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "output.json"
            source.write_text("{}\n")
            digest = module.sha256(source)
            metadata = {
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": kms,
                "VersionId": "output-version",
                "ContentLength": source.stat().st_size,
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": module.checksum_sha256(digest),
                "ETag": "output-etag",
                "Metadata": {"sha256": digest},
            }
            history = {
                "Versions": [{
                    "Key": "runs/subject01/output.json",
                    "VersionId": "output-version",
                    "IsLatest": True,
                    "Size": True,
                    "ETag": "output-etag",
                }],
                "DeleteMarkers": [],
                "IsTruncated": False,
            }
            calls = iter([
                {"Versions": [], "DeleteMarkers": [], "IsTruncated": False},
                {"VersionId": "output-version"},
                history,
            ])
            with (
                patch.object(
                    module,
                    "aws_json",
                    side_effect=lambda arguments, region: next(calls),
                ),
                patch.object(module, "head", return_value=metadata),
                self.assertRaisesRegex(ValueError, "single-version history"),
            ):
                module.upload(source, uri, kms, "us-east-1")

    def test_upload_rejects_non_exact_history_etag(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/output.json"
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"

        cases = (
            ("coerced", True, "exact S3 ETag"),
            ("mismatched", "other-etag", "single-version history"),
        )
        for label, etag, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "output.json"
                source.write_text("{}\n", encoding="utf-8")
                digest = module.sha256(source)
                metadata = {
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": kms,
                    "VersionId": "output-version",
                    "ContentLength": source.stat().st_size,
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": module.checksum_sha256(digest),
                    "ETag": "output-etag",
                    "Metadata": {"sha256": digest},
                }

                with (
                    patch.object(
                        module,
                        "version_history",
                        side_effect=[
                            [],
                            [
                                {
                                    "history_kind": "version",
                                    "Key": "runs/subject01/output.json",
                                    "VersionId": "output-version",
                                    "IsLatest": True,
                                    "Size": source.stat().st_size,
                                    "ETag": etag,
                                }
                            ],
                        ],
                    ),
                    patch.object(
                        module,
                        "aws_json",
                        return_value={"VersionId": "output-version"},
                    ),
                    patch.object(module, "head", return_value=metadata),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    module.upload(source, uri, kms, "us-east-1")

    def test_upload_rejects_s3_checksum_that_differs_from_local_sha256(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/output.json"
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "output.json"
            source.write_text("{}\n")
            digest = module.sha256(source)
            metadata = {
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": kms,
                "VersionId": "output-version",
                "ContentLength": source.stat().st_size,
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": module.checksum_sha256("0" * 64),
                "Metadata": {"sha256": digest},
            }
            calls = iter([
                {"Versions": [], "DeleteMarkers": [], "IsTruncated": False},
                {"VersionId": "output-version"},
            ])
            with (
                patch.object(
                    module,
                    "aws_json",
                    side_effect=lambda arguments, region: next(calls),
                ),
                patch.object(module, "head", return_value=metadata),
                self.assertRaisesRegex(ValueError, "SHA-256 checksum mismatch"),
            ):
                module.upload(source, uri, kms, "us-east-1")

    def test_upload_rejects_symlinked_source_before_aws(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/output.json"
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_source = root / "real-output.json"
            real_source.write_text("{}\n", encoding="utf-8")
            linked_source = root / "output.json"
            linked_source.symlink_to(real_source)

            with (
                patch.object(
                    module,
                    "version_history",
                    side_effect=AssertionError("unexpected AWS call"),
                ),
                self.assertRaisesRegex(ValueError, "upload source may not be a symlink"),
            ):
                module.upload(linked_source, uri, kms, "us-east-1")

    def test_audit_output_history_rejects_checksum_that_differs_from_receipt_sha256(self):
        uri = (
            "s3://diana-omics-private-results-000000000000-us-east-1/"
            "runs/subject01/materialized/sbs96.csv"
        )
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"
        digest = "1" * 64
        outputs = {
            "sbs96.csv": {
                "uri": uri,
                "version_id": "output-version",
                "bytes": 10,
                "etag": "output-etag",
                "sha256": digest,
                "checksums": {
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": module.checksum_sha256("0" * 64),
                },
            }
        }

        with (
            patch.object(
                module,
                "version_history",
                return_value=[
                    {
                        "history_kind": "version",
                        "Key": "runs/subject01/materialized/sbs96.csv",
                        "VersionId": "output-version",
                        "IsLatest": True,
                        "Size": 10,
                        "ETag": "output-etag",
                    }
                ],
            ),
            patch.object(
                module,
                "head",
                return_value={
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": kms,
                    "VersionId": "output-version",
                    "ContentLength": 10,
                    "ETag": "output-etag",
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": module.checksum_sha256("0" * 64),
                    "Metadata": {"sha256": digest},
                },
            ),
            self.assertRaisesRegex(ValueError, "exact-version audit failed"),
        ):
            module.audit_output_history(
                (
                    "s3://diana-omics-private-results-000000000000-us-east-1/"
                    "runs/subject01/materialized/"
                ),
                outputs,
                kms,
                "us-east-1",
            )

    def test_audit_output_history_rejects_non_exact_bytes(self):
        uri = (
            "s3://diana-omics-private-results-000000000000-us-east-1/"
            "runs/subject01/materialized/sbs96.csv"
        )
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"
        digest = "1" * 64

        cases = (
            (
                "receipt bytes",
                {"bytes": True},
                {"Size": 10},
            ),
            (
                "history Size",
                {"bytes": 10},
                {"Size": True},
            ),
        )
        for label, output_updates, history_updates in cases:
            with self.subTest(label=label):
                outputs = {
                    "sbs96.csv": {
                        "uri": uri,
                        "version_id": "output-version",
                        "bytes": 10,
                        "etag": "output-etag",
                        "sha256": digest,
                        "checksums": {
                            "ChecksumType": "FULL_OBJECT",
                            "ChecksumSHA256": module.checksum_sha256(digest),
                        },
                        **output_updates,
                    }
                }

                with (
                    patch.object(
                        module,
                        "version_history",
                        return_value=[
                            {
                                "history_kind": "version",
                                "Key": "runs/subject01/materialized/sbs96.csv",
                                "VersionId": "output-version",
                                "IsLatest": True,
                                "ETag": "output-etag",
                                **history_updates,
                            }
                        ],
                    ),
                    patch.object(
                        module,
                        "head",
                        return_value={
                            "ServerSideEncryption": "aws:kms",
                            "SSEKMSKeyId": kms,
                            "VersionId": "output-version",
                            "ContentLength": 10,
                            "ETag": "output-etag",
                            "ChecksumType": "FULL_OBJECT",
                            "ChecksumSHA256": module.checksum_sha256(digest),
                            "Metadata": {"sha256": digest},
                        },
                    ),
                    self.assertRaisesRegex(ValueError, "exact-version audit failed"),
                ):
                    module.audit_output_history(
                        (
                            "s3://diana-omics-private-results-000000000000-us-east-1/"
                            "runs/subject01/materialized/"
                        ),
                        outputs,
                        kms,
                        "us-east-1",
                    )

    def test_audit_output_history_rejects_malformed_version_and_sha_before_head(self):
        digest = "a" * 64
        kms = "arn:aws:kms:us-east-1:000000000000:key/test"
        base = {
            "sbs96.csv": {
                "uri": (
                    "s3://diana-omics-private-results-000000000000-us-east-1/"
                    "runs/subject01/materialized/sbs96.csv"
                ),
                "version_id": "output-version",
                "bytes": 10,
                "etag": "output-etag",
                "sha256": digest,
                "checksums": {
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": module.checksum_sha256(digest),
                },
            }
        }
        cases = (
            ("coerced_version", {"version_id": True}, "exact VersionId"),
            ("coerced_sha", {"sha256": int("a" * 64, 16)}, "exact SHA-256"),
            ("coerced_etag", {"etag": True}, "exact S3 ETag"),
        )
        for label, updates, message in cases:
            with (
                self.subTest(label=label),
                patch.object(
                    module,
                    "version_history",
                    return_value=[
                        {
                            "history_kind": "version",
                            "Key": "runs/subject01/materialized/sbs96.csv",
                            "VersionId": "output-version",
                            "IsLatest": True,
                            "Size": 10,
                            "ETag": "output-etag",
                        }
                    ],
                ),
                patch.object(module, "head") as head,
                self.assertRaisesRegex(ValueError, message),
            ):
                outputs = {"sbs96.csv": {**base["sbs96.csv"], **updates}}
                module.audit_output_history(
                    (
                        "s3://diana-omics-private-results-000000000000-us-east-1/"
                        "runs/subject01/materialized/"
                    ),
                    outputs,
                    kms,
                    "us-east-1",
                )
            head.assert_not_called()

    def test_audit_output_history_rejects_non_exact_etags(self):
        uri = (
            "s3://diana-omics-private-results-000000000000-us-east-1/"
            "runs/subject01/materialized/sbs96.csv"
        )
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"
        digest = "1" * 64
        outputs = {
            "sbs96.csv": {
                "uri": uri,
                "version_id": "output-version",
                "bytes": 10,
                "etag": "output-etag",
                "sha256": digest,
                "checksums": {
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": module.checksum_sha256(digest),
                },
            }
        }

        cases = (
            ("history coerced", True, "output-etag", "exact S3 ETag"),
            ("history mismatch", "other-etag", "output-etag", "exact-version audit"),
            ("metadata coerced", "output-etag", True, "exact S3 ETag"),
            ("metadata mismatch", "output-etag", "other-etag", "exact-version audit"),
        )
        for label, history_etag, metadata_etag, message in cases:
            with (
                self.subTest(label=label),
                patch.object(
                    module,
                    "version_history",
                    return_value=[
                        {
                            "history_kind": "version",
                            "Key": "runs/subject01/materialized/sbs96.csv",
                            "VersionId": "output-version",
                            "IsLatest": True,
                            "Size": 10,
                            "ETag": history_etag,
                        }
                    ],
                ),
                patch.object(
                    module,
                    "head",
                    return_value={
                        "ServerSideEncryption": "aws:kms",
                        "SSEKMSKeyId": kms,
                        "VersionId": "output-version",
                        "ContentLength": 10,
                        "ETag": metadata_etag,
                        "ChecksumType": "FULL_OBJECT",
                        "ChecksumSHA256": module.checksum_sha256(digest),
                        "Metadata": {"sha256": digest},
                    },
                ),
                self.assertRaisesRegex(ValueError, message),
            ):
                module.audit_output_history(
                    (
                        "s3://diana-omics-private-results-000000000000-us-east-1/"
                        "runs/subject01/materialized/"
                    ),
                    outputs,
                    kms,
                    "us-east-1",
                )

    def test_main_rejects_receipt_anchor_below_symlinked_parent_before_aws(self):
        bucket = "diana-omics-private-results-000000000000-us-east-1"
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-parent"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            anchor = linked_parent / "existing" / "anchor.json"
            argv = [
                "materialize_crosscheck_inputs.py",
                "--source-vcf-uri",
                f"s3://{bucket}/runs/subject01/source.vcf.gz",
                "--source-vcf-index-uri",
                f"s3://{bucket}/runs/subject01/source.vcf.gz.tbi",
                "--source-matrix-uri",
                f"s3://{bucket}/runs/subject01/source.sbs96.csv",
                "--reference-fasta-uri",
                f"s3://{bucket}/runs/subject01/reference.fa",
                "--reference-fai-uri",
                f"s3://{bucket}/runs/subject01/reference.fa.fai",
                "--source-vcf-version-id",
                "source-vcf-version",
                "--source-vcf-index-version-id",
                "source-vcf-index-version",
                "--source-matrix-version-id",
                "source-matrix-version",
                "--reference-fasta-version-id",
                "reference-fasta-version",
                "--reference-fai-version-id",
                "reference-fai-version",
                "--destination-prefix",
                f"s3://{bucket}/runs/subject01/materialized/",
                "--receipt-prefix",
                f"s3://{bucket}/runs/subject01/materialized-receipts/",
                "--receipt-anchor-output",
                str(anchor),
                "--kms-key-arn",
                kms,
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    module,
                    "require_bucket_versioning",
                    side_effect=AssertionError("unexpected AWS call"),
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "receipt anchor output parent may not be a symlink",
                ),
            ):
                module.main()

            self.assertFalse((real_parent / "existing" / "anchor.json").exists())

    def test_download_rejects_symlinked_destination(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/input.vcf.gz"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "input.vcf.gz"

            def fake_run(command):
                real_download = root / "real-input.vcf.gz"
                real_download.write_bytes(b"exact-s3-bytes\n")
                destination.symlink_to(real_download)

            with (
                patch.object(module, "run", side_effect=fake_run),
                self.assertRaisesRegex(
                    ValueError,
                    "downloaded exact input may not be a symlink",
                ),
            ):
                module.download(uri, destination, "us-east-1", "frozen-version")

    def test_download_rejects_existing_destination_before_aws(self):
        uri = "s3://diana-omics-private-results-000000000000-us-east-1/runs/subject01/input.vcf.gz"

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "source.filtered.vcf.gz"
            destination.write_bytes(b"stale-local-bytes\n")

            with (
                patch.object(module, "run", side_effect=AssertionError("AWS called")),
                self.assertRaisesRegex(
                    FileExistsError,
                    "downloaded exact input already exists",
                ),
            ):
                module.download(uri, destination, "us-east-1", "frozen-version")

            self.assertEqual(destination.read_bytes(), b"stale-local-bytes\n")

    def test_materialize_rejects_symlinked_source_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vcf, index, matrix, fasta, fai = self.fixture(root)
            real_matrix = root / "real-source.sbs96.csv"
            matrix.replace(real_matrix)
            matrix.symlink_to(real_matrix)

            with self.assertRaisesRegex(
                ValueError,
                "source SBS96 matrix may not be a symlink",
            ):
                module.materialize(
                    source_vcf=vcf,
                    source_vcf_index=index,
                    source_matrix=matrix,
                    fasta=fasta,
                    fai=fai,
                    output_dir=root / "output",
                )

    def test_materialize_rejects_symlinked_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vcf, index, matrix, fasta, fai = self.fixture(root)
            real_output = root / "real-output"
            real_output.mkdir()
            linked_output = root / "linked-output"
            linked_output.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "materializer output directory may not be a symlink",
            ):
                module.materialize(
                    source_vcf=vcf,
                    source_vcf_index=index,
                    source_matrix=matrix,
                    fasta=fasta,
                    fai=fai,
                    output_dir=linked_output,
                )

    def test_materialize_rejects_existing_generated_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vcf, index, matrix, fasta, fai = self.fixture(root)
            output = root / "output"
            output.mkdir()
            stale = output / "pass-snvs.with-source-header.vcf.gz"
            stale.write_bytes(b"stale-pass-vcf\n")

            with self.assertRaisesRegex(
                FileExistsError,
                "PASS-SNV source-header VCF already exists",
            ):
                module.materialize(
                    source_vcf=vcf,
                    source_vcf_index=index,
                    source_matrix=matrix,
                    fasta=fasta,
                    fai=fai,
                    output_dir=output,
                )

            self.assertEqual(stale.read_bytes(), b"stale-pass-vcf\n")

    def test_materialize_rejects_symlinked_external_writer_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vcf, index, matrix, fasta, fai = self.fixture(root)
            output = root / "output"

            def fake_run(command):
                self.assertEqual(command[1], "view")
                destination = output / "pass-snvs.with-source-header.vcf.gz"
                real_destination = output / "real-pass.vcf.gz"
                real_destination.write_bytes(b"redirected\n")
                destination.symlink_to(real_destination)

            with (
                patch.object(module, "run", side_effect=fake_run),
                self.assertRaisesRegex(
                    ValueError,
                    "PASS-SNV source-header VCF may not be a symlink",
                ),
            ):
                module.materialize(
                    source_vcf=vcf,
                    source_vcf_index=index,
                    source_matrix=matrix,
                    fasta=fasta,
                    fai=fai,
                    output_dir=output,
                )

    def test_main_rejects_symlinked_work_dir_before_input_download(self):
        bucket = "diana-omics-private-results-000000000000-us-east-1"
        kms = "arn:aws:kms:us-east-1:000000000000:key/unit"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_work = root / "real-work"
            real_work.mkdir()
            linked_work = root / "linked-work"
            linked_work.symlink_to(real_work, target_is_directory=True)
            anchor = root / "anchor.json"
            argv = [
                "materialize_crosscheck_inputs.py",
                "--source-vcf-uri",
                f"s3://{bucket}/runs/subject01/source.vcf.gz",
                "--source-vcf-index-uri",
                f"s3://{bucket}/runs/subject01/source.vcf.gz.tbi",
                "--source-matrix-uri",
                f"s3://{bucket}/runs/subject01/source.sbs96.csv",
                "--reference-fasta-uri",
                f"s3://{bucket}/runs/subject01/reference.fa",
                "--reference-fai-uri",
                f"s3://{bucket}/runs/subject01/reference.fa.fai",
                "--source-vcf-version-id",
                "source-vcf-version",
                "--source-vcf-index-version-id",
                "source-vcf-index-version",
                "--source-matrix-version-id",
                "source-matrix-version",
                "--reference-fasta-version-id",
                "reference-fasta-version",
                "--reference-fai-version-id",
                "reference-fai-version",
                "--destination-prefix",
                f"s3://{bucket}/runs/subject01/materialized/",
                "--receipt-prefix",
                f"s3://{bucket}/runs/subject01/materialized-receipts/",
                "--receipt-anchor-output",
                str(anchor),
                "--kms-key-arn",
                kms,
                "--work-dir",
                str(linked_work),
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(module, "require_bucket_versioning"),
                patch.object(module, "version_history", return_value=[]),
                patch.object(module, "head", side_effect=AssertionError("unexpected download")),
                self.assertRaisesRegex(ValueError, "work directory may not be a symlink"),
            ):
                module.main()

            self.assertFalse(any(real_work.iterdir()))


if __name__ == "__main__":
    unittest.main()
