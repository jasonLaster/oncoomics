#!/usr/bin/env python3
from __future__ import annotations

import base64
import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


finalizer = load("finalize_input_contract", ROOT / "scripts/finalize_input_contract.py")
publisher = load("publish_input_contract", ROOT / "scripts/publish_input_contract.py")
checker = load("check_contract_for_custody", ROOT / "scripts/check_contract.py")

KMS = "arn:aws:kms:us-east-1:172630973301:key/45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
RUN = "diana-wgs-hrd-20260716T033101Z"
BUCKET = "diana-omics-private-results-172630973301-us-east-1"


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def private_blob(relative: str, sha256: str, version: str) -> dict:
    return {
        "uri": f"s3://{BUCKET}/runs/subject01/{RUN}/{relative}",
        "sha256": sha256,
        "version_id": version,
    }


def pending_contract() -> dict:
    return {
        "schema_version": 1,
        "run_alias": "subject01",
        "kms_key_arn": KMS,
        "reference": {
            "build": "GRCh38",
            "fasta": private_blob(
                "deterministic/reference/reference.fa",
                "1" * 64,
                "reference-fasta-version",
            ),
            "fai": private_blob(
                "deterministic/reference/reference.fa.fai",
                "2" * 64,
                "reference-fai-version",
            ),
            "dict": private_blob(
                "deterministic/reference/reference.dict",
                "3" * 64,
                "reference-dict-version",
            ),
        },
        "artifacts": {
            "sbs96_matrix": private_blob(
                "deterministic/final/sbs96.csv",
                "4" * 64,
                "pending-sbs96-version",
            ),
            "somatic_vcf": private_blob(
                "deterministic/final/somatic.pass.vcf.gz",
                "5" * 64,
                "pending-vcf-version",
            ),
            "somatic_vcf_index": private_blob(
                "deterministic/final/somatic.pass.vcf.gz.tbi",
                "6" * 64,
                "pending-vcf-index-version",
            ),
            "tumor_bam": private_blob(
                "deterministic/inputs/tumor.markdup.bam",
                "7" * 64,
                "tumor-bam-version",
            ),
            "tumor_bai": private_blob(
                "deterministic/inputs/tumor.markdup.bam.bai",
                "8" * 64,
                "tumor-bai-version",
            ),
            "normal_bam": private_blob(
                "deterministic/inputs/normal.markdup.bam",
                "9" * 64,
                "normal-bam-version",
            ),
            "normal_bai": private_blob(
                "deterministic/inputs/normal.markdup.bam.bai",
                "a" * 64,
                "normal-bai-version",
            ),
        },
        "method_parameters": {"sequenza": {"female": True}},
        "routes": ["sigprofiler_sbs3", "sequenza_scarhrd"],
        "output_uri": f"s3://{BUCKET}/runs/subject01/{RUN}/",
        "attestations": {
            "input_sha256_verified": True,
            "bam_quickcheck_passed": True,
            "bam_reference_digest_matched": True,
            "fastq_checksums_match_delivery_manifest": False,
            "common_snp_vcf_reference_matched": False,
            "final_primary_wgs_artifacts": False,
            "no_direct_identifiers_in_aliases": True,
        },
    }


