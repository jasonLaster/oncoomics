#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
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

    def test_script_bytes_match_registered_materializer_revision(self):
        self.assertEqual(
            module.sha256(SCRIPT_DIR / "materialize_crosscheck_inputs.py"),
            "ca1a5e47fb2de1e8e1c502dbb9155bb6dafc0285cbb169c4ff0ebd1d7337faf1",
        )

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
                "ETag": "unit",
                "ChecksumCRC64NVME": "unit-crc",
                "Metadata": {"sha256": digest},
            }
            history = {
                "Versions": [{
                    "Key": "runs/subject01/output.json",
                    "VersionId": "output-version",
                    "IsLatest": True,
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
                "--metadata",
                f"sha256={digest}",
            ],
        )
        self.assertEqual(receipt["version_id"], "output-version")
        self.assertEqual(receipt["sha256"], digest)
        self.assertEqual(receipt["checksums"]["ChecksumCRC64NVME"], "unit-crc")
        self.assertTrue(all(receipt["checks"].values()))


if __name__ == "__main__":
    unittest.main()
