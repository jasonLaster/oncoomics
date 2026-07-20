#!/usr/bin/env python3
from __future__ import annotations

import ast
import base64
import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
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
materializer = load(
    "materialize_frozen_artifacts", ROOT / "scripts/materialize_frozen_artifacts.py"
)
crosscheck_materializer = load(
    "materialize_crosscheck_inputs", ROOT / "scripts/materialize_crosscheck_inputs.py"
)
publisher = load("publish_input_contract", ROOT / "scripts/publish_input_contract.py")
submitter = load("submit_materializer_v4", ROOT / "scripts/submit_materializer_v4.py")
checker = load("check_contract_for_custody", ROOT / "scripts/check_contract.py")

KMS = "arn:aws:kms:us-east-1:172630973301:key/45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
RUN = "diana-wgs-hrd-20260716T033101Z"
BUCKET = "diana-omics-private-results-172630973301-us-east-1"


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_duplicate_json_field(path: Path, key: str, stale_value: object) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(payload, indent=2, sort_keys=True)
    current = f'  "{key}": {json.dumps(payload[key], sort_keys=True)}'
    if text.count(current) != 1:
        raise AssertionError(f"expected exactly one top-level JSON field {key}")
    duplicate = f'  "{key}": {json.dumps(stale_value, sort_keys=True)},\n{current}'
    path.write_text(text.replace(current, duplicate, 1) + "\n", encoding="utf-8")


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


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
            checksum = checksum_sha256(digest)
            checksums = {
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": checksum,
            }
            destination = {
                "bucket": BUCKET,
                "key": key,
                "version_id": version,
                "bytes": index + 10,
                "etag": f"destination-etag-{index}",
                "checksums": checksums,
                "checksum_type": "FULL_OBJECT",
                "server_side_encryption": "aws:kms",
                "kms_key_id": KMS,
            }
            self.freeze_rows.append(
                {
                    "relative_key": relative,
                    "source": {
                        "bucket": "diana-omics-work-172630973301-us-east-1",
                        "key": f"source/{relative}",
                        "version_id": f"source-version-{index}",
                        "bytes": index + 10,
                        "etag": f"source-etag-{index}",
                        "checksums": checksums,
                        "checksum_type": "FULL_OBJECT",
                    },
                    "status": "passed",
                    "destination": destination,
                    "checks": dict(finalizer.EXPECTED_FINAL_ROW_CHECKS),
                }
            )
            self.exact_rows.append(
                {
                    "relative_key": relative,
                    "bucket": BUCKET,
                    "key": key,
                    "version_id": version,
                    "bytes": index + 10,
                    "checksums": checksums,
                    "checksum_type": "FULL_OBJECT",
                    "server_side_encryption": "aws:kms",
                    "kms_key_id": KMS,
                    "sha256": digest,
                    "checks": dict(finalizer.EXPECTED_MATERIALIZATION_CHECKS),
                }
            )
            self.cross_sources[role] = {
                "uri": uri,
                "version_id": version,
                "bytes": index + 10,
                "etag": f"source-etag-{index}",
                "checksums": checksums,
                "sha256": digest,
                "expected_sha256": digest,
                "kms_key_arn": KMS,
            }
        for role in ("fasta", "fai"):
            declared = self.pending["reference"][role]
            digest = declared["sha256"]
            self.cross_sources[role] = {
                "uri": declared["uri"],
                "version_id": declared["version_id"],
                "bytes": 20,
                "etag": f"{role}-etag",
                "checksums": {
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": checksum_sha256(digest),
                },
                "sha256": digest,
                "expected_sha256": digest,
                "kms_key_arn": KMS,
            }

        self.freeze = {
            "schema_version": 1,
            "status": "passed",
            "generated_at": "2026-07-19T01:00:00+00:00",
            "run_id": RUN,
            "batch_job_id": "deterministic-job",
            "batch_status": "SUCCEEDED",
            "execution_receipt": {
                "path": "/tmp/execution-receipt.json",
                "sha256": "d" * 64,
            },
            "source_prefix": f"s3://{BUCKET}/runs/subject01/{RUN}/work/final/",
            "destination_prefix": (
                f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/final/"
            ),
            "kms_key_arn": KMS,
            "script_sha256": "e" * 64,
            "destination_bucket_versioning": "Enabled",
            "destination_initial_version_history_count": 0,
            "receipt_anchor_strategy": "sha256_content_addressed_create_only",
            "object_count": len(self.freeze_rows),
            "passed_count": len(self.freeze_rows),
            "initial_inventory_identity": [{"x": 1}],
            "final_inventory_identity": [{"x": 1}],
            "destination_inventory": [
                {
                    "relative_key": row["relative_key"],
                    "key": row["destination"]["key"],
                    "version_id": row["destination"]["version_id"],
                    "bytes": row["destination"]["bytes"],
                    "etag": row["destination"]["etag"],
                    "checksums": row["destination"]["checksums"],
                    "checksum_type": row["destination"]["checksum_type"],
                    "kms_key_id": row["destination"]["kms_key_id"],
                }
                for row in self.freeze_rows
            ],
            "checks": dict(finalizer.EXPECTED_FINAL_FREEZE_CHECKS),
            "completed_at": "2026-07-19T01:01:00+00:00",
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
            "run_id": RUN,
            "batch_job_id": "deterministic-job",
            "script_sha256": "e" * 64,
            "freeze_receipt_sha256": self.freeze_sha,
            "expected_kms_key_arn": KMS,
            "materialization_dir": "/tmp/materialized-final",
            "object_count": len(self.exact_rows),
            "passed_count": len(self.exact_rows),
            "objects": self.exact_rows,
        }
        outputs = {}
        for index, (artifact, filename) in enumerate(finalizer.FINAL_OUTPUTS.items(), 11):
            uri = self.pending["artifacts"][artifact]["uri"]
            digest = f"{index:064x}"
            outputs[filename] = {
                "uri": uri,
                "version_id": f"alias-version-{index}",
                "sha256": digest,
                "bytes": index + 100,
                "etag": f"alias-etag-{index}",
                "checksums": {
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": checksum_sha256(digest),
                },
                "kms_key_arn": KMS,
                "checks": dict(finalizer.EXPECTED_CROSSCHECK_OUTPUT_CHECKS),
            }
        validation_digest = "f" * 64
        outputs["staged_input_validation.json"] = {
            "uri": f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/final/staged_input_validation.json",
            "version_id": "alias-validation-version",
            "sha256": validation_digest,
            "bytes": 101,
            "etag": "alias-validation-etag",
            "checksums": {
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": checksum_sha256(validation_digest),
            },
            "kms_key_arn": KMS,
            "checks": dict(finalizer.EXPECTED_CROSSCHECK_OUTPUT_CHECKS),
        }
        destination_inventory = [
            {
                "filename": filename,
                "key": row["uri"].split(f"s3://{BUCKET}/", 1)[1],
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
            "generated_at_utc": "2026-07-19T01:02:00+00:00",
            "run_alias": "subject01",
            "destination_prefix": (
                f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/final/"
            ),
            "destination_bucket_versioning": "Enabled",
            "destination_initial_version_history_count": 0,
            "receipt_anchor_strategy": "sha256_content_addressed_create_only",
            "script_sha256": self.materializer_sha,
            "source_custody": self.cross_sources,
            "validation": {
                "pass_snv_records": 1,
                "sbs96_matches_independent_pass_vcf_derivation": True,
            },
            "input_sha256": {
                "source_vcf": self.cross_sources["vcf"]["sha256"],
                "source_vcf_index": self.cross_sources["vcf_index"]["sha256"],
                "source_matrix": self.cross_sources["matrix"]["sha256"],
                "reference_fasta": self.cross_sources["fasta"]["sha256"],
                "reference_fai": self.cross_sources["fai"]["sha256"],
            },
            "outputs": outputs,
            "destination_inventory": destination_inventory,
            "checks": dict(finalizer.EXPECTED_CROSSCHECK_CHECKS),
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
    def write_contract_dry_run_receipt(
        self,
        path: Path,
        contract: Path,
        *,
        prefix: str | None = None,
        kms_key_arn: str = KMS,
    ) -> Path:
        prefix = prefix or f"runs/subject01/{RUN}/deterministic/contracts/"
        contract_sha = publisher.sha256(contract)
        write_json(
            path,
            {
                "schema_version": 1,
                "status": "dry_run",
                "receipt_sha256": contract_sha,
                "receipt_bytes": contract.stat().st_size,
                "receipt_uri": f"s3://{BUCKET}/{prefix}{contract_sha}.json",
                "receipt_version_id": "",
                "bucket_versioning": "Enabled",
                "initial_version_history_count": 0,
                "publication_strategy": "sha256_content_addressed_create_only",
                "kms_key_arn": kms_key_arn,
                "checks": dict(publisher.EXPECTED_CONTRACT_PREFLIGHT_CHECKS),
            },
        )
        return path

    def assert_contract_publication_rejects_checks(
        self, checks: dict[str, object]
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            anchor = root / "anchor.json"
            contract_sha = publisher.sha256(contract)
            version = "contract-version"
            prefix = f"runs/subject01/{RUN}/deterministic/contracts/"
            key = f"{prefix}{contract_sha}.json"
            dry_run = self.write_contract_dry_run_receipt(
                root / "anchor.dry.json", contract, prefix=prefix
            )
            history = [
                {
                    "history_kind": "version",
                    "Key": key,
                    "VersionId": version,
                    "IsLatest": True,
                    "Size": contract.stat().st_size,
                }
            ]
            argv = [
                "publish_input_contract.py",
                "--contract",
                str(contract),
                "--destination-prefix",
                f"s3://{BUCKET}/{prefix}",
                "--kms-key-arn",
                KMS,
                "--anchor-output",
                str(anchor),
                "--dry-run-receipt",
                str(dry_run),
                "--apply",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    publisher,
                    "aws_json",
                    return_value={"Status": "Enabled"},
                ),
                patch.object(publisher, "version_history", side_effect=[[], history]),
                patch.object(
                    publisher,
                    "put_create_only",
                    return_value={"VersionId": version},
                ),
                patch.object(publisher, "verify_publication", return_value=checks),
                self.assertRaisesRegex(
                    ValueError,
                    "contract publication verification failed",
                ),
            ):
                publisher.main()

            value = json.loads(anchor.read_text(encoding="utf-8"))
            self.assertEqual(value["status"], "failed")
            self.assertEqual(value["checks"], checks)
            self.assertIn(
                "contract publication verification failed",
                value["error"],
            )
            self.assertEqual(value["observed_version_history"], history)

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

    def test_finalizer_rejects_symlinked_output_parent_without_writing_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-contracts"
            real_parent.mkdir()
            linked_parent = root / "linked-contracts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                finalizer.write_new_json(
                    linked_parent / "input-contract.json",
                    {"status": "passed"},
                )

            self.assertFalse((real_parent / "input-contract.json").exists())

    def test_finalizer_removes_partial_output_after_fsync_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "input-contract.json"

            with (
                mock.patch.object(
                    finalizer.os,
                    "fsync",
                    side_effect=OSError("synthetic fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic fsync failure"),
            ):
                finalizer.write_new_json(output, {"status": "passed"})

            self.assertFalse(output.exists())

    def test_finalizer_fsyncs_file_and_parent_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "input-contract.json"

            with mock.patch.object(
                finalizer.os,
                "fsync",
                wraps=finalizer.os.fsync,
            ) as fsync:
                finalizer.write_new_json(output, {"status": "passed"})

            self.assertEqual(fsync.call_count, 2)

    def test_finalizer_removes_partial_output_after_directory_fsync_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "input-contract.json"

            with (
                mock.patch.object(
                    finalizer.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                finalizer.write_new_json(output, {"status": "passed"})

            self.assertFalse(output.exists())

    def test_finalizer_rehashes_after_parent_fsync(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "input-contract.json"
            real_fsync_directory = finalizer.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    finalizer,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "contract output changed during write",
                ),
            ):
                finalizer.write_new_json(output, {"status": "passed"})

            self.assertFalse(output.exists())

    def test_finalizer_rejects_output_below_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-contracts"
            real_parent.mkdir()
            linked_parent = root / "linked-contracts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                finalizer.write_new_json(
                    linked_parent / "missing" / "input-contract.json",
                    {"status": "passed"},
                )

            self.assertFalse((real_parent / "missing").exists())

    def test_finalizer_rejects_existing_output_dir_below_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-contracts"
            real_parent.mkdir()
            (real_parent / "existing").mkdir()
            linked_parent = root / "linked-contracts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                finalizer.write_new_json(
                    linked_parent / "existing" / "input-contract.json",
                    {"status": "passed"},
                )

            self.assertFalse((real_parent / "existing" / "input-contract.json").exists())

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

    def test_contract_check_rejects_symlinked_output_parent_without_writing_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-readiness"
            real_parent.mkdir()
            linked_parent = root / "linked-readiness"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                checker.write_text_once(
                    linked_parent / "input-contract.readiness.json",
                    "{}\n",
                )

            self.assertFalse((real_parent / "input-contract.readiness.json").exists())

    def test_contract_check_removes_partial_output_after_fsync_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "input-contract.readiness.json"

            with (
                mock.patch.object(
                    checker.os,
                    "fsync",
                    side_effect=OSError("synthetic fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic fsync failure"),
            ):
                checker.write_text_once(output, "{}\n")

            self.assertFalse(output.exists())

    def test_contract_check_fsyncs_file_and_parent_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "input-contract.readiness.json"

            with mock.patch.object(
                checker.os,
                "fsync",
                wraps=checker.os.fsync,
            ) as fsync:
                checker.write_text_once(output, "{}\n")

            self.assertEqual(fsync.call_count, 2)

    def test_contract_check_removes_partial_output_after_directory_fsync_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "input-contract.readiness.json"

            with (
                mock.patch.object(
                    checker.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                checker.write_text_once(output, "{}\n")

            self.assertFalse(output.exists())

    def test_contract_check_rehashes_after_parent_fsync(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "input-contract.readiness.json"
            real_fsync_directory = checker.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    checker,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "contract readiness output changed during write",
                ),
            ):
                checker.write_text_once(output, "{}\n")

            self.assertFalse(output.exists())

    def test_contract_check_sha256_rejects_symlinked_hash_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "input-contract.readiness.json"
            output.write_text("{}\n", encoding="utf-8")

            linked_output = root / "input-contract.link.json"
            linked_output.symlink_to(output)
            with self.assertRaisesRegex(
                ValueError,
                "input-contract\\.link\\.json SHA-256 input must be a real file",
            ):
                checker.sha256(linked_output)

            real_parent = root / "real-readiness"
            real_parent.mkdir()
            linked_parent = root / "linked-readiness"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            (real_parent / "input-contract.readiness.json").write_text(
                "{}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "input-contract\\.readiness\\.json SHA-256 input parent may not be a symlink",
            ):
                checker.sha256(linked_parent / "input-contract.readiness.json")

    def test_contract_check_rejects_output_below_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-readiness"
            real_parent.mkdir()
            linked_parent = root / "linked-readiness"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                checker.write_text_once(
                    linked_parent / "missing" / "input-contract.readiness.json",
                    "{}\n",
                )

            self.assertFalse((real_parent / "missing").exists())

    def test_contract_check_rejects_existing_output_dir_below_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-readiness"
            real_parent.mkdir()
            (real_parent / "existing").mkdir()
            linked_parent = root / "linked-readiness"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                checker.write_text_once(
                    linked_parent / "existing" / "input-contract.readiness.json",
                    "{}\n",
                )

            self.assertFalse(
                (real_parent / "existing" / "input-contract.readiness.json").exists()
            )

    def test_finalizer_binds_all_three_outputs_and_attests_final_primary(self):
        contract = CustodyFixture().finalize()
        self.assertTrue(contract["attestations"]["final_primary_wgs_artifacts"])
        self.assertEqual(contract["custody"]["status"], "passed")
        self.assertEqual(
            contract["custody"]["checks"],
            finalizer.EXPECTED_FINALIZED_CUSTODY_CHECKS,
        )
        self.assertEqual(
            contract["custody"]["final_primary_artifacts"],
            {key: contract["artifacts"][key] for key in finalizer.FINAL_OUTPUTS},
        )
        self.assertEqual(checker.validate(contract)["overall_status"], "ready")

    def test_finalizer_rejects_contract_that_remains_blocked_after_custody_binding(self):
        fixture = CustodyFixture()
        fixture.pending["routes"] = ["facets_scarhrd"]

        with self.assertRaisesRegex(
            ValueError,
            "finalized input contract is not ready: facets_scarhrd",
        ):
            fixture.finalize()

    def test_finalizer_main_uses_hashes_from_loaded_receipt_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = CustodyFixture()
            pending = root / "pending.json"
            freeze = root / "freeze.json"
            freeze_anchor = root / "freeze-anchor.json"
            exact = root / "exact.json"
            cross = root / "cross.json"
            cross_anchor = root / "cross-anchor.json"
            output = root / "contract.json"
            write_json(pending, fixture.pending)
            write_json(freeze, fixture.freeze)
            fixture.exact["freeze_receipt_sha256"] = finalizer.sha256(freeze)
            write_json(exact, fixture.exact)
            write_json(cross, fixture.cross)

            def write_anchor(
                path: Path,
                receipt: Path,
                *,
                prefix: str,
                version: str,
                checks: dict[str, bool],
            ) -> None:
                digest = finalizer.sha256(receipt)
                write_json(
                    path,
                    {
                        "schema_version": 1,
                        "status": "passed",
                        "receipt_sha256": digest,
                        "receipt_bytes": receipt.stat().st_size,
                        "receipt_uri": f"s3://{BUCKET}/{prefix}/{digest}.json",
                        "receipt_version_id": version,
                        "checks": dict(checks),
                    },
                )

            write_anchor(
                freeze_anchor,
                freeze,
                prefix="freeze",
                version="freeze-receipt-version",
                checks=finalizer.EXPECTED_FINAL_FREEZE_ANCHOR_CHECKS,
            )
            write_anchor(
                cross_anchor,
                cross,
                prefix="cross",
                version="cross-receipt-version",
                checks=finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS,
            )
            original_hashes = {
                "final freeze receipt": finalizer.sha256(freeze),
                "exact materialization": finalizer.sha256(exact),
                "cross-check materialization receipt": finalizer.sha256(cross),
            }
            rewritten_labels: set[str] = set()
            original_load = finalizer.load_object_with_sha256

            def load_then_rewrite(
                path: Path, label: str
            ) -> tuple[dict[str, object], str, int]:
                value, digest, byte_count = original_load(path, label)
                if label in original_hashes:
                    rewritten = json.loads(path.read_text(encoding="utf-8"))
                    rewritten["rewritten_after_parse"] = label
                    write_json(path, rewritten)
                    rewritten_labels.add(label)
                return value, digest, byte_count

            argv = [
                "finalize_input_contract.py",
                "--pending-contract",
                str(pending),
                "--final-freeze-receipt",
                str(freeze),
                "--final-freeze-anchor",
                str(freeze_anchor),
                "--exact-materialization-receipt",
                str(exact),
                "--crosscheck-materialization-receipt",
                str(cross),
                "--crosscheck-materialization-anchor",
                str(cross_anchor),
                "--expected-crosscheck-materializer-sha256",
                fixture.materializer_sha,
                "--output",
                str(output),
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    finalizer,
                    "load_object_with_sha256",
                    side_effect=load_then_rewrite,
                ),
            ):
                self.assertEqual(finalizer.main(), 0)

            self.assertEqual(rewritten_labels, set(original_hashes))
            self.assertNotEqual(
                finalizer.sha256(freeze), original_hashes["final freeze receipt"]
            )
            self.assertNotEqual(
                finalizer.sha256(exact), original_hashes["exact materialization"]
            )
            self.assertNotEqual(
                finalizer.sha256(cross),
                original_hashes["cross-check materialization receipt"],
            )
            contract = json.loads(output.read_text(encoding="utf-8"))
            custody = contract["custody"]
            self.assertEqual(
                custody["final_freeze_receipt_sha256"],
                original_hashes["final freeze receipt"],
            )
            self.assertEqual(
                custody["exact_materialization_receipt_sha256"],
                original_hashes["exact materialization"],
            )
            self.assertEqual(
                custody["crosscheck_materialization_receipt_sha256"],
                original_hashes["cross-check materialization receipt"],
            )

    def test_finalizer_rejects_loaded_receipt_that_changes_during_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "final-freeze-receipt.json"
            write_json(receipt, CustodyFixture().freeze)
            original_sha256 = finalizer.sha256
            mutated = False

            def mutate_before_stability_hash(path: Path) -> str:
                nonlocal mutated
                if path == receipt and not mutated:
                    mutated = True
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    payload["status"] = "raced"
                    write_json(path, payload)
                return original_sha256(path)

            with (
                patch.object(
                    finalizer,
                    "sha256",
                    side_effect=mutate_before_stability_hash,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "final freeze receipt changed during read",
                ),
            ):
                finalizer.load_object_with_sha256(receipt, "final freeze receipt")

    def test_contract_check_requires_exact_finalized_custody_checks(self):
        cases = {
            "unexpected": lambda checks: checks.__setitem__("future_check", True),
            "truthy_integer": lambda checks: checks.__setitem__(
                "sbs96_independently_rederived_from_final_pass_vcf",
                1,
            ),
        }

        for label, mutate in cases.items():
            with self.subTest(label=label):
                contract = CustodyFixture().finalize()
                mutate(contract["custody"]["checks"])

                result = checker.validate(contract)

                self.assertEqual(result["overall_status"], "blocked")
                self.assertTrue(
                    any(
                        "custody.checks must exactly match" in reason
                        for route in result["routes"].values()
                        for reason in route["reasons"]
                    )
                )

    def test_contract_publication_rejects_truthy_dry_run_preflight_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            dry_run = root / "anchor.dry.json"
            anchor = root / "anchor.json"
            write_json(contract, CustodyFixture().finalize())
            self.write_contract_dry_run_receipt(dry_run, contract)
            receipt = json.loads(dry_run.read_text(encoding="utf-8"))
            receipt["checks"]["destination_history_empty"] = 1
            write_json(dry_run, receipt)
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
                "--dry-run-receipt",
                str(dry_run),
                "--apply",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    publisher,
                    "aws_json",
                    return_value={"Status": "Enabled"},
                ),
                patch.object(
                    publisher,
                    "put_create_only",
                    side_effect=AssertionError("put called"),
                ),
                self.assertRaisesRegex(SystemExit, "preflight checks failed"),
            ):
                publisher.main()

            self.assertFalse(anchor.exists())

    def test_contract_check_hash_and_version_fields_must_be_exact_strings(self):
        numeric_sha256 = int("1" * 64)
        cases = (
            (
                "reference_sha256",
                lambda contract: contract["reference"]["fasta"].update(
                    {"sha256": numeric_sha256}
                ),
                (
                    "reference.fasta must have an approved private Diana S3 URI, "
                    "exact VersionId, and 64-hex SHA-256"
                ),
            ),
            (
                "artifact_sha256",
                lambda contract: contract["artifacts"]["sbs96_matrix"].update(
                    {"sha256": numeric_sha256}
                ),
                (
                    "artifacts.sbs96_matrix requires an approved private Diana "
                    "S3 URI, exact VersionId, and 64-hex SHA-256"
                ),
            ),
            (
                "artifact_version",
                lambda contract: contract["artifacts"]["sbs96_matrix"].update(
                    {"version_id": 1234567890}
                ),
                (
                    "artifacts.sbs96_matrix requires an approved private Diana "
                    "S3 URI, exact VersionId, and 64-hex SHA-256"
                ),
            ),
            (
                "custody_sha256",
                lambda contract: contract["custody"].update(
                    {"finalizer_script_sha256": numeric_sha256}
                ),
                "custody.finalizer_script_sha256 must be an exact SHA-256",
            ),
            (
                "custody_version",
                lambda contract: contract["custody"].update(
                    {"final_freeze_receipt_version_id": 1234567890}
                ),
                "custody.final_freeze_receipt_version_id must be an exact S3 VersionId",
            ),
        )

        for label, mutate, reason in cases:
            with self.subTest(label=label):
                contract = CustodyFixture().finalize()
                mutate(contract)

                result = checker.validate(contract)

                self.assertEqual(result["overall_status"], "blocked")
                self.assertTrue(
                    any(
                        reason == observed
                        for route in result["routes"].values()
                        for observed in route["reasons"]
                    )
                )

    def test_contract_check_sha256_helper_requires_lowercase_strings(self):
        self.assertTrue(checker.valid_sha256("a" * 64))
        self.assertFalse(checker.valid_sha256("A" * 64))
        self.assertFalse(checker.valid_sha256(int("1" * 64)))

    def test_contract_check_blocks_malformed_chord_fastq_lane_objects(self):
        contract = CustodyFixture().finalize()
        contract["routes"] = ["oncoanalyser_chord"]
        contract["attestations"]["fastq_checksums_match_delivery_manifest"] = True
        contract["fastq_lanes"] = [
            {
                "role": "tumor",
                "r1": private_blob(
                    "deterministic/fastq/tumor_R1.fastq.gz",
                    "b" * 64,
                    "tumor-r1-version",
                ),
                "r2": private_blob(
                    "deterministic/fastq/tumor_R2.fastq.gz",
                    "c" * 64,
                    "tumor-r2-version",
                ),
            },
            "not-a-lane-object",
            {
                "role": "normal",
                "r1": private_blob(
                    "deterministic/fastq/normal_R1.fastq.gz",
                    "d" * 64,
                    "normal-r1-version",
                ),
                "r2": private_blob(
                    "deterministic/fastq/normal_R2.fastq.gz",
                    "e" * 64,
                    "normal-r2-version",
                ),
            },
        ]

        result = checker.validate(contract)
        reasons = result["routes"]["oncoanalyser_chord"]["reasons"]

        self.assertEqual(result["overall_status"], "blocked")
        self.assertIn("fastq_lanes[1] must be an object", reasons)
        self.assertNotIn(
            "at least one tumor and one normal FASTQ lane are required",
            reasons,
        )

    def test_contract_check_blocks_non_list_chord_fastq_lanes(self):
        contract = CustodyFixture().finalize()
        contract["routes"] = ["oncoanalyser_chord"]
        contract["attestations"]["fastq_checksums_match_delivery_manifest"] = True
        contract["fastq_lanes"] = {"role": "tumor"}

        result = checker.validate(contract)
        reasons = result["routes"]["oncoanalyser_chord"]["reasons"]

        self.assertEqual(result["overall_status"], "blocked")
        self.assertIn("fastq_lanes must be a list of lane objects", reasons)
        self.assertIn("at least one tumor and one normal FASTQ lane are required", reasons)

    def test_contract_check_rejects_non_integer_custody_schema_version(self):
        contract = CustodyFixture().finalize()
        contract["custody"]["schema_version"] = 1.0

        result = checker.validate(contract)

        self.assertEqual(result["overall_status"], "blocked")
        self.assertTrue(
            any(
                "custody must be a passed schema-1 finalization record" in reason
                for route in result["routes"].values()
                for reason in route["reasons"]
            )
        )

    def test_contract_check_schema_version_checks_use_exact_integer_helper(self):
        cases = (
            (1, 1, True),
            (1.0, 1, False),
            ("1", 1, False),
            (2, 1, False),
            (None, 1, False),
            (True, 1, False),
            (False, 0, False),
        )
        for value, expected, accepted in cases:
            with self.subTest(value=value, expected=expected):
                self.assertIs(
                    checker.exact_schema_version(
                        {"schema_version": value},
                        expected,
                    ),
                    accepted,
                )

    def test_contract_check_schema_version_checks_avoid_raw_comparisons(self):
        module = ast.parse(
            (ROOT / "scripts/check_contract.py").read_text(encoding="utf-8")
        )
        parent_by_child = {
            child: parent
            for parent in ast.walk(module)
            for child in ast.iter_child_nodes(parent)
        }

        def in_exact_schema_helper(node: ast.AST) -> bool:
            parent = parent_by_child.get(node)
            while parent is not None:
                if isinstance(parent, ast.FunctionDef):
                    return parent.name == "exact_schema_version"
                parent = parent_by_child.get(parent)
            return False

        raw_schema_version_comparisons = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Compare)
            and "schema_version" in ast.unparse(node)
            and not in_exact_schema_helper(node)
        ]

        self.assertEqual(raw_schema_version_comparisons, [])

    def test_finalized_custody_check_inventory_matches_checker(self):
        self.assertEqual(
            finalizer.EXPECTED_FINALIZED_CUSTODY_CHECKS,
            checker.EXPECTED_CUSTODY_CHECKS,
        )
        self.assertEqual(
            publisher.EXPECTED_FINALIZED_CUSTODY_CHECKS,
            finalizer.EXPECTED_FINALIZED_CUSTODY_CHECKS,
        )

    def test_contract_publication_requires_exact_finalized_custody_checks(self):
        publisher.require_finalized_custody(
            {
                "status": "passed",
                "checks": dict(publisher.EXPECTED_FINALIZED_CUSTODY_CHECKS),
            }
        )

        for label, mutate in (
            ("missing", lambda checks: checks.pop("full_freeze_exactly_materialized")),
            ("unexpected", lambda checks: checks.__setitem__("future_check", True)),
            (
                "failed",
                lambda checks: checks.__setitem__(
                    "sbs96_independently_rederived_from_final_pass_vcf",
                    False,
                ),
            ),
            (
                "truthy_integer",
                lambda checks: checks.__setitem__(
                    "sbs96_independently_rederived_from_final_pass_vcf",
                    1,
                ),
            ),
        ):
            with self.subTest(label=label):
                checks = dict(publisher.EXPECTED_FINALIZED_CUSTODY_CHECKS)
                mutate(checks)

                with self.assertRaisesRegex(
                    SystemExit,
                    "lacks passed custody evidence",
                ):
                    publisher.require_finalized_custody(
                        {"status": "passed", "checks": checks}
                    )

    def test_finalizer_rejects_crosscheck_source_not_in_exact_freeze(self):
        fixture = CustodyFixture()
        fixture.cross["source_custody"]["vcf"]["version_id"] = "raced-version"
        with self.assertRaisesRegex(ValueError, "not the exact final freeze"):
            fixture.finalize()

    def test_finalizer_rejects_coerced_crosscheck_custody_hashes(self):
        numeric_sha256 = int("1" * 64)

        def coerce_exact_freeze_hash(fixture: CustodyFixture) -> None:
            fixture.freeze_sha = "1" * 64
            fixture.freeze_anchor["receipt_sha256"] = "1" * 64
            fixture.exact["freeze_receipt_sha256"] = numeric_sha256

        def coerce_crosscheck_script(fixture: CustodyFixture) -> None:
            fixture.materializer_sha = "1" * 64
            fixture.cross["script_sha256"] = numeric_sha256

        def coerce_reference_source(fixture: CustodyFixture) -> None:
            fixture.cross["source_custody"]["fasta"]["sha256"] = numeric_sha256

        for label, mutate, message in (
            (
                "exact_freeze_hash",
                coerce_exact_freeze_hash,
                "exact-version materialization freeze receipt is not an exact SHA-256",
            ),
            (
                "crosscheck_script",
                coerce_crosscheck_script,
                "cross-check materializer script is not an exact SHA-256",
            ),
            (
                "reference_source",
                coerce_reference_source,
                "cross-check reference fasta is not an exact SHA-256",
            ),
        ):
            with self.subTest(label=label):
                fixture = CustodyFixture()
                mutate(fixture)

                with self.assertRaisesRegex(ValueError, message):
                    fixture.finalize()

    def test_finalizer_rejects_coerced_version_ids(self):
        def coerce_freeze_anchor(fixture: CustodyFixture) -> None:
            fixture.freeze_anchor["receipt_version_id"] = True

        def coerce_final_freeze_destination(fixture: CustodyFixture) -> None:
            fixture.freeze["objects"][0]["destination"]["version_id"] = True
            fixture.freeze["destination_inventory"][0]["version_id"] = True

        def coerce_crosscheck_reference(fixture: CustodyFixture) -> None:
            fixture.pending["reference"]["fasta"]["version_id"] = True
            fixture.cross["source_custody"]["fasta"]["version_id"] = True

        def coerce_crosscheck_output(fixture: CustodyFixture) -> None:
            filename = "staged_input_validation.json"
            fixture.cross["outputs"][filename]["version_id"] = True
            inventory = next(
                row
                for row in fixture.cross["destination_inventory"]
                if row["filename"] == filename
            )
            inventory["version_id"] = True

        for label, mutate, message in (
            (
                "freeze_anchor",
                coerce_freeze_anchor,
                "final freeze anchor lacks an exact S3 VersionId",
            ),
            (
                "final_freeze_destination",
                coerce_final_freeze_destination,
                "frozen destination lacks an exact S3 VersionId",
            ),
            (
                "crosscheck_reference",
                coerce_crosscheck_reference,
                "cross-check reference fasta lacks an exact S3 VersionId",
            ),
            (
                "crosscheck_output",
                coerce_crosscheck_output,
                "staged_input_validation.json materializer output "
                "lacks an exact S3 VersionId",
            ),
        ):
            with self.subTest(label=label):
                fixture = CustodyFixture()
                mutate(fixture)

                with self.assertRaisesRegex(ValueError, message):
                    fixture.finalize()

    def test_finalizer_rejects_coerced_exact_materialization_version_id(self):
        fixture = CustodyFixture()
        exact = json.loads(json.dumps(fixture.exact))
        exact["objects"] = exact["objects"][:1]
        exact["object_count"] = 1
        exact["passed_count"] = 1
        row = exact["objects"][0]
        row["version_id"] = True
        frozen = json.loads(
            json.dumps(fixture.freeze["objects"][0]["destination"])
        )
        frozen["version_id"] = True
        freeze_uri = f"s3://{row['bucket']}/{row['key']}"

        with self.assertRaisesRegex(
            ValueError,
            "exact-version materialization row lacks an exact S3 VersionId",
        ):
            finalizer.validate_exact_materialization(
                exact,
                fixture.freeze_sha,
                {freeze_uri: frozen},
            )

    def test_finalizer_version_guard_avoids_raw_string_coercion(self):
        script = ROOT / "scripts/finalize_input_contract.py"
        source = script.read_text()
        module = ast.parse(source, filename=str(script))
        require_version = next(
            node
            for node in ast.walk(module)
            if isinstance(node, ast.FunctionDef) and node.name == "require_version"
        )
        raw_string_coercions = [
            ast.get_source_segment(source, node)
            for node in ast.walk(require_version)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
        ]

        self.assertEqual(raw_string_coercions, [])

    def test_finalizer_rejects_incomplete_materialization_row_checks(self):
        fixture = CustodyFixture()
        fixture.exact["objects"][0]["checks"].pop("checksum_type")
        with self.assertRaisesRegex(ValueError, "exact custody checks"):
            fixture.finalize()

    def test_finalizer_rejects_unexpected_materialization_row_checks(self):
        fixture = CustodyFixture()
        fixture.exact["objects"][0]["checks"]["future_check"] = True
        with self.assertRaisesRegex(ValueError, "exact custody checks"):
            fixture.finalize()

    def test_finalizer_rejects_failed_materialization_row_checks(self):
        fixture = CustodyFixture()
        fixture.exact["objects"][0]["checks"]["checksum_type"] = False
        with self.assertRaisesRegex(ValueError, "exact custody checks"):
            fixture.finalize()

    def test_finalizer_requires_full_object_materialization_rows(self):
        fixture = CustodyFixture()
        fixture.exact["objects"][0].pop("checksum_type")
        with self.assertRaisesRegex(ValueError, "stale or missing metadata"):
            fixture.finalize()

    def test_finalizer_materialization_check_inventory_matches_producers(self):
        self.assertEqual(
            finalizer.EXPECTED_MATERIALIZATION_CHECKS,
            materializer.EXPECTED_MATERIALIZATION_CHECKS,
        )
        self.assertEqual(
            set(finalizer.EXPECTED_MATERIALIZATION_CHECKS),
            submitter.EXPECTED_MATERIALIZATION_ROW_CHECKS,
        )

    def test_finalizer_rejects_crosscheck_output_without_exact_sha256_checksum(self):
        fixture = CustodyFixture()
        fixture.cross["outputs"]["sbs96.csv"]["checksums"]["ChecksumSHA256"] = (
            checksum_sha256("0" * 64)
        )
        with self.assertRaisesRegex(ValueError, "full-object SHA-256"):
            fixture.finalize()

    def test_finalizer_rejects_staged_validation_output_without_full_object_checksum(
        self,
    ):
        fixture = CustodyFixture()
        fixture.cross["outputs"]["staged_input_validation.json"]["checksums"][
            "ChecksumType"
        ] = "COMPOSITE"
        with self.assertRaisesRegex(ValueError, "full-object SHA-256"):
            fixture.finalize()

    def test_finalizer_rejects_staged_validation_output_with_failed_checks(self):
        fixture = CustodyFixture()
        fixture.cross["outputs"]["staged_input_validation.json"]["checks"][
            "sha256_checksum_exact"
        ] = False
        with self.assertRaisesRegex(ValueError, "exact custody checks"):
            fixture.finalize()

    def test_finalizer_rejects_incomplete_crosscheck_receipt_checks(self):
        fixture = CustodyFixture()
        fixture.cross["checks"].pop("destination_prefix_initially_empty")
        with self.assertRaisesRegex(ValueError, "exact custody checks"):
            fixture.finalize()

    def test_finalizer_rejects_non_exact_crosscheck_initial_history_count(self):
        for label, value in (
            ("boolean", False),
            ("float", 0.0),
        ):
            with self.subTest(label=label):
                fixture = CustodyFixture()
                fixture.cross["destination_initial_version_history_count"] = value

                with self.assertRaisesRegex(ValueError, "one-shot publication"):
                    fixture.finalize()

    def test_finalizer_rejects_unexpected_crosscheck_output_checks(self):
        fixture = CustodyFixture()
        fixture.cross["outputs"]["somatic.pass.vcf.gz"]["checks"]["future"] = True
        with self.assertRaisesRegex(ValueError, "exact custody checks"):
            fixture.finalize()

    def test_finalizer_crosscheck_check_inventory_matches_materializer(self):
        self.assertEqual(
            finalizer.EXPECTED_CROSSCHECK_CHECKS,
            crosscheck_materializer.EXPECTED_RECEIPT_CHECKS,
        )
        self.assertEqual(
            finalizer.EXPECTED_CROSSCHECK_OUTPUT_CHECKS,
            crosscheck_materializer.EXPECTED_UPLOAD_CHECKS,
        )

    def test_finalizer_rejects_incomplete_freeze_or_history(self):
        fixture = CustodyFixture()
        fixture.freeze["destination_initial_version_history_count"] = 1
        with self.assertRaisesRegex(ValueError, "one-shot freeze"):
            fixture.finalize()

    def test_finalizer_rejects_non_exact_freeze_initial_history_count(self):
        for label, value in (
            ("boolean", False),
            ("float", 0.0),
        ):
            with self.subTest(label=label):
                fixture = CustodyFixture()
                fixture.freeze["destination_initial_version_history_count"] = value

                with self.assertRaisesRegex(ValueError, "one-shot freeze"):
                    fixture.finalize()

    def test_finalizer_rejects_boolean_final_freeze_object_count(self):
        fixture = CustodyFixture()
        fixture.freeze["objects"] = fixture.freeze["objects"][:1]
        fixture.freeze["destination_inventory"] = fixture.freeze[
            "destination_inventory"
        ][:1]
        fixture.freeze["object_count"] = True
        fixture.freeze["passed_count"] = 1

        with self.assertRaisesRegex(ValueError, "one-shot freeze"):
            finalizer.validate_freeze(
                fixture.freeze,
                fixture.freeze_anchor,
                fixture.freeze_sha,
            )

    def test_finalizer_rejects_incomplete_final_freeze_checks(self):
        fixture = CustodyFixture()
        fixture.freeze["checks"].pop("execution_receipt_bound")
        with self.assertRaisesRegex(ValueError, "exact custody checks"):
            fixture.finalize()

    def test_finalizer_rejects_unexpected_final_freeze_row_checks(self):
        fixture = CustodyFixture()
        fixture.freeze["objects"][0]["checks"]["future_check"] = True
        with self.assertRaisesRegex(ValueError, "exact custody checks"):
            fixture.finalize()

    def test_finalizer_rejects_failed_final_freeze_row_checks(self):
        fixture = CustodyFixture()
        fixture.freeze["objects"][0]["checks"]["exact_kms_matches"] = False
        with self.assertRaisesRegex(ValueError, "exact custody checks"):
            fixture.finalize()

    def test_finalizer_rejects_final_freeze_rows_without_sse_kms(self):
        fixture = CustodyFixture()
        fixture.freeze["objects"][0]["destination"].pop("server_side_encryption")
        with self.assertRaisesRegex(ValueError, "stale or missing metadata"):
            fixture.finalize()

    def test_finalizer_final_freeze_check_inventory_matches_submitter(self):
        self.assertEqual(
            set(finalizer.EXPECTED_FINAL_FREEZE_CHECKS),
            submitter.EXPECTED_FINAL_FREEZE_CHECKS,
        )
        self.assertEqual(
            set(finalizer.EXPECTED_FINAL_ROW_CHECKS),
            submitter.EXPECTED_FINAL_ROW_CHECKS,
        )

    def test_finalizer_rejects_stale_receipt_envelopes(self):
        for label, mutate in (
            ("freeze top-level", lambda fixture: fixture.freeze.update(legacy=True)),
            (
                "freeze object row",
                lambda fixture: fixture.freeze["objects"][0].update(legacy=True),
            ),
            (
                "freeze source row",
                lambda fixture: fixture.freeze["objects"][0]["source"].update(
                    legacy=True
                ),
            ),
            (
                "freeze destination row",
                lambda fixture: fixture.freeze["objects"][0]["destination"].update(
                    legacy=True
                ),
            ),
            (
                "freeze destination inventory row",
                lambda fixture: fixture.freeze["destination_inventory"][0].update(
                    legacy=True
                ),
            ),
            (
                "exact materialization top-level",
                lambda fixture: fixture.exact.update(legacy=True),
            ),
            (
                "exact materialization object row",
                lambda fixture: fixture.exact["objects"][0].update(legacy=True),
            ),
            (
                "cross-check top-level",
                lambda fixture: fixture.cross.update(legacy=True),
            ),
            (
                "cross-check source row",
                lambda fixture: fixture.cross["source_custody"]["vcf"].update(
                    legacy=True
                ),
            ),
            (
                "cross-check output row",
                lambda fixture: fixture.cross["outputs"]["sbs96.csv"].update(
                    legacy=True
                ),
            ),
            (
                "cross-check inventory row",
                lambda fixture: fixture.cross["destination_inventory"][0].update(
                    legacy=True
                ),
            ),
        ):
            with self.subTest(label=label):
                fixture = CustodyFixture()
                mutate(fixture)

                with self.assertRaisesRegex(
                    ValueError,
                    "stale or missing metadata",
                ):
                    fixture.finalize()

    def test_finalizer_rejects_final_freeze_inventory_drift(self):
        fixture = CustodyFixture()
        fixture.freeze["destination_inventory"][0]["version_id"] = "stale-version"

        with self.assertRaisesRegex(
            ValueError,
            "destination inventory differs",
        ):
            fixture.finalize()

    def test_finalizer_rejects_boolean_destination_inventory_bytes(self):
        destination = {
            "key": "runs/subject01/unit/deterministic/final/sbs96.csv",
            "version_id": "frozen-version",
            "bytes": 1,
            "etag": "destination-etag",
            "checksums": {"ChecksumType": "FULL_OBJECT", "ChecksumSHA256": "sha256"},
            "checksum_type": "FULL_OBJECT",
            "kms_key_id": KMS,
        }
        receipt = {
            "destination_inventory": [
                {
                    **destination,
                    "relative_key": "signatures/sbs96.csv",
                    "bytes": True,
                }
            ]
        }

        with self.assertRaisesRegex(
            ValueError,
            "destination inventory differs",
        ):
            finalizer.require_final_destination_inventory(
                receipt,
                {"signatures/sbs96.csv": destination},
            )

    def test_finalizer_rejects_boolean_destination_inventory_version(self):
        destination = {
            "key": "runs/subject01/unit/deterministic/final/sbs96.csv",
            "version_id": True,
            "bytes": 1,
            "etag": "destination-etag",
            "checksums": {"ChecksumType": "FULL_OBJECT", "ChecksumSHA256": "sha256"},
            "checksum_type": "FULL_OBJECT",
            "kms_key_id": KMS,
        }
        receipt = {
            "destination_inventory": [
                {
                    **destination,
                    "relative_key": "signatures/sbs96.csv",
                }
            ]
        }

        with self.assertRaisesRegex(
            ValueError,
            "destination inventory lacks an exact S3 VersionId",
        ):
            finalizer.require_final_destination_inventory(
                receipt,
                {"signatures/sbs96.csv": destination},
            )

    def test_finalizer_rejects_boolean_exact_materialization_counts(self):
        fixture = CustodyFixture()
        exact = json.loads(json.dumps(fixture.exact))
        exact["objects"] = exact["objects"][:1]
        exact["object_count"] = True
        exact["passed_count"] = 1
        row = exact["objects"][0]
        freeze_uri = f"s3://{row['bucket']}/{row['key']}"

        with self.assertRaisesRegex(ValueError, "incomplete or unbound"):
            finalizer.validate_exact_materialization(
                exact,
                fixture.freeze_sha,
                {freeze_uri: fixture.freeze["objects"][0]["destination"]},
            )

    def test_finalizer_rejects_string_exact_materialization_bytes(self):
        fixture = CustodyFixture()
        exact = json.loads(json.dumps(fixture.exact))
        exact["objects"] = exact["objects"][:1]
        exact["object_count"] = 1
        exact["passed_count"] = 1
        exact["objects"][0]["bytes"] = str(exact["objects"][0]["bytes"])
        row = exact["objects"][0]
        freeze_uri = f"s3://{row['bucket']}/{row['key']}"

        with self.assertRaisesRegex(ValueError, "exact-version materialization"):
            finalizer.validate_exact_materialization(
                exact,
                fixture.freeze_sha,
                {freeze_uri: fixture.freeze["objects"][0]["destination"]},
            )

    def test_finalizer_rejects_crosscheck_destination_inventory_key_drift(self):
        fixture = CustodyFixture()
        fixture.cross["destination_inventory"][0]["key"] = (
            "runs/subject01/stale-run/deterministic/final/sbs96.csv"
        )

        with self.assertRaisesRegex(
            ValueError,
            "cross-check destination inventory differs",
        ):
            fixture.finalize()

    def test_finalizer_rejects_boolean_crosscheck_output_and_inventory_bytes(self):
        fixture = CustodyFixture()
        filename = finalizer.FINAL_OUTPUTS["somatic_vcf"]
        fixture.cross["outputs"][filename]["bytes"] = True
        for row in fixture.cross["destination_inventory"]:
            if row["filename"] == filename:
                row["bytes"] = True
                break

        with self.assertRaisesRegex(
            ValueError,
            "cross-check destination inventory differs",
        ):
            fixture.finalize()

    def test_finalizer_accepts_exact_materialization_recovery_metadata(self):
        fixture = CustodyFixture()
        fixture.exact.update(
            {
                "recovered_from_status": "failed",
                "prior_receipt_sha256": "0" * 64,
                "prior_error": "ValueError: transient exact download failure",
                "recovered_prepared_cutover": True,
            }
        )

        contract = fixture.finalize()

        self.assertEqual(contract["custody"]["status"], "passed")

    def test_finalizer_rejects_non_integer_receipt_schema_versions(self):
        for label, mutate, message in (
            (
                "final freeze",
                lambda fixture: fixture.freeze.__setitem__("schema_version", 1.0),
                "one-shot freeze",
            ),
            (
                "exact materialization",
                lambda fixture: fixture.exact.__setitem__("schema_version", 1.0),
                "incomplete or unbound",
            ),
            (
                "cross-check materialization",
                lambda fixture: fixture.cross.__setitem__("schema_version", 2.0),
                "one-shot publication",
            ),
        ):
            with self.subTest(label=label):
                fixture = CustodyFixture()
                mutate(fixture)

                with self.assertRaisesRegex(ValueError, message):
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
                    "checks": dict(finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS),
                },
            )
            finalizer.validate_anchor(
                receipt,
                anchor,
                "unit",
                finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS,
            )
            value = json.loads(anchor.read_text())
            value["receipt_version_id"] = ""
            write_json(anchor, value)
            with self.assertRaisesRegex(ValueError, "VersionId"):
                finalizer.validate_anchor(
                    receipt,
                    anchor,
                    "unit",
                    finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS,
                )

    def test_anchor_validation_requires_exact_integer_receipt_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            anchor = root / "anchor.json"
            write_json(
                anchor,
                {
                    "schema_version": 1,
                    "status": "passed",
                    "receipt_sha256": finalizer.sha256(receipt),
                    "receipt_bytes": "2",
                    "receipt_uri": f"s3://{BUCKET}/receipts/{finalizer.sha256(receipt)}.json",
                    "receipt_version_id": "receipt-version",
                    "checks": dict(finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS),
                },
            )

            with self.assertRaisesRegex(
                ValueError,
                "unit anchor does not bind the local receipt",
            ):
                finalizer.validate_anchor(
                    receipt,
                    anchor,
                    "unit",
                    finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS,
                )

    def test_anchor_validation_rejects_non_integer_schema_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "receipt.json"
            write_json(receipt, {"status": "passed"})
            anchor = root / "anchor.json"
            write_json(
                anchor,
                {
                    "schema_version": 1.0,
                    "status": "passed",
                    "receipt_sha256": finalizer.sha256(receipt),
                    "receipt_bytes": receipt.stat().st_size,
                    "receipt_uri": f"s3://{BUCKET}/receipts/{finalizer.sha256(receipt)}.json",
                    "receipt_version_id": "receipt-version",
                    "checks": dict(finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS),
                },
            )

            with self.assertRaisesRegex(
                ValueError,
                "unit anchor does not bind the local receipt",
            ):
                finalizer.validate_anchor(
                    receipt,
                    anchor,
                    "unit",
                    finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS,
                )

    def test_anchor_validation_rejects_inexact_anchor_checks(self):
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
                    "checks": {
                        **finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS,
                        "future_check": True,
                    },
                },
            )

            with self.assertRaisesRegex(ValueError, "exact custody checks"):
                finalizer.validate_anchor(
                    receipt,
                    anchor,
                    "unit",
                    finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS,
                )

    def test_finalizer_anchor_check_inventory_matches_producers(self):
        self.assertEqual(
            set(finalizer.EXPECTED_FINAL_FREEZE_ANCHOR_CHECKS),
            submitter.EXPECTED_ANCHOR_CHECKS,
        )
        self.assertEqual(
            finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS,
            crosscheck_materializer.EXPECTED_RECEIPT_ANCHOR_CHECKS,
        )

    def test_anchor_validation_rejects_symlinked_input_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "receipt.json"
            write_json(receipt, {"status": "passed"})
            linked_receipt = root / "linked-receipt.json"
            linked_receipt.symlink_to(receipt)

            with self.assertRaisesRegex(ValueError, "receipt must be a real JSON file"):
                finalizer.validate_anchor(
                    linked_receipt,
                    receipt,
                    "unit",
                    finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS,
                )

    def test_anchor_validation_rejects_input_json_below_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-receipts"
            real_parent.mkdir()
            receipt = real_parent / "receipt.json"
            write_json(receipt, {"status": "passed"})
            linked_parent = root / "linked-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                finalizer.validate_anchor(
                    linked_parent / "receipt.json",
                    receipt,
                    "unit",
                    finalizer.EXPECTED_CROSSCHECK_ANCHOR_CHECKS,
                )

    def test_finalizer_sha256_rejects_symlinked_hash_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_input = root / "real-contract.json"
            linked_input = root / "contract-link.json"
            real_input.write_text("{}\n", encoding="utf-8")
            linked_input.symlink_to(real_input)

            real_parent = root / "real-inputs"
            real_parent.mkdir()
            (real_parent / "contract.json").write_text("{}\n", encoding="utf-8")
            linked_parent = root / "linked-inputs"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            cases = (
                (
                    linked_input,
                    "contract-link.json SHA-256 input must be a real file",
                ),
                (
                    linked_parent / "contract.json",
                    "contract.json SHA-256 input parent may not be a symlink",
                ),
            )
            for path, message in cases:
                with self.subTest(path=path):
                    with self.assertRaisesRegex(ValueError, message):
                        finalizer.sha256(path)

    def test_finalizer_sha256_rejects_hash_input_that_changes_during_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "final-contract.json"
            receipt.write_text('{"stable": true}\n', encoding="utf-8")
            original_sha256_file_once = finalizer.sha256_file_once
            mutated = False

            def mutate_after_first_hash(path: Path) -> str:
                nonlocal mutated
                digest = original_sha256_file_once(path)
                if path == receipt and not mutated:
                    mutated = True
                    path.write_text('{"stable": false}\n', encoding="utf-8")
                return digest

            with (
                patch.object(
                    finalizer,
                    "sha256_file_once",
                    side_effect=mutate_after_first_hash,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "final-contract.json SHA-256 input changed during read",
                ),
            ):
                finalizer.sha256(receipt)

    def test_finalizer_rejects_duplicate_input_json_object_names(self):
        for label, payload, key, stale in (
            (
                "pending contract",
                CustodyFixture().pending,
                "run_alias",
                "subject99",
            ),
            (
                "exact materialization",
                CustodyFixture().exact,
                "schema_version",
                0,
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / f"{label.replace(' ', '-')}.json"
                write_json(path, payload)
                write_duplicate_json_field(path, key, stale)

                with self.assertRaisesRegex(
                    ValueError,
                    f"duplicate JSON object name in {label}: {key}",
                ):
                    finalizer.load_object(path, label)

    def test_contract_check_rejects_symlinked_contract_without_writing_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            linked_contract = root / "linked-contract.json"
            linked_contract.symlink_to(contract)
            readiness = root / "input-contract.readiness.json"
            argv = [
                "check_contract.py",
                "--contract",
                str(linked_contract),
                "--json-out",
                str(readiness),
            ]

            with (
                patch.object(sys, "argv", argv),
                self.assertRaisesRegex(SystemExit, "contract must be a real JSON file"),
            ):
                checker.main()

            self.assertFalse(readiness.exists())

    def test_contract_check_rejects_contract_below_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-contracts"
            real_parent.mkdir()
            contract = real_parent / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            linked_parent = root / "linked-contracts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            readiness = root / "input-contract.readiness.json"
            argv = [
                "check_contract.py",
                "--contract",
                str(linked_parent / "contract.json"),
                "--json-out",
                str(readiness),
            ]

            with (
                patch.object(sys, "argv", argv),
                self.assertRaisesRegex(SystemExit, "parent may not be a symlink"),
            ):
                checker.main()

            self.assertFalse(readiness.exists())

    def test_contract_check_rejects_duplicate_contract_without_writing_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            write_duplicate_json_field(contract, "run_alias", "subject99")
            readiness = root / "input-contract.readiness.json"
            argv = [
                "check_contract.py",
                "--contract",
                str(contract),
                "--json-out",
                str(readiness),
            ]

            with (
                patch.object(sys, "argv", argv),
                self.assertRaisesRegex(
                    SystemExit,
                    "duplicate JSON object name in contract: run_alias",
                ),
            ):
                checker.main()

            self.assertFalse(readiness.exists())

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
            prefix = f"runs/subject01/{RUN}/deterministic/contracts/"
            dry_run = self.write_contract_dry_run_receipt(
                root / "anchor.dry.json", contract, prefix=prefix
            )

            def fake_get(bucket, key, version_id, destination, region):
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
                str(anchor),
                "--dry-run-receipt",
                str(dry_run),
                "--apply",
            ]
            history = [
                {
                    "history_kind": "version",
                    "Key": f"runs/subject01/{RUN}/deterministic/contracts/{contract_sha}.json",
                    "VersionId": version,
                    "IsLatest": True,
                    "Size": contract.stat().st_size,
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

    def test_contract_publication_rejects_coerced_put_version_before_verification(self):
        cases = (True, "null", "none", "has whitespace")
        for version_id in cases:
            with self.subTest(version_id=version_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                contract = root / "contract.json"
                write_json(contract, CustodyFixture().finalize())
                anchor = root / "anchor.json"
                prefix = f"runs/subject01/{RUN}/deterministic/contracts/"
                dry_run = self.write_contract_dry_run_receipt(
                    root / "anchor.dry.json", contract, prefix=prefix
                )
                argv = [
                    "publish_input_contract.py",
                    "--contract",
                    str(contract),
                    "--destination-prefix",
                    f"s3://{BUCKET}/{prefix}",
                    "--kms-key-arn",
                    KMS,
                    "--anchor-output",
                    str(anchor),
                    "--dry-run-receipt",
                    str(dry_run),
                    "--apply",
                ]

                with (
                    patch.object(sys, "argv", argv),
                    patch.object(
                        publisher,
                        "aws_json",
                        return_value={"Status": "Enabled"},
                    ),
                    patch.object(publisher, "version_history", side_effect=[[], []]),
                    patch.object(
                        publisher,
                        "put_create_only",
                        return_value={"VersionId": version_id},
                    ),
                    patch.object(
                        publisher,
                        "verify_publication",
                        side_effect=AssertionError("verification reached"),
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "create-only put response omitted an exact VersionId",
                    ),
                ):
                    publisher.main()

                value = json.loads(anchor.read_text(encoding="utf-8"))
                self.assertEqual(value["status"], "failed")
                self.assertEqual(value["receipt_version_id"], "")

    def test_contract_publication_verify_publication_emits_expected_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            contract_sha = publisher.sha256(contract)
            version = "contract-version"
            prefix = f"runs/subject01/{RUN}/deterministic/contracts/"
            key = f"{prefix}{contract_sha}.json"
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
            history = [
                {
                    "history_kind": "version",
                    "Key": key,
                    "VersionId": version,
                    "IsLatest": True,
                    "Size": contract.stat().st_size,
                }
            ]

            def fake_get(bucket, object_key, version_id, destination, region):
                destination.write_bytes(contract.read_bytes())
                return dict(metadata)

            with (
                patch.object(publisher, "head", return_value=metadata),
                patch.object(publisher, "get_exact", side_effect=fake_get),
                patch.object(publisher, "version_history", return_value=history),
            ):
                checks = publisher.verify_publication(
                    contract,
                    BUCKET,
                    prefix,
                    key,
                    version,
                    KMS,
                    "us-east-1",
                )

            self.assertEqual(checks, publisher.EXPECTED_CONTRACT_ANCHOR_CHECKS)

    def test_contract_publication_exact_int_rejects_coerced_byte_values(self):
        self.assertTrue(publisher.exact_int(1, 1))

        for value in (True, 1.0, "1"):
            with self.subTest(value=value):
                self.assertFalse(publisher.exact_int(value, 1))

    def test_contract_publication_byte_guards_avoid_raw_content_length_equality(self):
        source = (ROOT / "scripts/publish_input_contract.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        raw_comparisons = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "ContentLength" in segment:
                raw_comparisons.append(f"{node.lineno}: {segment}")

        self.assertEqual(raw_comparisons, [])

    def test_contract_publication_verify_requires_exact_content_lengths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            contract.write_bytes(b"x")
            contract_sha = publisher.sha256(contract)
            checksum = checksum_sha256(contract_sha)
            version = "contract-version"
            prefix = f"runs/subject01/{RUN}/deterministic/contracts/"
            key = f"{prefix}{contract_sha}.json"
            metadata = {
                "VersionId": version,
                "ContentLength": 1,
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": checksum,
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": KMS,
                "Metadata": {"sha256": contract_sha},
            }
            history = [
                {
                    "history_kind": "version",
                    "Key": key,
                    "VersionId": version,
                    "IsLatest": True,
                    "Size": 1,
                }
            ]

            for phase, value in (
                ("head", True),
                ("head", 1.0),
                ("head", "1"),
                ("get", True),
                ("get", 1.0),
                ("get", "1"),
            ):
                with self.subTest(phase=phase, value=value):
                    head_metadata = dict(metadata)
                    get_metadata = dict(metadata)
                    if phase == "head":
                        head_metadata["ContentLength"] = value
                    else:
                        get_metadata["ContentLength"] = value

                    def fake_get(
                        bucket,
                        object_key,
                        version_id,
                        destination,
                        region,
                        get_metadata=get_metadata,
                    ):
                        destination.write_bytes(contract.read_bytes())
                        return dict(get_metadata)

                    with (
                        patch.object(publisher, "head", return_value=head_metadata),
                        patch.object(publisher, "get_exact", side_effect=fake_get),
                        patch.object(
                            publisher, "version_history", return_value=history
                        ),
                    ):
                        checks = publisher.verify_publication(
                            contract,
                            BUCKET,
                            prefix,
                            key,
                            version,
                            KMS,
                            "us-east-1",
                        )

                    self.assertFalse(checks["bytes_exact"])
                    self.assertTrue(checks["single_create_only_version"])

    def test_contract_publication_verify_requires_exact_history_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            contract.write_bytes(b"x")
            contract_sha = publisher.sha256(contract)
            checksum = checksum_sha256(contract_sha)
            version = "contract-version"
            prefix = f"runs/subject01/{RUN}/deterministic/contracts/"
            key = f"{prefix}{contract_sha}.json"
            metadata = {
                "VersionId": version,
                "ContentLength": 1,
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": checksum,
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": KMS,
                "Metadata": {"sha256": contract_sha},
            }

            def fake_get(bucket, object_key, version_id, destination, region):
                destination.write_bytes(contract.read_bytes())
                return dict(metadata)

            for size in (True, 1.0, "1"):
                with self.subTest(size=size):
                    history = [
                        {
                            "history_kind": "version",
                            "Key": key,
                            "VersionId": version,
                            "IsLatest": True,
                            "Size": size,
                        }
                    ]
                    with (
                        patch.object(publisher, "head", return_value=metadata),
                        patch.object(publisher, "get_exact", side_effect=fake_get),
                        patch.object(
                            publisher, "version_history", return_value=history
                        ),
                    ):
                        checks = publisher.verify_publication(
                            contract,
                            BUCKET,
                            prefix,
                            key,
                            version,
                            KMS,
                            "us-east-1",
                        )

                    self.assertTrue(checks["bytes_exact"])
                    self.assertFalse(checks["single_create_only_version"])

    def test_contract_publication_dry_run_emits_exact_preflight_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            anchor = root / "anchor.dry.json"
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
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(publisher, "aws_json", return_value={"Status": "Enabled"}),
                patch.object(publisher, "version_history", return_value=[]),
                patch.object(publisher, "put_create_only") as put_create_only,
            ):
                self.assertEqual(publisher.main(), 0)

            put_create_only.assert_not_called()
            self.assertEqual(
                json.loads(anchor.read_text(encoding="utf-8"))["checks"],
                publisher.EXPECTED_CONTRACT_PREFLIGHT_CHECKS,
            )

    def test_contract_publication_rejects_duplicate_contract_json_before_aws(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            write_duplicate_json_field(contract, "run_alias", "subject99")
            anchor = root / "anchor.dry.json"
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
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    publisher,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
                self.assertRaisesRegex(
                    SystemExit,
                    "duplicate JSON object name in contract: run_alias",
                ),
            ):
                publisher.main()

            self.assertFalse(anchor.exists())

    def test_contract_publication_apply_requires_dry_run_receipt_before_aws(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            argv = [
                "publish_input_contract.py",
                "--contract",
                str(contract),
                "--destination-prefix",
                f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/contracts/",
                "--kms-key-arn",
                KMS,
                "--anchor-output",
                str(root / "anchor.json"),
                "--apply",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    publisher,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
                self.assertRaisesRegex(SystemExit, "requires the matching"),
            ):
                publisher.main()

    def test_contract_publication_rejects_dry_run_receipt_without_apply_before_aws(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            dry_run = root / "anchor.dry.json"
            write_json(contract, CustodyFixture().finalize())
            self.write_contract_dry_run_receipt(dry_run, contract)
            argv = [
                "publish_input_contract.py",
                "--contract",
                str(contract),
                "--destination-prefix",
                f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/contracts/",
                "--kms-key-arn",
                KMS,
                "--anchor-output",
                str(root / "anchor.json"),
                "--dry-run-receipt",
                str(dry_run),
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    publisher,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
                self.assertRaisesRegex(SystemExit, "only valid with --apply"),
            ):
                publisher.main()

    def test_contract_publication_rejects_stale_dry_run_metadata_before_put(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            dry_run = root / "anchor.dry.json"
            anchor = root / "anchor.json"
            write_json(contract, CustodyFixture().finalize())
            self.write_contract_dry_run_receipt(dry_run, contract)
            receipt = json.loads(dry_run.read_text(encoding="utf-8"))
            receipt["stale_receipt_sha256"] = "0" * 64
            write_json(dry_run, receipt)
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
                "--dry-run-receipt",
                str(dry_run),
                "--apply",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(publisher, "aws_json", return_value={"Status": "Enabled"}),
                patch.object(
                    publisher,
                    "put_create_only",
                    side_effect=AssertionError("put called"),
                ),
                self.assertRaisesRegex(SystemExit, "stale or missing metadata"),
            ):
                publisher.main()

            self.assertFalse(anchor.exists())

    def test_contract_publication_rejects_duplicate_dry_run_json_before_put(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            dry_run = root / "anchor.dry.json"
            anchor = root / "anchor.json"
            write_json(contract, CustodyFixture().finalize())
            self.write_contract_dry_run_receipt(dry_run, contract)
            write_duplicate_json_field(dry_run, "status", "failed")
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
                "--dry-run-receipt",
                str(dry_run),
                "--apply",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(publisher, "aws_json", return_value={"Status": "Enabled"}),
                patch.object(
                    publisher,
                    "put_create_only",
                    side_effect=AssertionError("put called"),
                ),
                self.assertRaisesRegex(
                    SystemExit,
                    (
                        "duplicate JSON object name in "
                        "contract publication dry-run receipt: status"
                    ),
                ),
            ):
                publisher.main()

            self.assertFalse(anchor.exists())

    def test_contract_publication_rejects_failed_dry_run_preflight_before_put(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            dry_run = root / "anchor.dry.json"
            anchor = root / "anchor.json"
            write_json(contract, CustodyFixture().finalize())
            self.write_contract_dry_run_receipt(dry_run, contract)
            receipt = json.loads(dry_run.read_text(encoding="utf-8"))
            receipt["checks"]["destination_history_empty"] = False
            write_json(dry_run, receipt)
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
                "--dry-run-receipt",
                str(dry_run),
                "--apply",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(publisher, "aws_json", return_value={"Status": "Enabled"}),
                patch.object(
                    publisher,
                    "put_create_only",
                    side_effect=AssertionError("put called"),
                ),
                self.assertRaisesRegex(SystemExit, "preflight checks failed"),
            ):
                publisher.main()

            self.assertFalse(anchor.exists())

    def test_contract_publication_rejects_stale_dry_run_identity_before_put(self):
        for field, replacement in (
            ("receipt_sha256", "0" * 64),
            ("receipt_bytes", 1),
            ("receipt_uri", f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/contracts/stale.json"),
            ("kms_key_arn", KMS.replace("45aa", "0000")),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                contract = root / "contract.json"
                dry_run = root / "anchor.dry.json"
                anchor = root / "anchor.json"
                write_json(contract, CustodyFixture().finalize())
                self.write_contract_dry_run_receipt(dry_run, contract)
                receipt = json.loads(dry_run.read_text(encoding="utf-8"))
                receipt[field] = replacement
                write_json(dry_run, receipt)
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
                    "--dry-run-receipt",
                    str(dry_run),
                    "--apply",
                ]

                with (
                    patch.object(sys, "argv", argv),
                    patch.object(publisher, "aws_json", return_value={"Status": "Enabled"}),
                    patch.object(
                        publisher,
                        "put_create_only",
                        side_effect=AssertionError("put called"),
                    ),
                    self.assertRaisesRegex(SystemExit, "differs from requested"),
                ):
                    publisher.main()

                self.assertFalse(anchor.exists())

    def test_contract_publication_rejects_missing_verification_check(self):
        checks = dict(publisher.EXPECTED_CONTRACT_ANCHOR_CHECKS)
        checks.pop("version_exact")

        self.assert_contract_publication_rejects_checks(checks)

    def test_contract_publication_rejects_unexpected_verification_check(self):
        checks = dict(publisher.EXPECTED_CONTRACT_ANCHOR_CHECKS)
        checks["future_check"] = True

        self.assert_contract_publication_rejects_checks(checks)

    def test_contract_publication_rejects_failed_verification_check(self):
        checks = dict(publisher.EXPECTED_CONTRACT_ANCHOR_CHECKS)
        checks["metadata_sha256_exact"] = False

        self.assert_contract_publication_rejects_checks(checks)

    def test_contract_publication_rejects_truthy_verification_check(self):
        checks = dict(publisher.EXPECTED_CONTRACT_ANCHOR_CHECKS)
        checks["metadata_sha256_exact"] = 1

        self.assert_contract_publication_rejects_checks(checks)

    def test_contract_publication_put_pins_exact_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            contract = Path(temporary) / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            contract_sha = publisher.sha256(contract)

            with patch.object(
                publisher,
                "aws_json",
                return_value={"VersionId": "contract-version"},
            ) as aws_json:
                publisher.put_create_only(
                    contract,
                    BUCKET,
                    f"runs/subject01/{RUN}/deterministic/contracts/{contract_sha}.json",
                    KMS,
                    "us-east-1",
                    contract_sha,
                )

        self.assertEqual(
            aws_json.call_args.args,
            (
                [
                    "s3api",
                    "put-object",
                    "--bucket",
                    BUCKET,
                    "--key",
                    f"runs/subject01/{RUN}/deterministic/contracts/{contract_sha}.json",
                    "--body",
                    str(contract),
                    "--if-none-match",
                    "*",
                    "--server-side-encryption",
                    "aws:kms",
                    "--sse-kms-key-id",
                    KMS,
                    "--checksum-algorithm",
                    "SHA256",
                    "--checksum-sha256",
                    publisher.checksum_sha256(contract_sha),
                    "--content-type",
                    "application/json",
                    "--metadata",
                    f"sha256={contract_sha}",
                ],
                "us-east-1",
            ),
        )

    def test_contract_publication_binds_dry_run_to_parsed_contract_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            original_bytes = contract.read_bytes()
            original_sha = publisher.sha256(contract)
            anchor = root / "anchor.dry.json"
            real_load = publisher.load_contract_with_sha256
            mutated_sha = ""

            def mutate_after_contract_parse(path):
                nonlocal mutated_sha
                value, digest, payload = real_load(path)
                if not mutated_sha:
                    mutated = dict(value)
                    mutated["run_alias"] = "subject99"
                    write_json(contract, mutated)
                    mutated_sha = publisher.sha256(contract)
                return value, digest, payload

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
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    publisher,
                    "load_contract_with_sha256",
                    side_effect=mutate_after_contract_parse,
                ),
                patch.object(publisher, "aws_json", return_value={"Status": "Enabled"}),
                patch.object(publisher, "version_history", return_value=[]),
            ):
                self.assertEqual(publisher.main(), 0)

            receipt = json.loads(anchor.read_text(encoding="utf-8"))
            self.assertEqual(receipt["receipt_sha256"], original_sha)
            self.assertEqual(receipt["receipt_bytes"], len(original_bytes))
            self.assertNotEqual(receipt["receipt_sha256"], mutated_sha)

    def test_contract_publication_rejects_loaded_contract_that_changes_during_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            original_sha256 = publisher.sha256
            mutated = False

            def mutate_before_stability_hash(path: Path) -> str:
                nonlocal mutated
                if path == contract and not mutated:
                    mutated = True
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    payload["run_alias"] = "subject99"
                    write_json(path, payload)
                return original_sha256(path)

            with (
                patch.object(
                    publisher,
                    "sha256",
                    side_effect=mutate_before_stability_hash,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "contract changed during read",
                ),
            ):
                publisher.load_contract_with_sha256(contract)

    def test_contract_publication_uploads_stable_parsed_contract_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            original_bytes = contract.read_bytes()
            original_sha = publisher.sha256(contract)
            version = "contract-version"
            prefix = f"runs/subject01/{RUN}/deterministic/contracts/"
            key = f"{prefix}{original_sha}.json"
            checksum = base64.b64encode(bytes.fromhex(original_sha)).decode("ascii")
            anchor = root / "anchor.json"
            dry_run = self.write_contract_dry_run_receipt(
                root / "anchor.dry.json", contract, prefix=prefix
            )
            metadata = {
                "VersionId": version,
                "ContentLength": len(original_bytes),
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": checksum,
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": KMS,
                "Metadata": {"sha256": original_sha},
            }
            history = [
                {
                    "history_kind": "version",
                    "Key": key,
                    "VersionId": version,
                    "IsLatest": True,
                    "Size": len(original_bytes),
                }
            ]
            real_load = publisher.load_contract_with_sha256
            uploaded = {}

            def mutate_after_contract_parse(path):
                value, digest, payload = real_load(path)
                mutated = dict(value)
                mutated["run_alias"] = "subject99"
                write_json(contract, mutated)
                return value, digest, payload

            def fake_put(path, bucket, object_key, kms_key_arn, region, contract_sha):
                self.assertNotEqual(path, contract)
                self.assertEqual(path.read_bytes(), original_bytes)
                self.assertEqual(contract_sha, original_sha)
                self.assertEqual(object_key, key)
                uploaded["sha256"] = publisher.sha256(path)
                return {"VersionId": version}

            def fake_get(bucket, object_key, version_id, destination, region):
                destination.write_bytes(original_bytes)
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
                str(anchor),
                "--dry-run-receipt",
                str(dry_run),
                "--apply",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    publisher,
                    "load_contract_with_sha256",
                    side_effect=mutate_after_contract_parse,
                ),
                patch.object(publisher, "aws_json", return_value={"Status": "Enabled"}),
                patch.object(publisher, "version_history", side_effect=[[], history]),
                patch.object(publisher, "put_create_only", side_effect=fake_put),
                patch.object(publisher, "head", return_value=metadata),
                patch.object(publisher, "get_exact", side_effect=fake_get),
            ):
                self.assertEqual(publisher.main(), 0)

            receipt = json.loads(anchor.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "passed")
            self.assertEqual(receipt["receipt_sha256"], original_sha)
            self.assertEqual(uploaded["sha256"], original_sha)

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
            dry_run = self.write_contract_dry_run_receipt(
                root / "anchor.dry.json", contract, prefix=prefix
            )
            history = [
                {
                    "history_kind": "version",
                    "Key": key,
                    "VersionId": version,
                    "IsLatest": True,
                    "Size": contract.stat().st_size,
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
                "--dry-run-receipt",
                str(dry_run),
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

    def test_contract_publication_rejects_duplicate_existing_anchor_json_before_recovery(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            anchor_path = root / "anchor.json"
            contract_sha = publisher.sha256(contract)
            prefix = f"runs/subject01/{RUN}/deterministic/contracts/"
            key = f"{prefix}{contract_sha}.json"
            publisher.reserve_json(
                anchor_path,
                {
                    "schema_version": 1,
                    "status": "in_progress",
                    "receipt_sha256": contract_sha,
                    "receipt_bytes": contract.stat().st_size,
                    "receipt_uri": f"s3://{BUCKET}/{key}",
                    "receipt_version_id": "",
                    "bucket_versioning": "Enabled",
                    "initial_version_history_count": 0,
                    "publication_strategy": "sha256_content_addressed_create_only",
                    "kms_key_arn": KMS,
                    "checks": {},
                },
            )
            write_duplicate_json_field(anchor_path, "status", "failed")
            dry_run = self.write_contract_dry_run_receipt(
                root / "anchor.dry.json", contract, prefix=prefix
            )
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
                "--dry-run-receipt",
                str(dry_run),
                "--apply",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(publisher, "aws_json", return_value={"Status": "Enabled"}),
                patch.object(
                    publisher,
                    "put_create_only",
                    side_effect=AssertionError("put called"),
                ),
                self.assertRaisesRegex(
                    SystemExit,
                    (
                        "duplicate JSON object name in "
                        "existing contract publication anchor: status"
                    ),
                ),
            ):
                publisher.main()

    def test_contract_publication_rejects_coerced_recovery_version_without_second_put(self):
        cases = (True, "null", "none", "has whitespace")
        for version_id in cases:
            with self.subTest(version_id=version_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                contract = root / "contract.json"
                write_json(contract, CustodyFixture().finalize())
                anchor_path = root / "anchor.json"
                contract_sha = publisher.sha256(contract)
                prefix = f"runs/subject01/{RUN}/deterministic/contracts/"
                key = f"{prefix}{contract_sha}.json"
                uri = f"s3://{BUCKET}/{key}"
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
                dry_run = self.write_contract_dry_run_receipt(
                    root / "anchor.dry.json", contract, prefix=prefix
                )
                history = [
                    {
                        "history_kind": "version",
                        "Key": key,
                        "VersionId": version_id,
                        "IsLatest": True,
                        "Size": contract.stat().st_size,
                    }
                ]
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
                    "--dry-run-receipt",
                    str(dry_run),
                    "--apply",
                ]

                with (
                    patch.object(sys, "argv", argv),
                    patch.object(
                        publisher,
                        "aws_json",
                        return_value={"Status": "Enabled"},
                    ),
                    patch.object(
                        publisher,
                        "version_history",
                        side_effect=[history, history],
                    ),
                    patch.object(publisher, "put_create_only") as put,
                    patch.object(
                        publisher,
                        "verify_publication",
                        side_effect=AssertionError("verification reached"),
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "recovery history omitted an exact VersionId",
                    ),
                ):
                    publisher.main()

                put.assert_not_called()
                value = json.loads(anchor_path.read_text(encoding="utf-8"))
                self.assertEqual(value["status"], "failed")
                self.assertEqual(value["receipt_version_id"], "")

    def test_contract_publication_rejects_symlinked_exact_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            contract_sha = publisher.sha256(contract)
            version = "contract-version"
            prefix = f"runs/subject01/{RUN}/deterministic/contracts/"
            key = f"{prefix}{contract_sha}.json"
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
            history = [
                {
                    "history_kind": "version",
                    "Key": key,
                    "VersionId": version,
                    "IsLatest": True,
                    "Size": contract.stat().st_size,
                }
            ]

            def fake_get(bucket, object_key, version_id, destination, region):
                real_contract = destination.with_name("real-contract.json")
                real_contract.write_bytes(contract.read_bytes())
                destination.symlink_to(real_contract)
                return dict(metadata)

            anchor_path = root / "anchor.json"
            dry_run = self.write_contract_dry_run_receipt(
                root / "anchor.dry.json", contract, prefix=prefix
            )
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
                "--dry-run-receipt",
                str(dry_run),
                "--apply",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(publisher, "aws_json", return_value={"Status": "Enabled"}),
                patch.object(publisher, "version_history", side_effect=[[], history]),
                patch.object(
                    publisher,
                    "put_create_only",
                    return_value={"VersionId": version},
                ),
                patch.object(publisher, "head", return_value=metadata),
                patch.object(publisher, "get_exact", side_effect=fake_get),
                self.assertRaisesRegex(
                    ValueError,
                    "downloaded input contract must be a real file",
                ),
            ):
                publisher.main()

            value = json.loads(anchor_path.read_text(encoding="utf-8"))
            self.assertEqual(value["status"], "failed")
            self.assertIn("downloaded input contract", value["error"])

    def test_contract_publication_reservation_fsyncs_parent_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            anchor_path = Path(temporary) / "anchor.json"

            with mock.patch.object(
                publisher,
                "fsync_directory",
                wraps=publisher.fsync_directory,
            ) as fsync_directory:
                publisher.reserve_json(anchor_path, {"status": "dry_run"})

            fsync_directory.assert_called_once_with(anchor_path.parent)

    def test_contract_publication_removes_reservation_after_parent_fsync_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor_path = root / "anchor.json"

            with (
                mock.patch.object(
                    publisher,
                    "fsync_directory",
                    side_effect=OSError("synthetic parent fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic parent fsync failure"),
            ):
                publisher.reserve_json(anchor_path, {"status": "dry_run"})

            self.assertFalse(anchor_path.exists())

    def test_contract_publication_reservation_rehashes_after_parent_fsync(self):
        with tempfile.TemporaryDirectory() as temporary:
            anchor_path = Path(temporary) / "anchor.json"
            real_fsync_directory = publisher.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                anchor_path.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    publisher,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "contract publication anchor changed during write",
                ),
            ):
                publisher.reserve_json(anchor_path, {"status": "dry_run"})

            self.assertFalse(anchor_path.exists())

    def test_contract_publication_anchor_update_rehashes_after_parent_fsync(self):
        with tempfile.TemporaryDirectory() as temporary:
            anchor_path = Path(temporary) / "anchor.json"
            real_fsync_directory = publisher.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                anchor_path.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    publisher,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "contract publication anchor changed during write",
                ),
            ):
                publisher.write_json_atomic(anchor_path, {"status": "passed"})

    def test_contract_publication_sha256_rejects_symlinked_hash_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_input = root / "real-anchor.json"
            linked_input = root / "anchor-link.json"
            real_input.write_text("{}\n", encoding="utf-8")
            linked_input.symlink_to(real_input)

            real_parent = root / "real-inputs"
            real_parent.mkdir()
            (real_parent / "anchor.json").write_text("{}\n", encoding="utf-8")
            linked_parent = root / "linked-inputs"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            cases = (
                (
                    linked_input,
                    "anchor-link.json SHA-256 input must be a real file",
                ),
                (
                    linked_parent / "anchor.json",
                    "anchor.json SHA-256 input parent may not be a symlink",
                ),
            )
            for path, message in cases:
                with self.subTest(path=path):
                    with self.assertRaisesRegex(ValueError, message):
                        publisher.sha256(path)

    def test_contract_publication_sha256_rejects_hash_input_that_changes_during_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            anchor = root / "anchor.json"
            anchor.write_text('{"stable": true}\n', encoding="utf-8")
            original_sha256_file_once = publisher.sha256_file_once
            mutated = False

            def mutate_after_first_hash(path: Path) -> str:
                nonlocal mutated
                digest = original_sha256_file_once(path)
                if path == anchor and not mutated:
                    mutated = True
                    path.write_text('{"stable": false}\n', encoding="utf-8")
                return digest

            with (
                patch.object(
                    publisher,
                    "sha256_file_once",
                    side_effect=mutate_after_first_hash,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "anchor.json SHA-256 input changed during read",
                ),
            ):
                publisher.sha256(anchor)

    def test_contract_publication_rejects_symlinked_anchor_parent_without_writing_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-anchors"
            real_parent.mkdir()
            linked_parent = root / "linked-anchors"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                publisher.reserve_json(
                    linked_parent / "anchor.json",
                    {"status": "dry_run"},
                )

            self.assertFalse((real_parent / "anchor.json").exists())

    def test_contract_publication_rejects_nested_symlinked_anchor_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-anchors"
            real_parent.mkdir()
            linked_parent = root / "linked-anchors"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                publisher.reserve_json(
                    linked_parent / "missing" / "anchor.json",
                    {"status": "dry_run"},
                )

            self.assertFalse((real_parent / "missing" / "anchor.json").exists())

    def test_contract_publication_rejects_existing_dir_below_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-anchors"
            real_parent.mkdir()
            (real_parent / "existing").mkdir()
            linked_parent = root / "linked-anchors"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                publisher.reserve_json(
                    linked_parent / "existing" / "anchor.json",
                    {"status": "dry_run"},
                )

            self.assertFalse((real_parent / "existing" / "anchor.json").exists())

    def test_contract_publication_rejects_symlinked_anchor_parent_before_aws(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            real_parent = root / "real-anchors"
            real_parent.mkdir()
            linked_parent = root / "linked-anchors"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            argv = [
                "publish_input_contract.py",
                "--contract",
                str(contract),
                "--destination-prefix",
                f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/contracts/",
                "--kms-key-arn",
                KMS,
                "--anchor-output",
                str(linked_parent / "anchor.json"),
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    publisher,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
                self.assertRaisesRegex(SystemExit, "parent may not be a symlink"),
            ):
                publisher.main()

            self.assertFalse((real_parent / "anchor.json").exists())

    def test_contract_publication_rejects_symlinked_contract_before_aws(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            contract = root / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            linked_contract = root / "linked-contract.json"
            linked_contract.symlink_to(contract)
            anchor = root / "anchor.json"
            argv = [
                "publish_input_contract.py",
                "--contract",
                str(linked_contract),
                "--destination-prefix",
                f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/contracts/",
                "--kms-key-arn",
                KMS,
                "--anchor-output",
                str(anchor),
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    publisher,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
                self.assertRaisesRegex(SystemExit, "contract must be a real JSON file"),
            ):
                publisher.main()

            self.assertFalse(anchor.exists())

    def test_finalizer_schema_version_checks_use_exact_integer_helper(self):
        cases = (
            (1, 1, True),
            (1.0, 1, False),
            ("1", 1, False),
            (2, 1, False),
            (None, 1, False),
            (True, 1, False),
            (False, 0, False),
        )
        for value, expected, accepted in cases:
            with self.subTest(value=value, expected=expected):
                self.assertIs(
                    finalizer.exact_schema_version(
                        {"schema_version": value},
                        expected,
                    ),
                    accepted,
                )

    def test_finalizer_schema_version_checks_avoid_raw_comparisons(self):
        module = ast.parse(
            (ROOT / "scripts/finalize_input_contract.py").read_text(
                encoding="utf-8"
            )
        )
        parent_by_child = {
            child: parent
            for parent in ast.walk(module)
            for child in ast.iter_child_nodes(parent)
        }

        def in_exact_schema_helper(node: ast.AST) -> bool:
            parent = parent_by_child.get(node)
            while parent is not None:
                if isinstance(parent, ast.FunctionDef):
                    return parent.name == "exact_schema_version"
                parent = parent_by_child.get(parent)
            return False

        raw_schema_version_comparisons = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Compare)
            and "schema_version" in ast.unparse(node)
            and not in_exact_schema_helper(node)
        ]

        self.assertEqual(raw_schema_version_comparisons, [])

    def test_contract_publication_rejects_contract_below_symlinked_parent_before_aws(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-contracts"
            real_parent.mkdir()
            contract = real_parent / "contract.json"
            write_json(contract, CustodyFixture().finalize())
            linked_parent = root / "linked-contracts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            anchor = root / "anchor.json"
            argv = [
                "publish_input_contract.py",
                "--contract",
                str(linked_parent / "contract.json"),
                "--destination-prefix",
                f"s3://{BUCKET}/runs/subject01/{RUN}/deterministic/contracts/",
                "--kms-key-arn",
                KMS,
                "--anchor-output",
                str(anchor),
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    publisher,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
                self.assertRaisesRegex(SystemExit, "parent may not be a symlink"),
            ):
                publisher.main()

            self.assertFalse(anchor.exists())

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
        cases = (
            {"NextKeyMarker": "prefix/contract.json"},
            {"NextKeyMarker": True, "NextVersionIdMarker": "v1"},
            {"NextKeyMarker": "prefix/contract.json", "NextVersionIdMarker": True},
        )
        for case in cases:
            with self.subTest(case=case):
                malformed = {
                    "IsTruncated": True,
                    "Versions": [],
                    "DeleteMarkers": [],
                    **case,
                }
                with patch.object(publisher, "aws_json", return_value=malformed):
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