class CustodyFixture:
    def __init__(self):
        self.pending = pending_contract()
        paths = {
            "vcf": "variants/diana.wgs.mutect2.filtered.vcf.gz",
            "vcf_index": "variants/diana.wgs.mutect2.filtered.vcf.gz.tbi",
            "matrix": "signatures/wgs_sbs96_matrix.csv",
        }
        self.freeze_rows = []
        self.exact_rows = []
        self.cross_sources = {}
        for index, (role, relative) in enumerate(paths.items(), 1):
            uri = f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/final/{relative}"
            key = uri.split(f"s3://{BUCKET}/", 1)[1]
            version = f"frozen-version-{index}"
            digest = f"{index:064x}"
            checksum = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
            destination = {
                "bucket": BUCKET,
                "key": key,
                "version_id": version,
                "bytes": index + 10,
                "checksums": {"ChecksumSHA256": checksum},
                "checksum_type": "FULL_OBJECT",
                "kms_key_id": KMS,
            }
            self.freeze_rows.append(
                {
                    "relative_key": relative,
                    "status": "passed",
                    "destination": destination,
                    "checks": {"copy": True},
                }
            )
            self.exact_rows.append(
                {
                    "relative_key": relative,
                    "bucket": BUCKET,
                    "key": key,
                    "version_id": version,
                    "bytes": index + 10,
                    "checksums": {"ChecksumSHA256": checksum},
                    "kms_key_id": KMS,
                    "sha256": digest,
                    "checks": {"exact": True},
                }
            )
            self.cross_sources[role] = {
                "uri": uri,
                "version_id": version,
                "sha256": digest,
            }
        for role in ("fasta", "fai"):
            declared = self.pending["reference"][role]
            self.cross_sources[role] = {
                "uri": declared["uri"],
                "version_id": declared["version_id"],
                "sha256": declared["sha256"],
            }

        self.freeze = {
            "schema_version": 1,
            "status": "passed",
            "batch_status": "SUCCEEDED",
            "destination_bucket_versioning": "Enabled",
            "destination_initial_version_history_count": 0,
            "receipt_anchor_strategy": "sha256_content_addressed_create_only",
            "object_count": len(self.freeze_rows),
            "passed_count": len(self.freeze_rows),
            "initial_inventory_identity": [{"x": 1}],
            "final_inventory_identity": [{"x": 1}],
            "checks": {"complete": True},
            "objects": self.freeze_rows,
        }
        self.freeze_sha = "a" * 64
        self.freeze_anchor = {
            "receipt_sha256": self.freeze_sha,
            "receipt_uri": f"s3://{BUCKET}/freeze/{self.freeze_sha}.json",
            "receipt_version_id": "freeze-receipt-version",
        }
        self.exact = {
            "schema_version": 1,
            "status": "passed",
            "freeze_receipt_sha256": self.freeze_sha,
            "expected_kms_key_arn": KMS,
            "object_count": len(self.exact_rows),
            "passed_count": len(self.exact_rows),
            "objects": self.exact_rows,
        }
        outputs = {}
        for index, (artifact, filename) in enumerate(finalizer.FINAL_OUTPUTS.items(), 11):
            uri = self.pending["artifacts"][artifact]["uri"]
            outputs[filename] = {
                "uri": uri,
                "version_id": f"alias-version-{index}",
                "sha256": f"{index:064x}",
                "bytes": index + 100,
                "checksums": {"ChecksumSHA256": f"checksum-{index}"},
                "checks": {"single": True},
            }
        outputs["staged_input_validation.json"] = {
            "uri": f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/final/staged_input_validation.json",
            "version_id": "alias-validation-version",
            "sha256": "f" * 64,
            "bytes": 101,
            "checksums": {"ChecksumSHA256": "validation-checksum"},
            "checks": {"single": True},
        }
        destination_inventory = [
            {
                "filename": filename,
                "version_id": row["version_id"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "checksums": row["checksums"],
            }
            for filename, row in outputs.items()
        ]
        self.materializer_sha = "e" * 64
        self.cross = {
            "schema_version": 2,
            "status": "passed",
            "run_alias": "subject01",
            "destination_bucket_versioning": "Enabled",
            "destination_initial_version_history_count": 0,
            "receipt_anchor_strategy": "sha256_content_addressed_create_only",
            "script_sha256": self.materializer_sha,
            "source_custody": self.cross_sources,
            "outputs": outputs,
            "destination_inventory": destination_inventory,
            "checks": {"complete": True},
            "classification_authorization": "none",
            "authorized_hrd_state": "no_call",
        }
        self.cross_sha = "b" * 64
        self.cross_anchor = {
            "receipt_sha256": self.cross_sha,
            "receipt_uri": f"s3://{BUCKET}/cross/{self.cross_sha}.json",
            "receipt_version_id": "cross-receipt-version",
        }

    def finalize(self) -> dict:
        return finalizer.finalize(
            self.pending,
            self.freeze,
            self.freeze_anchor,
            self.exact,
            self.cross,
            self.cross_anchor,
            freeze_receipt_sha256=self.freeze_sha,
            exact_materialization_sha256="c" * 64,
            crosscheck_receipt_sha256=self.cross_sha,
            finalizer_sha256="d" * 64,
            expected_crosscheck_materializer_sha256=self.materializer_sha,
        )


class CustodyHandoffTests(unittest.TestCase):
    def test_finalizer_writes_contract_create_only_mode_0600(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "input-contract.json"
            finalizer.write_new_json(output, {"status": "passed"})

            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                {"status": "passed"},
            )

            original = output.read_bytes()
            with self.assertRaises(FileExistsError):
                finalizer.write_new_json(output, {"status": "failed"})
            self.assertEqual(output.read_bytes(), original)

    def test_contract_check_writes_readiness_receipt_create_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            readiness = root / "input-contract.readiness.json"
            write_json(contract, CustodyFixture().finalize())
            argv = [
                "check_contract.py",
                "--contract",
                str(contract),
                "--json-out",
                str(readiness),
            ]

            with patch.object(sys, "argv", argv):
                self.assertEqual(checker.main(), 0)

            self.assertEqual(stat.S_IMODE(readiness.stat().st_mode), 0o600)
            self.assertEqual(
                json.loads(readiness.read_text(encoding="utf-8")),
                checker.validate(json.loads(contract.read_text(encoding="utf-8"))),
            )

            original = readiness.read_bytes()
            with (
                patch.object(sys, "argv", argv),
                self.assertRaisesRegex(
                    SystemExit,
                    "contract readiness output already exists",
                ),
            ):
                checker.main()
            self.assertEqual(readiness.read_bytes(), original)

    def test_finalizer_binds_all_three_outputs_and_attests_final_primary(self):
        contract = CustodyFixture().finalize()
        self.assertTrue(contract["attestations"]["final_primary_wgs_artifacts"])
        self.assertEqual(contract["custody"]["status"], "passed")
        self.assertEqual(
            contract["custody"]["final_primary_artifacts"],
            {key: contract["artifacts"][key] for key in finalizer.FINAL_OUTPUTS},
        )
        self.assertEqual(checker.validate(contract)["overall_status"], "ready")

    def test_finalizer_rejects_crosscheck_source_not_in_exact_freeze(self):
        fixture = CustodyFixture()
        fixture.cross["source_custody"]["vcf"]["version_id"] = "raced-version"
        with self.assertRaisesRegex(ValueError, "not the exact final freeze"):
            fixture.finalize()

    def test_finalizer_rejects_incomplete_freeze_or_history(self):
        fixture = CustodyFixture()
        fixture.freeze["destination_initial_version_history_count"] = 1
        with self.assertRaisesRegex(ValueError, "one-shot freeze"):
            fixture.finalize()

    def test_anchor_validation_binds_exact_local_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "receipt.json"
            write_json(receipt, {"status": "passed"})
            anchor = root / "anchor.json"
            write_json(
                anchor,
                {
                    "schema_version": 1,
                    "status": "passed",
                    "receipt_sha256": finalizer.sha256(receipt),
                    "receipt_bytes": receipt.stat().st_size,
                    "receipt_uri": f"s3://{BUCKET}/receipts/{finalizer.sha256(receipt)}.json",
                    "receipt_version_id": "receipt-version",
                    "checks": {"exact": True},
                },
            )
            finalizer.validate_anchor(receipt, anchor, "unit")
            value = json.loads(anchor.read_text())
            value["receipt_version_id"] = ""
            write_json(anchor, value)
            with self.assertRaisesRegex(ValueError, "VersionId"):
                finalizer.validate_anchor(receipt, anchor, "unit")

    def test_contract_publication_is_create_only_content_addressed_and_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            anchor = root / "anchor.json"
            contract_sha = publisher.sha256(contract)
            version = "contract-version"
            checksum = base64.b64encode(bytes.fromhex(contract_sha)).decode("ascii")
            metadata = {
                "VersionId": version,
                "ContentLength": contract.stat().st_size,
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": checksum,
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": KMS,
                "Metadata": {"sha256": contract_sha},
            }

            def fake_get(bucket, key, version_id, destination, region):
                destination.write_bytes(contract.read_bytes())
                return dict(metadata)

            argv = [
                "publish_input_contract.py",
                "--contract",
                str(contract),
                "--destination-prefix",
                f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/contracts/",
                "--kms-key-arn",
                KMS,
                "--anchor-output",
                str(anchor),
                "--apply",
            ]
            history = [
                {
                    "history_kind": "version",
                    "Key": f"runs/subject01/{RUN}/deterministic/contracts/{contract_sha}.json",
                    "VersionId": version,
                    "IsLatest": True,
                }
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(publisher, "aws_json", return_value={"Status": "Enabled"}),
                patch.object(publisher, "version_history", side_effect=[[], history]),
                patch.object(publisher, "put_create_only", return_value={"VersionId": version}),
                patch.object(publisher, "head", return_value=metadata),
                patch.object(publisher, "get_exact", side_effect=fake_get),
            ):
                self.assertEqual(publisher.main(), 0)
            value = json.loads(anchor.read_text())
            self.assertEqual(value["status"], "passed")
            self.assertEqual(value["receipt_version_id"], version)
            self.assertTrue(all(value["checks"].values()))
            self.assertIn(contract_sha, value["receipt_uri"])

    def test_contract_publication_recovers_put_before_anchor_update_without_second_put(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            anchor_path = root / "anchor.json"
            contract_sha = publisher.sha256(contract)
            version = "contract-version"
            prefix = f"runs/subject01/{RUN}/deterministic/contracts/"
            key = f"{prefix}{contract_sha}.json"
            uri = f"s3://{BUCKET}/{key}"
            checksum = base64.b64encode(bytes.fromhex(contract_sha)).decode("ascii")
            metadata = {
                "VersionId": version,
                "ContentLength": contract.stat().st_size,
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": checksum,
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": KMS,
                "Metadata": {"sha256": contract_sha},
            }
            reserved = {
                "schema_version": 1,
                "status": "in_progress",
                "receipt_sha256": contract_sha,
                "receipt_bytes": contract.stat().st_size,
                "receipt_uri": uri,
                "receipt_version_id": "",
                "bucket_versioning": "Enabled",
                "initial_version_history_count": 0,
                "publication_strategy": "sha256_content_addressed_create_only",
                "kms_key_arn": KMS,
                "checks": {},
            }
            publisher.reserve_json(anchor_path, reserved)
            history = [
                {
                    "history_kind": "version",
                    "Key": key,
                    "VersionId": version,
                    "IsLatest": True,
                }
            ]

            def fake_get(bucket, object_key, version_id, destination, region):
                destination.write_bytes(contract.read_bytes())
                return dict(metadata)

            argv = [
                "publish_input_contract.py",
                "--contract",
                str(contract),
                "--destination-prefix",
                f"s3://{BUCKET}/{prefix}",
                "--kms-key-arn",
                KMS,
                "--anchor-output",
                str(anchor_path),
                "--apply",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(publisher, "aws_json", return_value={"Status": "Enabled"}),
                patch.object(publisher, "version_history", side_effect=[history, history]),
                patch.object(publisher, "put_create_only") as put,
                patch.object(publisher, "head", return_value=metadata),
                patch.object(publisher, "get_exact", side_effect=fake_get),
            ):
                self.assertEqual(publisher.main(), 0)
            put.assert_not_called()
            value = json.loads(anchor_path.read_text())
            self.assertEqual(value["status"], "passed")
            self.assertEqual(value["receipt_version_id"], version)
            self.assertTrue(value["recovered_existing_version"])

    def test_contract_version_history_consumes_key_and_version_markers(self):
        pages = [
            {
                "IsTruncated": True,
                "Versions": [{"Key": "prefix/contract.json", "VersionId": "v1"}],
                "DeleteMarkers": [],
                "NextKeyMarker": "prefix/contract.json",
                "NextVersionIdMarker": "v1",
            },
            {
                "IsTruncated": False,
                "Versions": [],
                "DeleteMarkers": [{"Key": "prefix/old.json", "VersionId": "d1"}],
            },
        ]

        with patch.object(publisher, "aws_json", side_effect=pages) as aws_json:
            self.assertEqual(
                publisher.version_history(BUCKET, "prefix/", "us-east-1"),
                [
                    {
                        "Key": "prefix/contract.json",
                        "VersionId": "v1",
                        "history_kind": "version",
                    },
                    {
                        "Key": "prefix/old.json",
                        "VersionId": "d1",
                        "history_kind": "delete_marker",
                    },
                ],
            )

        self.assertEqual(
            aws_json.call_args_list[1].args,
            (
                [
                    "s3api",
                    "list-object-versions",
                    "--bucket",
                    BUCKET,
                    "--prefix",
                    "prefix/",
                    "--key-marker",
                    "prefix/contract.json",
                    "--version-id-marker",
                    "v1",
                ],
                "us-east-1",
            ),
        )

    def test_contract_version_history_rejects_missing_or_stalled_markers(self):
        missing_version = {
            "IsTruncated": True,
            "Versions": [],
            "DeleteMarkers": [],
            "NextKeyMarker": "prefix/contract.json",
        }
        with patch.object(publisher, "aws_json", return_value=missing_version):
            with self.assertRaisesRegex(ValueError, "key/version markers"):
                publisher.version_history(BUCKET, "prefix/", "us-east-1")

        stalled = {
            "IsTruncated": True,
            "Versions": [],
            "DeleteMarkers": [],
            "NextKeyMarker": "prefix/contract.json",
            "NextVersionIdMarker": "v1",
        }
        with patch.object(publisher, "aws_json", side_effect=[stalled, stalled]):
            with self.assertRaisesRegex(ValueError, "did not advance"):
                publisher.version_history(BUCKET, "prefix/", "us-east-1")


if __name__ == "__main__":
    unittest.main()
