#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import submit_materializer_v4 as MODULE  # noqa: E402


def write_duplicate_json_field(path: Path, key: str, stale_value: object) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(payload, indent=2, sort_keys=True)
    if key not in payload:
        raise AssertionError(f"missing top-level JSON field {key}")
    current = f'  "{key}": '
    if text.count(current) != 1:
        raise AssertionError(f"expected exactly one top-level JSON field {key}")
    duplicate = f'  "{key}": {json.dumps(stale_value, sort_keys=True)},\n{current}'
    path.write_text(text.replace(current, duplicate, 1) + "\n", encoding="utf-8")


class SubmitMaterializerV4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run_id = "diana-wgs-hrd-20260716T033101Z"
        self.job_id = "6f827d44-d19b-4a6c-9126-d65189aa66cf"
        self.kms = "arn:aws:kms:us-east-1:172630973301:key/45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
        self.private_bucket = "diana-omics-private-results-172630973301-us-east-1"
        self.final_prefix = f"runs/subject01/{self.run_id}/deterministic/final/"
        self.final_freeze = self.root / "final-freeze.json"
        self.final_anchor = self.root / "final-freeze-anchor.json"
        self.exact_materialization = self.root / "exact-materialization.json"
        self.reference_freeze = self.root / "reference-freeze-receipt.json"
        self.reference_sha = self.root / "reference-sha256.json"
        self.script_anchor = self.root / "materializer-script-freeze-anchor.json"
        self.registration = self.root / "materializer-registration-receipt.v4.json"
        self.job_definition = self.root / "materializer-job-definition.v4.json"
        self.request_output = self.root / "request.json"
        self.response_output = self.root / "response.json"
        self._write_final_receipts()
        self._write_reference_receipts()
        self._write_registration_receipts()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_final_receipts(self) -> None:
        rows = []
        materialized_rows = []
        for index, relative in enumerate(MODULE.SOURCE_RELATIVES.values(), start=1):
            key = self.final_prefix + relative
            version = f"exact-version-{index}"
            checksum = f"exact-checksum-{index}"
            sha = f"{index}" * 64
            destination = {
                "bucket": self.private_bucket,
                "key": key,
                "version_id": version,
                "bytes": 100 + index,
                "etag": f'"etag-{index}"',
                "checksums": {"ChecksumCRC64NVME": checksum},
                "checksum_type": "FULL_OBJECT",
                "server_side_encryption": "aws:kms",
                "kms_key_id": self.kms,
            }
            rows.append(
                {
                    "relative_key": relative,
                    "source": {
                        "bucket": "work",
                        "key": relative,
                        "version_id": f"source-{index}",
                        "bytes": 100 + index,
                        "etag": f'"source-{index}"',
                        "checksums": {"ChecksumCRC64NVME": checksum},
                        "checksum_type": "FULL_OBJECT",
                    },
                    "destination": destination,
                    "status": "passed",
                    "checks": {
                        "listed_inventory_stable": True,
                        "source_stable": True,
                        "size_matches": True,
                        "common_checksum_matches": True,
                        "exact_kms_matches": True,
                        "destination_versioned": True,
                        "copy_response_version_matches": True,
                    },
                }
            )
            materialized_rows.append(
                {
                    "relative_key": relative,
                    "bucket": self.private_bucket,
                    "key": key,
                    "version_id": version,
                    "bytes": 100 + index,
                    "checksums": {"ChecksumCRC64NVME": checksum},
                    "checksum_type": "FULL_OBJECT",
                    "server_side_encryption": "aws:kms",
                    "kms_key_id": self.kms,
                    "sha256": sha,
                    "checks": {
                        "version_id": True,
                        "content_length": True,
                        "local_bytes": True,
                        "checksums": True,
                        "checksum_type": True,
                        "sse": True,
                        "kms": True,
                    },
                }
            )
        freeze = {
            "schema_version": 1,
            "status": "passed",
            "run_id": self.run_id,
            "batch_job_id": self.job_id,
            "batch_status": "SUCCEEDED",
            "destination_prefix": f"s3://{self.private_bucket}/{self.final_prefix}",
            "kms_key_arn": self.kms,
            "destination_bucket_versioning": "Enabled",
            "destination_initial_version_history_count": 0,
            "receipt_anchor_strategy": "sha256_content_addressed_create_only",
            "object_count": len(rows),
            "passed_count": len(rows),
            "initial_inventory_identity": [
                {
                    "relative_key": row["relative_key"],
                    "key": row["source"]["key"],
                    "bytes": row["source"]["bytes"],
                    "etag": row["source"]["etag"],
                    "version_id": row["source"]["version_id"],
                }
                for row in rows
            ],
            "final_inventory_identity": [
                {
                    "relative_key": row["relative_key"],
                    "key": row["source"]["key"],
                    "bytes": row["source"]["bytes"],
                    "etag": row["source"]["etag"],
                    "version_id": row["source"]["version_id"],
                }
                for row in rows
            ],
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
                for row in rows
            ],
            "objects": rows,
            "checks": {
                "execution_receipt_bound": True,
                "complete_source_inventory_unchanged": True,
                "destination_exact_history_and_receipt_match": True,
            },
        }
        self._write(self.final_freeze, freeze)
        freeze_sha = MODULE.sha256_path(self.final_freeze)
        anchor = {
            "schema_version": 1,
            "status": "passed",
            "run_id": self.run_id,
            "batch_job_id": self.job_id,
            "receipt_sha256": freeze_sha,
            "receipt_bytes": self.final_freeze.stat().st_size,
            "receipt_uri": (
                f"s3://{self.private_bucket}/runs/subject01/{self.run_id}/"
                "deterministic/provenance/final-artifact-freeze-receipts/"
                f"{freeze_sha}.json"
            ),
            "receipt_version_id": "freeze-receipt-version",
            "checks": {name: True for name in MODULE.EXPECTED_ANCHOR_CHECKS},
        }
        self._write(self.final_anchor, anchor)
        self._write(
            self.exact_materialization,
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": self.run_id,
                "batch_job_id": self.job_id,
                "freeze_receipt_sha256": freeze_sha,
                "expected_kms_key_arn": self.kms,
                "object_count": len(materialized_rows),
                "passed_count": len(materialized_rows),
                "objects": materialized_rows,
            },
        )

    def _write_reference_receipts(self) -> None:
        artifacts = {
            "reference.fa": ("a" * 64, "reference-fasta-version", "crc-fasta"),
            "reference.fa.fai": ("b" * 64, "reference-fai-version", "crc-fai"),
            "reference.dict": ("c" * 64, "reference-dict-version", "crc-dict"),
        }
        objects = []
        sha_rows = []
        for index, (artifact, (digest, version_id, crc64nvme)) in enumerate(
            artifacts.items(), start=1
        ):
            destination = {
                "uri": (
                    f"s3://{self.private_bucket}/runs/subject01/{self.run_id}/"
                    f"deterministic/reference/{artifact}"
                ),
                "version_id": version_id,
                "bytes": 200 + index,
                "crc64nvme": crc64nvme,
                "kms_key_id": self.kms,
            }
            objects.append(
                {
                    "status": "passed",
                    "destination": destination,
                    "checks": {
                        name: True for name in MODULE.EXPECTED_REFERENCE_ROW_CHECKS
                    },
                }
            )
            sha_rows.append(
                {
                    "artifact": artifact,
                    "status": "passed",
                    "version_id": version_id,
                    "bytes": destination["bytes"],
                    "crc64nvme": crc64nvme,
                    "server_side_encryption": "aws:kms",
                    "kms_key_id": self.kms,
                    "sha256": digest,
                }
            )

        freeze = {
            "schema_version": 1,
            "status": "passed",
            "object_count": len(objects),
            "objects": objects,
        }
        self._write(self.reference_freeze, freeze)
        self._write(
            self.reference_sha,
            {
                "schema_version": 1,
                "status": "passed",
                "object_count": len(sha_rows),
                "freeze_receipt_sha256": MODULE.sha256_path(
                    self.reference_freeze
                ),
                "algorithm": "sha256_full_object_aws_side_stream",
                "execution": {
                    "hash_computation_status": "passed",
                    "batch_terminal_status": (
                        "FAILED_AFTER_ALL_HASHES_DURING_RECEIPT_UPLOAD"
                    ),
                    "image": MODULE.EXPECTED_IMAGE,
                    "job_definition": (
                        f"arn:aws:batch:{MODULE.REGION}:{MODULE.ACCOUNT_ID}:"
                        "job-definition/diana-hrd-private-sha256-202607:2"
                    ),
                    "cloudwatch_log_group": "/aws/batch/job",
                    "cloudwatch_events_sha256": "d" * 64,
                },
                "receipt_delivery": (
                    "recovered_locally_from_complete_immutable_cloudwatch_hash_log"
                ),
                "script_sha256": "e" * 64,
                "objects": sha_rows,
            },
        )

    def _write_registration_receipts(self) -> None:
        script_bucket = self.private_bucket
        script_key = (
            f"runs/subject01/{self.run_id}/preparation/scripts/"
            "materialize_crosscheck_inputs-"
            f"{MODULE.EXPECTED_MATERIALIZER_SHA256}.py"
        )
        script_source = {
            "logical_path": "scripts/materialize_crosscheck_inputs.py",
            "sha256": MODULE.EXPECTED_MATERIALIZER_SHA256,
            "bytes": 32598,
        }
        script_object = {
            "uri": f"s3://{script_bucket}/{script_key}",
            "bucket": script_bucket,
            "key": script_key,
            "version_id": "script-version",
            "server_side_encryption": "aws:kms",
            "ssekms_key_id": self.kms,
        }
        script_checks = {
            name: True for name in MODULE.EXPECTED_SCRIPT_ANCHOR_CHECKS
        }
        self._write(
            self.script_anchor,
            {
                "schema_version": 1,
                "status": "passed",
                "source": script_source,
                "object": script_object,
                "checks": script_checks,
            },
        )

        source_uris = {
            name: (
                f"s3://{self.private_bucket}/{self.final_prefix}{relative}"
            )
            for name, relative in MODULE.SOURCE_RELATIVES.items()
        }
        shell = (
            "set -euo pipefail; "
            "actual=$(sha256sum /work/materialize/materialize_crosscheck_inputs.py | awk '{print $1}'); "
            f"test \"$actual\" = {MODULE.EXPECTED_MATERIALIZER_SHA256}; "
            "python3 -u /work/materialize/materialize_crosscheck_inputs.py "
            f"--bucket {script_bucket} "
            f"--key {script_key} "
            f"--source-vcf-uri {source_uris['source_vcf']} "
            f"--source-vcf-index-uri {source_uris['source_vcf_index']} "
            f"--source-matrix-uri {source_uris['source_matrix']} "
            f"--reference-fasta-uri s3://{self.private_bucket}/runs/subject01/{self.run_id}/deterministic/reference/reference.fa "
            f"--reference-fai-uri s3://{self.private_bucket}/runs/subject01/{self.run_id}/deterministic/reference/reference.fa.fai "
            "--source-vcf-version-id \"$1\" "
            "--source-vcf-index-version-id \"$2\" "
            "--source-matrix-version-id \"$3\" "
            "--source-vcf-sha256 \"$4\" "
            "--source-vcf-index-sha256 \"$5\" "
            "--source-matrix-sha256 \"$6\" "
            "--reference-fasta-version-id \"$7\" "
            "--reference-fai-version-id \"$8\" "
            f"--reference-fasta-sha256 {'a' * 64} "
            f"--reference-fai-sha256 {'b' * 64} "
            f"--destination-prefix s3://{self.private_bucket}/runs/subject01/{self.run_id}/deterministic/final "
            f"--receipt-prefix s3://{self.private_bucket}/runs/subject01/{self.run_id}/deterministic/provenance/crosscheck-materialization-receipts "
            f"--kms-key-arn {self.kms} "
            f"--version-id {script_object['version_id']} "
            "--region us-east-1"
        )
        command = [
            "bash",
            "-lc",
            shell,
            "materializer",
            *[f"Ref::{name}" for name in MODULE.PARAMETER_NAMES],
        ]
        definition = {
            "jobDefinitionName": MODULE.JOB_DEFINITION_NAME,
            "type": "container",
            "platformCapabilities": ["EC2"],
            "containerProperties": {
                "image": MODULE.EXPECTED_IMAGE,
                "jobRoleArn": MODULE.EXPECTED_JOB_ROLE_ARN,
                "vcpus": 8,
                "memory": 32000,
                "command": command,
                "environment": [{"name": "AWS_REGION", "value": MODULE.REGION}],
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": "/aws/batch/job",
                        "awslogs-region": MODULE.REGION,
                        "awslogs-stream-prefix": "diana-wgs-hrd-materialize",
                    },
                },
            },
            "retryStrategy": {"attempts": 1},
            "timeout": {"attemptDurationSeconds": 21600},
        }
        self._write(self.job_definition, definition)
        expected_binding = {
            f"${index}": name
            for index, name in enumerate(MODULE.PARAMETER_NAMES, start=1)
        }
        self._write(
            self.registration,
            {
                "schema_version": 3,
                "status": "registered_not_submitted",
                "classification_authorization": "none",
                "authorized_hrd_state": "no_call",
                "script_freeze": {
                    "anchor_sha256": MODULE.sha256_path(self.script_anchor),
                    "object": script_object,
                    "source": script_source,
                    "checks": script_checks,
                },
                "batch": {
                    "definition_sha256": MODULE.sha256_path(
                        self.job_definition
                    ),
                    "registration": {
                        "jobDefinitionArn": MODULE.JOB_DEFINITION_ARN,
                        "revision": 4,
                    },
                    "job_definition_arn": MODULE.JOB_DEFINITION_ARN,
                    "revision": 4,
                    "retry_attempts": 1,
                    "timeout_seconds": 21600,
                    "vcpus": 8,
                    "memory_mib": 32000,
                    "image": MODULE.EXPECTED_IMAGE,
                    "parameter_substitution": list(MODULE.PARAMETER_NAMES),
                    "shell_argument_binding": expected_binding,
                },
                "checks": {
                    name: True for name in MODULE.EXPECTED_REGISTRATION_CHECKS
                },
            },
        )

    def args(self, *, submit: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            run_id=self.run_id,
            final_freeze_receipt=self.final_freeze,
            final_freeze_anchor=self.final_anchor,
            exact_materialization_receipt=self.exact_materialization,
            reference_freeze_receipt=self.reference_freeze,
            reference_sha256_receipt=self.reference_sha,
            reference_freeze_anchor=None,
            materializer_script_anchor=self.script_anchor,
            registration_receipt=self.registration,
            job_definition_payload=self.job_definition,
            request_output=self.request_output,
            response_output=self.response_output if submit else None,
            dry_run_receipt=None,
            region=MODULE.REGION,
            submit=submit,
        )

    def preflight_receipt(
        self,
        job_name: str = "diana-wgs-hrd-materialize-20260716T033101Z",
    ) -> dict:
        return {
            "schema_version": 1,
            "status": "submission_authorized",
            "generated_at_utc": "2026-07-17T01:02:03Z",
            "scope": "private one-shot materializer-v4 submission preflight",
            "run_id": self.run_id,
            "classification_authorization": "none",
            "authorized_hrd_state": "no_call",
            "input_receipts": {
                "final_freeze": {"path": str(self.final_freeze), "sha256": "a" * 64},
                "registration_v4": {"path": str(self.registration), "sha256": "b" * 64},
            },
            "custody": {"final": {}, "reference": {}},
            "live_preflight": {
                "identity": {},
                "job_definition": {},
                "image": {},
                "queue": {},
                "job_name_uniqueness": {},
                "destination_history": {},
                "receipt_history": {},
            },
            "submit_job_request": {
                "jobName": job_name,
                "jobQueue": MODULE.QUEUE_NAME,
                "jobDefinition": MODULE.JOB_DEFINITION_ARN,
                "parameters": {name: "value" for name in MODULE.PARAMETER_NAMES},
                "retryStrategy": {"attempts": 1},
            },
            "checks": {
                "receipt_hashes_cross_bound": True,
                "three_exact_source_versions_and_local_sha256": True,
                "two_exact_reference_versions_and_aws_sha256": True,
                "exact_active_revision_4": True,
                "immutable_arm64_image": True,
                "exact_live_arm_queue": True,
                "one_attempt": True,
                "zero_existing_exact_job_name": True,
                "empty_destination_history": True,
                "empty_receipt_history": True,
                "default_dry_run_behavior_preserved": True,
                "submission_guard_satisfied": True,
            },
        }

    def write_dry_run_receipt(self, receipt: dict) -> Path:
        dry_run = copy.deepcopy(receipt)
        dry_run["status"] = "rendered_only"
        dry_run["generated_at_utc"] = "2026-07-17T01:01:01Z"
        output = self.root / "request.dry.json"
        output.write_text(json.dumps(dry_run, indent=2, sort_keys=True) + "\n")
        return output

    def argv(
        self,
        *,
        submit: bool = False,
        dry_run_receipt: Path | None = None,
        bind_dry_run: bool = True,
    ) -> list[str]:
        values = [
            "submit_materializer_v4.py",
            "--run-id",
            self.run_id,
            "--final-freeze-receipt",
            str(self.final_freeze),
            "--final-freeze-anchor",
            str(self.final_anchor),
            "--exact-materialization-receipt",
            str(self.exact_materialization),
            "--reference-freeze-receipt",
            str(self.reference_freeze),
            "--reference-sha256-receipt",
            str(self.reference_sha),
            "--materializer-script-anchor",
            str(self.script_anchor),
            "--registration-receipt",
            str(self.registration),
            "--job-definition-payload",
            str(self.job_definition),
            "--request-output",
            str(self.request_output),
        ]
        if submit:
            values.extend(
                [
                    *(
                        [
                            "--dry-run-receipt",
                            str(dry_run_receipt or self.root / "request.dry.json"),
                        ]
                        if bind_dry_run
                        else []
                    ),
                    "--response-output",
                    str(self.response_output),
                    "--submit",
                ]
            )
        return values

    def live_definition(self) -> dict:
        local = json.loads(self.job_definition.read_text(encoding="utf-8"))
        local.update(
            {
                "jobDefinitionArn": MODULE.JOB_DEFINITION_ARN,
                "revision": 4,
                "status": "ACTIVE",
            }
        )
        local["retryStrategy"] = {"attempts": 1, "evaluateOnExit": []}
        return local

    def aws_side_effect(
        self,
        *,
        image_platform: dict | None = None,
        queue_status: str = "VALID",
        existing_job: bool = False,
        history: dict | None = None,
        definition: dict | None = None,
    ):
        image_platform = image_platform or {"architecture": "arm64", "os": "linux"}
        history = {"IsTruncated": False} if history is None else history
        definition = self.live_definition() if definition is None else definition

        def invoke(region: str, *arguments: str) -> dict:
            self.assertEqual(region, MODULE.REGION)
            operation = tuple(arguments[:2])
            if operation == ("sts", "get-caller-identity"):
                return {
                    "Account": MODULE.ACCOUNT_ID,
                    "Arn": f"arn:aws:iam::{MODULE.ACCOUNT_ID}:user/unit",
                    "UserId": "unit",
                }
            if operation == ("batch", "describe-job-definitions"):
                return {"jobDefinitions": [copy.deepcopy(definition)]}
            if operation == ("ecr", "batch-get-image"):
                manifest = {
                    "schemaVersion": 2,
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                    "manifests": [
                        {
                            "digest": "sha256:" + "a" * 64,
                            "mediaType": "application/vnd.oci.image.manifest.v1+json",
                            "platform": image_platform,
                        },
                        {
                            "digest": "sha256:" + "b" * 64,
                            "mediaType": "application/vnd.oci.image.manifest.v1+json",
                            "platform": {"architecture": "unknown", "os": "unknown"},
                            "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
                        },
                    ],
                }
                return {
                    "failures": [],
                    "images": [
                        {
                            "imageId": {"imageDigest": MODULE.EXPECTED_IMAGE_DIGEST},
                            "imageManifestMediaType": "application/vnd.oci.image.index.v1+json",
                            "imageManifest": json.dumps(manifest),
                        }
                    ],
                }
            if operation == ("batch", "describe-compute-environments"):
                return {
                    "computeEnvironments": [
                        {
                            "computeEnvironmentArn": MODULE.COMPUTE_ENVIRONMENT_ARN,
                            "computeEnvironmentName": MODULE.QUEUE_NAME,
                            "state": "ENABLED",
                            "status": "VALID",
                            "computeResources": {
                                "type": "EC2",
                                "instanceTypes": list(MODULE.EXPECTED_INSTANCE_TYPES),
                            },
                        }
                    ]
                }
            if operation == ("batch", "describe-job-queues"):
                queue = {
                    "jobQueueArn": MODULE.QUEUE_ARN,
                    "jobQueueName": MODULE.QUEUE_NAME,
                    "state": "ENABLED",
                    "status": queue_status,
                    "computeEnvironmentOrder": [
                        {
                            "order": 1,
                            "computeEnvironment": MODULE.COMPUTE_ENVIRONMENT_ARN,
                        }
                    ],
                }
                return {"jobQueues": [queue]}
            if operation == ("batch", "list-jobs"):
                jobs = []
                if existing_job and "SUCCEEDED" in arguments:
                    jobs = [
                        {
                            "jobId": "prior",
                            "jobName": "diana-wgs-hrd-materialize-20260716T033101Z",
                            "status": "SUCCEEDED",
                        }
                    ]
                return {"jobSummaryList": jobs}
            if operation == ("s3api", "list-object-versions"):
                return copy.deepcopy(history)
            raise AssertionError(f"unexpected mocked AWS call: {arguments}")

        return invoke

    def run_preflight(self, *, aws=None):
        aws = self.aws_side_effect() if aws is None else aws
        with mock.patch.object(MODULE, "aws_json", side_effect=aws):
            return MODULE.preflight(self.args())

    def test_preflight_extracts_exact_eight_parameters_and_is_dry_run(self) -> None:
        result = self.run_preflight()
        self.assertEqual(result["status"], "rendered_only")
        request = result["submit_job_request"]
        self.assertEqual(request["jobQueue"], MODULE.QUEUE_NAME)
        self.assertEqual(request["jobDefinition"], MODULE.JOB_DEFINITION_ARN)
        self.assertEqual(request["retryStrategy"], {"attempts": 1})
        self.assertEqual(list(request["parameters"]), list(MODULE.PARAMETER_NAMES))
        self.assertEqual(request["parameters"]["source_vcf_sha256"], "1" * 64)
        self.assertEqual(
            request["parameters"]["reference_fasta_version_id"],
            "reference-fasta-version",
        )
        self.assertEqual(
            result["custody"]["reference"]["custody_mode"],
            "exact_existing_freeze_plus_aws_sha_receipts",
        )

    def test_tampered_final_anchor_fails_before_aws(self) -> None:
        anchor = json.loads(self.final_anchor.read_text(encoding="utf-8"))
        anchor["receipt_sha256"] = "0" * 64
        self._write(self.final_anchor, anchor)
        with mock.patch.object(MODULE, "aws_json") as aws:
            with self.assertRaisesRegex(ValueError, "anchor does not bind"):
                MODULE.preflight(self.args())
        aws.assert_not_called()

    def test_tampered_local_sha_or_version_fails_before_aws(self) -> None:
        cases = ("BAD", "A" * 64, int("1" * 64))
        for sha256 in cases:
            with self.subTest(sha256=sha256):
                self._write_final_receipts()
                value = json.loads(self.exact_materialization.read_text(encoding="utf-8"))
                value["objects"][0]["sha256"] = sha256
                self._write(self.exact_materialization, value)

                with mock.patch.object(MODULE, "aws_json") as aws:
                    with self.assertRaisesRegex(ValueError, "does not bind frozen row"):
                        MODULE.preflight(self.args())

                aws.assert_not_called()

    def test_exact_materialization_bytes_must_be_exact_before_aws(self) -> None:
        value = json.loads(self.exact_materialization.read_text(encoding="utf-8"))
        value["objects"][0]["bytes"] = float(value["objects"][0]["bytes"])
        self._write(self.exact_materialization, value)

        with mock.patch.object(MODULE, "aws_json") as aws:
            with self.assertRaisesRegex(ValueError, "does not bind frozen row"):
                MODULE.preflight(self.args())

        aws.assert_not_called()

    def test_final_source_version_ids_must_be_strings_before_aws(self) -> None:
        final_freeze = json.loads(self.final_freeze.read_text(encoding="utf-8"))
        final_freeze["objects"][0]["destination"]["version_id"] = True
        final_freeze["destination_inventory"][0]["version_id"] = True
        self._write(self.final_freeze, final_freeze)

        materialization = json.loads(
            self.exact_materialization.read_text(encoding="utf-8")
        )
        materialization["objects"][0]["version_id"] = True
        self._write(self.exact_materialization, materialization)

        with mock.patch.object(MODULE, "aws_json") as aws:
            with self.assertRaisesRegex(ValueError, "final freeze row is not exact"):
                MODULE.preflight(self.args())

        aws.assert_not_called()

    def test_rejects_final_freeze_below_symlinked_parent_before_aws(self) -> None:
        real_parent = self.root / "real-inputs"
        real_parent.mkdir()
        relocated = real_parent / self.final_freeze.name
        relocated.write_bytes(self.final_freeze.read_bytes())
        linked_parent = self.root / "linked-inputs"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        args = self.args()
        args.final_freeze_receipt = linked_parent / self.final_freeze.name

        with mock.patch.object(MODULE, "aws_json") as aws:
            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.preflight(args)

        aws.assert_not_called()

    def test_rejects_symlinked_local_json_input_before_aws(self) -> None:
        relocated = self.root / "exact-materialization.real.json"
        self.exact_materialization.rename(relocated)
        self.exact_materialization.symlink_to(relocated)

        with mock.patch.object(MODULE, "aws_json") as aws:
            with self.assertRaisesRegex(
                ValueError,
                "exact local materialization receipt must be a real file",
            ):
                MODULE.preflight(self.args())

        aws.assert_not_called()

    def test_rejects_duplicate_custody_receipts_before_aws(self) -> None:
        cases = (
            ("final freeze receipt", self.final_freeze, "schema_version"),
            ("freeze anchor", self.final_anchor, "schema_version"),
            (
                "exact local materialization receipt",
                self.exact_materialization,
                "schema_version",
            ),
            ("reference freeze receipt", self.reference_freeze, "schema_version"),
            ("reference SHA-256 receipt", self.reference_sha, "schema_version"),
            (
                "materializer script freeze anchor",
                self.script_anchor,
                "schema_version",
            ),
            (
                "materializer registration receipt v4",
                self.registration,
                "schema_version",
            ),
            (
                "materializer job definition payload",
                self.job_definition,
                "containerProperties",
            ),
        )
        for label, path, duplicate_key in cases:
            with self.subTest(label=label):
                self._write_final_receipts()
                self._write_reference_receipts()
                self._write_registration_receipts()
                write_duplicate_json_field(path, duplicate_key, 0)

                with (
                    mock.patch.object(MODULE, "aws_json") as aws,
                    self.assertRaisesRegex(
                        ValueError,
                        f"duplicate JSON object name in {label}: {duplicate_key}",
                    ),
                ):
                    MODULE.preflight(self.args())

                aws.assert_not_called()

    def test_reference_sha_receipt_must_cross_bind_freeze_hash(self) -> None:
        tampered = self.root / "reference-sha.json"
        value = json.loads(self.reference_sha.read_text(encoding="utf-8"))
        value["freeze_receipt_sha256"] = "0" * 64
        self._write(tampered, value)
        args = self.args()
        args.reference_sha256_receipt = tampered
        with mock.patch.object(MODULE, "aws_json") as aws:
            with self.assertRaisesRegex(ValueError, "reference SHA-256 receipt"):
                MODULE.preflight(args)
        aws.assert_not_called()

    def test_reference_sha_bytes_must_be_exact_before_aws(self) -> None:
        value = json.loads(self.reference_sha.read_text(encoding="utf-8"))
        value["objects"][0]["bytes"] = float(value["objects"][0]["bytes"])
        self._write(self.reference_sha, value)

        with mock.patch.object(MODULE, "aws_json") as aws:
            with self.assertRaisesRegex(ValueError, "reference SHA-256 row"):
                MODULE.preflight(self.args())

        aws.assert_not_called()

    def test_reference_sha_values_must_be_exact_before_aws(self) -> None:
        cases = (
            (
                "numeric_row_sha",
                lambda receipt: receipt["objects"][0].__setitem__(
                    "sha256",
                    int("1" * 64),
                ),
            ),
            (
                "numeric_cloudwatch_sha",
                lambda receipt: receipt["execution"].__setitem__(
                    "cloudwatch_events_sha256",
                    int("2" * 64),
                ),
            ),
            (
                "numeric_script_sha",
                lambda receipt: receipt.__setitem__(
                    "script_sha256",
                    int("3" * 64),
                ),
            ),
        )

        for name, mutate in cases:
            with self.subTest(name=name):
                self._write_reference_receipts()
                receipt = json.loads(self.reference_sha.read_text(encoding="utf-8"))
                mutate(receipt)
                self._write(self.reference_sha, receipt)

                with mock.patch.object(MODULE, "aws_json") as aws:
                    with self.assertRaisesRegex(ValueError, "reference SHA-256"):
                        MODULE.preflight(self.args())

                aws.assert_not_called()

    def test_reference_version_ids_must_be_strings_before_aws(self) -> None:
        freeze = json.loads(self.reference_freeze.read_text(encoding="utf-8"))
        freeze["objects"][0]["destination"]["version_id"] = True
        self._write(self.reference_freeze, freeze)

        sha_receipt = json.loads(self.reference_sha.read_text(encoding="utf-8"))
        sha_receipt["objects"][0]["version_id"] = True
        self._write(self.reference_sha, sha_receipt)

        with mock.patch.object(MODULE, "aws_json") as aws:
            with self.assertRaisesRegex(
                ValueError,
                "reference freeze destination is incomplete",
            ):
                MODULE.preflight(self.args())

        aws.assert_not_called()

    def test_registration_hash_must_bind_exact_definition(self) -> None:
        altered = self.root / "definition.json"
        value = json.loads(self.job_definition.read_text(encoding="utf-8"))
        value["containerProperties"]["memory"] += 1
        self._write(altered, value)
        args = self.args()
        args.job_definition_payload = altered
        with mock.patch.object(MODULE, "aws_json") as aws:
            with self.assertRaisesRegex(ValueError, "registration receipt/definition"):
                MODULE.preflight(args)
        aws.assert_not_called()

    def test_preflight_rejects_non_integer_schema_versions_before_aws(self) -> None:
        cases = (
            (
                "final freeze anchor",
                self.final_anchor,
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "freeze anchor does not bind",
            ),
            (
                "final freeze receipt",
                self.final_freeze,
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "final freeze receipt is incomplete",
            ),
            (
                "exact materialization",
                self.exact_materialization,
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "exact local materialization is incomplete",
            ),
            (
                "reference freeze",
                self.reference_freeze,
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "reference freeze schema/status is not passed",
            ),
            (
                "reference SHA-256 receipt",
                self.reference_sha,
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "reference SHA-256 receipt is incomplete",
            ),
            (
                "materializer script anchor",
                self.script_anchor,
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "materializer registration receipt/definition is not exact",
            ),
            (
                "registration receipt",
                self.registration,
                lambda payload: payload.__setitem__("schema_version", 3.0),
                "materializer registration receipt/definition is not exact",
            ),
        )

        for label, path, mutate, message in cases:
            with self.subTest(label=label):
                value = json.loads(path.read_text(encoding="utf-8"))
                mutate(value)
                self._write(path, value)

                with mock.patch.object(MODULE, "aws_json") as aws:
                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.preflight(self.args())

                aws.assert_not_called()
                self._write_final_receipts()
                self._write_reference_receipts()
                self._write_registration_receipts()

    def test_registration_command_check_map_must_be_exact(self) -> None:
        cases = (
            (
                {*MODULE.EXPECTED_BASE_COMMAND_CHECKS, "future_command_check"},
                "missing future_command_check",
            ),
            (
                {
                    name
                    for name in MODULE.EXPECTED_BASE_COMMAND_CHECKS
                    if name != "script_sha"
                },
                "unexpected script_sha",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(MODULE, "EXPECTED_BASE_COMMAND_CHECKS", expected),
                mock.patch.object(MODULE, "aws_json") as aws,
                self.assertRaisesRegex(ValueError, error),
            ):
                MODULE.preflight(self.args())
            aws.assert_not_called()

    def test_registration_shell_value_map_must_be_exact(self) -> None:
        cases = (
            (
                {*MODULE.EXPECTED_SHELL_VALUES, "future_shell_value"},
                "missing future_shell_value",
            ),
            (
                {
                    name
                    for name in MODULE.EXPECTED_SHELL_VALUES
                    if name != "kms_key_arn"
                },
                "unexpected kms_key_arn",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(MODULE, "EXPECTED_SHELL_VALUES", expected),
                mock.patch.object(MODULE, "aws_json") as aws,
                self.assertRaisesRegex(ValueError, error),
            ):
                MODULE.preflight(self.args())
            aws.assert_not_called()

    def test_registration_definition_check_map_must_be_exact(self) -> None:
        cases = (
            (
                {
                    *MODULE.EXPECTED_REGISTRATION_DEFINITION_CHECKS,
                    "future_definition_check",
                },
                "missing future_definition_check",
            ),
            (
                {
                    name
                    for name in MODULE.EXPECTED_REGISTRATION_DEFINITION_CHECKS
                    if name != "normalized_definition"
                },
                "unexpected normalized_definition",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(
                    MODULE,
                    "EXPECTED_REGISTRATION_DEFINITION_CHECKS",
                    expected,
                ),
                mock.patch.object(MODULE, "aws_json") as aws,
                self.assertRaisesRegex(ValueError, error),
            ):
                MODULE.preflight(self.args())
            aws.assert_not_called()

    def test_registration_batch_runtime_numbers_must_be_exact_integers(self) -> None:
        cases = (
            ("batch_revision", ("batch", "revision"), 4.0),
            ("registration_revision", ("batch", "registration", "revision"), 4.0),
            ("retry_attempts", ("batch", "retry_attempts"), True),
            ("timeout_seconds", ("batch", "timeout_seconds"), 21600.0),
            ("vcpus", ("batch", "vcpus"), 8.0),
            ("memory_mib", ("batch", "memory_mib"), 32000.0),
        )

        for label, path, value in cases:
            with self.subTest(label=label):
                registration = json.loads(
                    self.registration.read_text(encoding="utf-8")
                )
                cursor = registration
                for key in path[:-1]:
                    cursor = cursor[key]
                cursor[path[-1]] = value
                self._write(self.registration, registration)

                with mock.patch.object(MODULE, "aws_json") as aws:
                    with self.assertRaisesRegex(
                        ValueError,
                        "materializer registration receipt/definition is not exact",
                    ):
                        MODULE.preflight(self.args())

                aws.assert_not_called()
                self._write_registration_receipts()

    def test_failed_registration_shell_literal_is_rejected_by_exact_map(self) -> None:
        definition = json.loads(self.job_definition.read_text(encoding="utf-8"))
        shell = definition["containerProperties"]["command"][2]
        source_uri = (
            f"s3://{self.private_bucket}/{self.final_prefix}"
            f"{MODULE.SOURCE_RELATIVES['source_vcf']}"
        )
        definition["containerProperties"]["command"][2] = shell.replace(
            f"--source-vcf-uri {source_uri} ",
            "",
        )
        self._write(self.job_definition, definition)

        registration = json.loads(self.registration.read_text(encoding="utf-8"))
        registration["batch"]["definition_sha256"] = MODULE.sha256_path(
            self.job_definition
        )
        self._write(self.registration, registration)

        with (
            mock.patch.object(MODULE, "aws_json") as aws,
            self.assertRaisesRegex(ValueError, "shell_source_vcf_uri"),
        ):
            MODULE.preflight(self.args())

        aws.assert_not_called()

    def test_failed_registration_definition_check_is_rejected_by_exact_map(self) -> None:
        registration = json.loads(self.registration.read_text(encoding="utf-8"))
        registration["authorized_hrd_state"] = "partial_evidence"
        self._write(self.registration, registration)

        with (
            mock.patch.object(MODULE, "aws_json") as aws,
            self.assertRaisesRegex(ValueError, "failed no_call_boundary"),
        ):
            MODULE.preflight(self.args())

        aws.assert_not_called()

    def test_live_definition_drift_is_rejected(self) -> None:
        definition = self.live_definition()
        definition["containerProperties"]["memory"] += 1
        with self.assertRaisesRegex(ValueError, "failed exact_payload"):
            self.run_preflight(aws=self.aws_side_effect(definition=definition))

    def test_live_definition_check_map_must_be_exact(self) -> None:
        cases = (
            (
                {
                    *MODULE.EXPECTED_LIVE_JOB_DEFINITION_CHECKS,
                    "future_live_definition_check",
                },
                "missing future_live_definition_check",
            ),
            (
                {
                    name
                    for name in MODULE.EXPECTED_LIVE_JOB_DEFINITION_CHECKS
                    if name != "immutable_image"
                },
                "unexpected immutable_image",
            ),
        )

        local = json.loads(self.job_definition.read_text(encoding="utf-8"))
        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(
                    MODULE,
                    "EXPECTED_LIVE_JOB_DEFINITION_CHECKS",
                    expected,
                ),
                mock.patch.object(
                    MODULE,
                    "aws_json",
                    return_value={"jobDefinitions": [self.live_definition()]},
                ),
                self.assertRaisesRegex(ValueError, error),
            ):
                MODULE.validate_live_definition(local, MODULE.REGION)

    def test_failed_live_definition_check_reports_exact_key(self) -> None:
        local = json.loads(self.job_definition.read_text(encoding="utf-8"))
        live = self.live_definition()
        live["revision"] = 3

        with (
            mock.patch.object(
                MODULE,
                "aws_json",
                return_value={"jobDefinitions": [live]},
            ),
            self.assertRaisesRegex(ValueError, "failed revision"),
        ):
            MODULE.validate_live_definition(local, MODULE.REGION)

    def test_live_definition_runtime_numbers_must_be_exact_integers(self) -> None:
        cases = (
            ("revision", ("revision",), 4.0, "failed revision"),
            ("retry_attempts", ("retryStrategy", "attempts"), True, "failed one_attempt"),
            ("vcpus", ("containerProperties", "vcpus"), 8.0, "failed exact_runtime"),
            (
                "memory",
                ("containerProperties", "memory"),
                32000.0,
                "failed exact_runtime",
            ),
            (
                "timeout",
                ("timeout", "attemptDurationSeconds"),
                21600.0,
                "failed exact_runtime",
            ),
        )

        local = json.loads(self.job_definition.read_text(encoding="utf-8"))
        for label, path, value, error in cases:
            with self.subTest(label=label):
                live = self.live_definition()
                cursor = live
                for key in path[:-1]:
                    cursor = cursor[key]
                cursor[path[-1]] = value

                with (
                    mock.patch.object(
                        MODULE,
                        "aws_json",
                        return_value={"jobDefinitions": [live]},
                    ),
                    self.assertRaisesRegex(ValueError, error),
                ):
                    MODULE.validate_live_definition(local, MODULE.REGION)

    def test_live_image_check_map_must_be_exact(self) -> None:
        cases = (
            (
                {*MODULE.EXPECTED_LIVE_IMAGE_CHECKS, "future_live_image_check"},
                "missing future_live_image_check",
            ),
            (
                {
                    name
                    for name in MODULE.EXPECTED_LIVE_IMAGE_CHECKS
                    if name != "index_media_type"
                },
                "unexpected index_media_type",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(MODULE, "EXPECTED_LIVE_IMAGE_CHECKS", expected),
                mock.patch.object(
                    MODULE,
                    "aws_json",
                    side_effect=self.aws_side_effect(),
                ),
                self.assertRaisesRegex(ValueError, error),
            ):
                MODULE.validate_live_image(MODULE.REGION)

    def test_failed_live_image_check_reports_exact_key(self) -> None:
        with (
            mock.patch.object(
                MODULE,
                "aws_json",
                side_effect=self.aws_side_effect(
                    image_platform={"architecture": "amd64", "os": "linux"}
                ),
            ),
            self.assertRaisesRegex(ValueError, "failed linux_arm64_only"),
        ):
            MODULE.validate_live_image(MODULE.REGION)

    def test_live_queue_check_map_must_be_exact(self) -> None:
        cases = (
            (
                {*MODULE.EXPECTED_LIVE_QUEUE_CHECKS, "future_live_queue_check"},
                "missing future_live_queue_check",
            ),
            (
                {
                    name
                    for name in MODULE.EXPECTED_LIVE_QUEUE_CHECKS
                    if name != "ce_arm_instances"
                },
                "unexpected ce_arm_instances",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(MODULE, "EXPECTED_LIVE_QUEUE_CHECKS", expected),
                mock.patch.object(
                    MODULE,
                    "aws_json",
                    side_effect=self.aws_side_effect(),
                ),
                self.assertRaisesRegex(ValueError, error),
            ):
                MODULE.validate_live_queue(MODULE.REGION)

    def test_failed_live_queue_check_reports_exact_key(self) -> None:
        with (
            mock.patch.object(
                MODULE,
                "aws_json",
                side_effect=self.aws_side_effect(queue_status="INVALID"),
            ),
            self.assertRaisesRegex(ValueError, "failed queue_live"),
        ):
            MODULE.validate_live_queue(MODULE.REGION)

    def test_x86_image_or_invalid_queue_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "ARM64-only"):
            self.run_preflight(aws=self.aws_side_effect(image_platform={"architecture": "amd64", "os": "linux"}))
        with self.assertRaisesRegex(ValueError, "queue/compute environment"):
            self.run_preflight(aws=self.aws_side_effect(queue_status="INVALID"))

    def test_prior_exact_job_name_in_any_status_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "job name already exists"):
            self.run_preflight(aws=self.aws_side_effect(existing_job=True))

    def test_destination_version_or_delete_history_is_rejected(self) -> None:
        for history in (
            {"Versions": [{"Key": "prior", "VersionId": "v"}], "IsTruncated": False},
            {
                "DeleteMarkers": [{"Key": "prior", "VersionId": "d"}],
                "IsTruncated": False,
            },
        ):
            with self.subTest(history=history), self.assertRaisesRegex(ValueError, "object or delete-marker history"):
                self.run_preflight(aws=self.aws_side_effect(history=history))

    def test_empty_history_consumes_key_and_version_markers(self) -> None:
        uri = (
            f"s3://{self.private_bucket}/runs/subject01/{self.run_id}/"
            "deterministic/provenance/crosscheck-materialization-receipts/"
        )
        pages = [
            {
                "IsTruncated": True,
                "NextKeyMarker": "next-key",
                "NextVersionIdMarker": "next-version",
            },
            {"IsTruncated": False},
        ]

        with mock.patch.object(MODULE, "aws_json", side_effect=pages) as aws_json:
            self.assertEqual(
                MODULE.require_empty_history(uri, MODULE.REGION),
                {"uri": uri, "page_count": 2, "history_count": 0},
            )

        self.assertEqual(
            aws_json.call_args_list[1].args,
            (
                MODULE.REGION,
                "s3api",
                "list-object-versions",
                "--bucket",
                self.private_bucket,
                "--prefix",
                f"runs/subject01/{self.run_id}/"
                "deterministic/provenance/crosscheck-materialization-receipts/",
                "--key-marker",
                "next-key",
                "--version-id-marker",
                "next-version",
            ),
        )

    def test_history_and_job_pagination_fail_closed(self) -> None:
        calls = 0

        def aws(region: str, *arguments: str):
            nonlocal calls
            calls += 1
            if tuple(arguments[:2]) == ("s3api", "list-object-versions"):
                return {"IsTruncated": True}
            return self.aws_side_effect()(region, *arguments)

        with self.assertRaisesRegex(ValueError, "omitted or repeated"):
            self.run_preflight(aws=aws)
        self.assertGreater(calls, 0)

        pages = (
            {"NextKeyMarker": "next-key"},
            {"NextKeyMarker": True, "NextVersionIdMarker": "next-version"},
            {"NextKeyMarker": "next-key", "NextVersionIdMarker": True},
        )
        for page in pages:
            with self.subTest(page=page), mock.patch.object(
                MODULE,
                "aws_json",
                return_value={"IsTruncated": True, **page},
            ):
                with self.assertRaisesRegex(ValueError, "omitted or repeated"):
                    MODULE.require_empty_history(
                        f"s3://{self.private_bucket}/runs/subject01/{self.run_id}/empty/",
                        MODULE.REGION,
                    )

    def test_batch_pagination_rejects_malformed_next_token(self) -> None:
        for value in (None, True):
            with self.subTest(nextToken=value):
                calls: list[tuple[str, ...]] = []

                def aws(region: str, *arguments: str):
                    self.assertEqual(region, MODULE.REGION)
                    calls.append(arguments)
                    return {"jobQueues": [], "nextToken": value}

                with (
                    mock.patch.object(MODULE, "aws_json", side_effect=aws),
                    self.assertRaisesRegex(
                        ValueError,
                        "malformed nextToken",
                    ),
                ):
                    MODULE.paginated_rows(
                        MODULE.REGION,
                        ["batch", "describe-job-queues"],
                        "jobQueues",
                    )

                self.assertEqual(len(calls), 1)

    def test_dry_run_main_emits_exclusive_mode_0600_without_submit(self) -> None:
        args = self.args()
        argv = [
            "submit_materializer_v4.py",
            "--run-id",
            args.run_id,
            "--final-freeze-receipt",
            str(args.final_freeze_receipt),
            "--final-freeze-anchor",
            str(args.final_freeze_anchor),
            "--exact-materialization-receipt",
            str(args.exact_materialization_receipt),
            "--reference-freeze-receipt",
            str(args.reference_freeze_receipt),
            "--reference-sha256-receipt",
            str(args.reference_sha256_receipt),
            "--materializer-script-anchor",
            str(args.materializer_script_anchor),
            "--registration-receipt",
            str(args.registration_receipt),
            "--job-definition-payload",
            str(args.job_definition_payload),
            "--request-output",
            str(args.request_output),
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(MODULE, "aws_json", side_effect=self.aws_side_effect()) as aws:
            self.assertEqual(MODULE.main(), 0)
        self.assertTrue(self.request_output.is_file())
        self.assertEqual(self.request_output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.request_output.read_text())["status"], "rendered_only")
        self.assertFalse(any(call.args[1:3] == ("batch", "submit-job") for call in aws.call_args_list))
        with mock.patch.object(sys, "argv", argv), mock.patch.object(MODULE, "aws_json") as untouched:
            with self.assertRaisesRegex(SystemExit, "refusing to overwrite"):
                MODULE.main()
        untouched.assert_not_called()

    def test_submit_rejects_duplicate_dry_run_receipt_before_submit(self) -> None:
        expected = self.preflight_receipt()
        dry_run = self.write_dry_run_receipt(expected)
        write_duplicate_json_field(dry_run, "schema_version", 0)

        with self.assertRaisesRegex(
            ValueError,
            "duplicate JSON object name in "
            "materializer dry-run request receipt: schema_version",
        ):
            MODULE.validate_dry_run_receipt(dry_run, expected)

    def test_request_receipt_fsyncs_parent_directory(self) -> None:
        with mock.patch.object(
            MODULE,
            "fsync_directory",
            wraps=MODULE.fsync_directory,
        ) as fsync_directory:
            MODULE.create_private(self.request_output, b'{"status":"passed"}\n')

        fsync_directory.assert_called_once_with(self.request_output.parent)

    def test_request_receipt_is_removed_after_parent_fsync_failure(self) -> None:
        with (
            mock.patch.object(
                MODULE,
                "fsync_directory",
                side_effect=OSError("synthetic request parent fsync failure"),
            ),
            self.assertRaisesRegex(
                OSError,
                "synthetic request parent fsync failure",
            ),
        ):
            MODULE.create_private(self.request_output, b'{"status":"passed"}\n')

        self.assertFalse(self.request_output.exists())

    def test_request_receipt_rehashes_after_parent_fsync(self) -> None:
        real_fsync_directory = MODULE.fsync_directory

        def tamper_after_parent_fsync(parent: Path) -> None:
            real_fsync_directory(parent)
            self.request_output.write_bytes(b"tampered")

        with (
            mock.patch.object(
                MODULE,
                "fsync_directory",
                side_effect=tamper_after_parent_fsync,
            ),
            self.assertRaisesRegex(
                ValueError,
                "private output changed during write",
            ),
        ):
            MODULE.create_private(self.request_output, b'{"status":"passed"}\n')

        self.assertFalse(self.request_output.exists())

    def test_response_reservation_fsyncs_parent_directory(self) -> None:
        descriptor = -1
        try:
            with mock.patch.object(
                MODULE,
                "fsync_directory",
                wraps=MODULE.fsync_directory,
            ) as fsync_directory:
                descriptor = MODULE.reserve_private(self.response_output)

            fsync_directory.assert_called_once_with(self.response_output.parent)
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def test_response_reservation_is_removed_after_parent_fsync_failure(self) -> None:
        with (
            mock.patch.object(
                MODULE,
                "fsync_directory",
                side_effect=OSError("synthetic response parent fsync failure"),
            ),
            self.assertRaisesRegex(
                OSError,
                "synthetic response parent fsync failure",
            ),
        ):
            MODULE.reserve_private(self.response_output)

        self.assertFalse(self.response_output.exists())

    def test_completed_response_receipt_rehashes_after_fsync(self) -> None:
        descriptor = MODULE.reserve_private(self.response_output)
        real_fsync = MODULE.os.fsync

        def tamper_after_fsync(file_descriptor: int) -> None:
            real_fsync(file_descriptor)
            self.response_output.write_bytes(b"tampered")

        with (
            mock.patch.object(MODULE.os, "fsync", side_effect=tamper_after_fsync),
            self.assertRaisesRegex(
                ValueError,
                "private output changed during write",
            ),
        ):
            MODULE.complete_reserved(
                descriptor,
                self.response_output,
                {"status": "submitted"},
            )

        self.assertTrue(self.response_output.exists())

    def test_submit_guard_is_required_before_receipt_or_aws(self) -> None:
        with (
            mock.patch.object(sys, "argv", self.argv(submit=True)),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(MODULE, "aws_json") as aws,
            self.assertRaisesRegex(SystemExit, "EXPENSIVE_RUN=YES"),
        ):
            MODULE.main()
        aws.assert_not_called()
        self.assertFalse(self.request_output.exists())
        self.assertFalse(self.response_output.exists())

    def test_submit_requires_matching_dry_run_receipt_before_submit(self) -> None:
        request = self.preflight_receipt()

        with (
            mock.patch.object(
                sys,
                "argv",
                self.argv(submit=True, bind_dry_run=False),
            ),
            mock.patch.dict(
                os.environ,
                {"HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES"},
                clear=True,
            ),
            mock.patch.object(MODULE, "preflight") as preflight,
            self.assertRaisesRegex(SystemExit, "requires --dry-run-receipt"),
        ):
            MODULE.main()

        preflight.assert_not_called()

        dry_run = self.write_dry_run_receipt(request)
        stale = json.loads(dry_run.read_text(encoding="utf-8"))
        stale["submit_job_request"]["jobName"] = "stale"
        dry_run.write_text(json.dumps(stale, indent=2, sort_keys=True) + "\n")

        with (
            mock.patch.object(
                sys,
                "argv",
                self.argv(submit=True, dry_run_receipt=dry_run),
            ),
            mock.patch.object(MODULE, "preflight", return_value=request),
            mock.patch.object(MODULE, "submit") as submitter,
            mock.patch.dict(
                os.environ,
                {"HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES"},
                clear=True,
            ),
            self.assertRaisesRegex(SystemExit, "does not match this submit"),
        ):
            MODULE.main()

        submitter.assert_not_called()
        self.assertFalse(self.request_output.exists())
        self.assertFalse(self.response_output.exists())

    def test_submit_rejects_non_integer_dry_run_schema_version(self) -> None:
        request = self.preflight_receipt()
        dry_run = self.write_dry_run_receipt(request)
        stale = json.loads(dry_run.read_text(encoding="utf-8"))
        stale["schema_version"] = 1.0
        dry_run.write_text(json.dumps(stale, indent=2, sort_keys=True) + "\n")

        with self.assertRaisesRegex(ValueError, "contract is malformed"):
            MODULE.validate_dry_run_receipt(dry_run, request)

    def test_submit_writes_distinct_request_and_response_receipts(self) -> None:
        response = {
            "jobName": "diana-wgs-hrd-materialize-20260716T033101Z",
            "jobId": "12345678-1234-1234-1234-123456789abc",
            "jobArn": ("arn:aws:batch:us-east-1:172630973301:job/12345678-1234-1234-1234-123456789abc"),
        }
        request = self.preflight_receipt(response["jobName"])
        dry_run = self.write_dry_run_receipt(request)
        with (
            mock.patch.object(MODULE, "preflight", return_value=request),
            mock.patch.object(MODULE, "submit", return_value=response) as submitter,
            mock.patch.dict(os.environ, {"HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES"}, clear=True),
        ):
            with mock.patch.object(
                sys,
                "argv",
                self.argv(submit=True, dry_run_receipt=dry_run),
            ):
                self.assertEqual(MODULE.main(), 0)
        submitter.assert_called_once()
        for path in (self.request_output, self.response_output):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        persisted = json.loads(self.response_output.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "submitted")
        self.assertEqual(persisted["response"], response)
        self.assertEqual(
            persisted["request_receipt"]["sha256"],
            hashlib.sha256(self.request_output.read_bytes()).hexdigest(),
        )

    def test_successful_submit_with_response_fsync_failure_requires_manual_reconciliation(self) -> None:
        response = {
            "jobName": "diana-wgs-hrd-materialize-20260716T033101Z",
            "jobId": "12345678-1234-1234-1234-123456789abc",
            "jobArn": ("arn:aws:batch:us-east-1:172630973301:job/12345678-1234-1234-1234-123456789abc"),
        }
        request = self.preflight_receipt(response["jobName"])
        dry_run = self.write_dry_run_receipt(request)
        with (
            mock.patch.object(
                sys,
                "argv",
                self.argv(submit=True, dry_run_receipt=dry_run),
            ),
            mock.patch.object(MODULE, "preflight", return_value=request),
            mock.patch.object(MODULE, "submit", return_value=response) as submitter,
            mock.patch.object(MODULE, "complete_reserved", side_effect=OSError("fsync failed")),
            mock.patch.dict(os.environ, {"HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES"}, clear=True),
            self.assertRaisesRegex(SystemExit, "submission succeeded.*do not retry before manual reconciliation"),
        ):
            MODULE.main()
        submitter.assert_called_once()
        self.assertTrue(self.response_output.exists())
        self.assertEqual(self.response_output.stat().st_mode & 0o777, 0o600)

    def test_schema_version_checks_use_exact_integer_helper(self) -> None:
        cases = (
            (1, 1, True),
            (1.0, 1, False),
            ("1", 1, False),
            (2, 1, False),
            (None, 1, False),
            (True, 1, False),
            (False, 0, False),
            (3.0, 3, False),
        )
        for value, expected, accepted in cases:
            with self.subTest(value=value, expected=expected):
                self.assertIs(
                    MODULE.exact_schema_version(
                        {"schema_version": value},
                        expected,
                    ),
                    accepted,
                )

    def test_schema_version_checks_avoid_raw_comparisons(self) -> None:
        module = ast.parse(
            (SCRIPT_DIR / "submit_materializer_v4.py").read_text(
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

    def test_request_and_response_paths_may_not_traverse_symlinks(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        direct_target = real_parent / "direct-target.json"
        linked_output = self.root / "linked-output.json"
        linked_output.symlink_to(direct_target)
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        (real_parent / "existing").mkdir()

        with self.assertRaisesRegex(FileExistsError, "may not be a symlink"):
            MODULE.require_new_outputs([linked_output])
        with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
            MODULE.require_new_outputs([linked_parent / "request.json"])
        with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
            MODULE.require_new_outputs([linked_parent / "missing" / "request.json"])
        with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
            MODULE.require_new_outputs([linked_parent / "existing" / "request.json"])

        self.assertFalse((real_parent / "missing").exists())
        self.assertFalse((real_parent / "existing" / "request.json").exists())

    def test_symlinked_request_path_fails_before_preflight(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        self.request_output = linked_parent / "request.json"

        with (
            mock.patch.object(sys, "argv", self.argv()),
            mock.patch.object(MODULE, "preflight") as preflight,
            self.assertRaisesRegex(SystemExit, "parent may not be a symlink"),
        ):
            MODULE.main()

        preflight.assert_not_called()
        self.assertFalse((real_parent / "request.json").exists())

    def test_symlinked_response_path_fails_before_preflight_or_submit(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        self.response_output = linked_parent / "response.json"

        with (
            mock.patch.object(sys, "argv", self.argv(submit=True)),
            mock.patch.dict(
                os.environ,
                {"HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES"},
                clear=True,
            ),
            mock.patch.object(MODULE, "preflight") as preflight,
            mock.patch.object(MODULE, "submit") as submitter,
            self.assertRaisesRegex(SystemExit, "parent may not be a symlink"),
        ):
            MODULE.main()

        preflight.assert_not_called()
        submitter.assert_not_called()
        self.assertFalse(self.request_output.exists())
        self.assertFalse((real_parent / "response.json").exists())

    def test_nested_symlinked_response_path_fails_before_preflight_or_submit(
        self,
    ) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        self.response_output = linked_parent / "missing" / "response.json"

        with (
            mock.patch.object(sys, "argv", self.argv(submit=True)),
            mock.patch.dict(
                os.environ,
                {"HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES"},
                clear=True,
            ),
            mock.patch.object(MODULE, "preflight") as preflight,
            mock.patch.object(MODULE, "submit") as submitter,
            self.assertRaisesRegex(SystemExit, "parent may not be a symlink"),
        ):
            MODULE.main()

        preflight.assert_not_called()
        submitter.assert_not_called()
        self.assertFalse(self.request_output.exists())
        self.assertFalse((real_parent / "missing").exists())

    def test_existing_symlinked_response_path_fails_before_preflight_or_submit(
        self,
    ) -> None:
        real_parent = self.root / "real-parent"
        (real_parent / "existing").mkdir(parents=True)
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        self.response_output = linked_parent / "existing" / "response.json"

        with (
            mock.patch.object(sys, "argv", self.argv(submit=True)),
            mock.patch.dict(
                os.environ,
                {"HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES"},
                clear=True,
            ),
            mock.patch.object(MODULE, "preflight") as preflight,
            mock.patch.object(MODULE, "submit") as submitter,
            self.assertRaisesRegex(SystemExit, "parent may not be a symlink"),
        ):
            MODULE.main()

        preflight.assert_not_called()
        submitter.assert_not_called()
        self.assertFalse(self.request_output.exists())
        self.assertFalse((real_parent / "existing" / "response.json").exists())


if __name__ == "__main__":
    unittest.main()
