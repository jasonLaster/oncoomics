from __future__ import annotations

import copy
import hashlib
import json
import shlex
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import render_materializer_capture_command as MODULE  # noqa: E402


def submitter_canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


class RenderMaterializerCaptureCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.request_path = self.root / "request.json"
        self.response_path = self.root / "response.json"
        self.output = self.root / "capture-command.sh"
        self.capture_output = self.root / "capture.json"
        self.anchor_output = self.root / "anchor.json"
        self.receipt_output = self.root / "receipt.json"
        self.job_id = "12345678-1234-1234-1234-123456789abc"
        self.parameters = {
            "source_vcf_version_id": "source-vcf-version",
            "source_vcf_index_version_id": "source-vcf-index-version",
            "source_matrix_version_id": "source-matrix-version",
            "source_vcf_sha256": "a" * 64,
            "source_vcf_index_sha256": "b" * 64,
            "source_matrix_sha256": "c" * 64,
            "reference_fasta_version_id": "reference-fasta-version",
            "reference_fai_version_id": "reference-fai-version",
        }
        self.request = {
            "status": "submission_authorized",
            "run_id": MODULE.RUN_ID,
            "submit_job_request": {
                "jobName": "diana-wgs-hrd-materialize-20260716T033101Z",
                "retryStrategy": {"attempts": 1},
                "parameters": {
                    name: self.parameters[name] for name in MODULE.PARAMETER_NAMES
                },
            },
        }
        self.response = self.bound_response(self.request)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def bound_response(self, request: dict) -> dict:
        self.request_path.write_text(
            json.dumps(request, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            "schema_version": 1,
            "status": "submitted",
            "run_id": MODULE.RUN_ID,
            "request_receipt": {
                "path": str(self.request_path.resolve()),
                "sha256": hashlib.sha256(self.request_path.read_bytes()).hexdigest(),
            },
            "submit_job_request_sha256": hashlib.sha256(
                submitter_canonical_bytes(request["submit_job_request"])
            ).hexdigest(),
            "response": {
                "jobName": request["submit_job_request"]["jobName"],
                "jobId": self.job_id,
                "jobArn": f"{MODULE.AWS_BATCH_ARN_PREFIX}{self.job_id}",
            },
            "checks": {
                "request_receipt_mode_0600": True,
                "exact_job_name": True,
                "job_id_and_arn": True,
                "one_shot_no_retry": True,
            },
        }

    def args(self) -> object:
        self.request_path.write_text(
            json.dumps(self.request, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.response_path.write_text(
            json.dumps(self.response, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return type(
            "Args",
            (),
            {
                "request_receipt": self.request_path,
                "response_receipt": self.response_path,
                "output": self.output,
                "capture_output": self.capture_output,
                "anchor_output": self.anchor_output,
                "receipt_output": self.receipt_output,
                "expected_receipt_prefix": (
                    f"{MODULE.DETERMINISTIC_DESTINATION_PREFIX}/provenance/"
                    "crosscheck-materialization-receipts/"
                ),
                "expected_kms_key_arn": MODULE.KMS_KEY_ARN,
                "region": MODULE.REGION,
            },
        )()

    def test_renders_exact_capture_command_from_bound_receipts(self) -> None:
        command = MODULE.render_from_files(self.args())

        lines = command.splitlines()
        self.assertEqual(lines[:2], ["#!/usr/bin/env bash", "set -euo pipefail"])
        self.assertEqual(
            shlex.split(lines[2]),
            [
                "python3",
                str(SCRIPT_DIR / "capture_materializer_terminal.py"),
                "--job-id",
                self.job_id,
                *[
                    token
                    for name in MODULE.PARAMETER_NAMES
                    for token in (
                        "--expected-parameter",
                        f"{name}={self.parameters[name]}",
                    )
                ],
                "--expected-receipt-prefix",
                (
                    f"{MODULE.DETERMINISTIC_DESTINATION_PREFIX}/provenance/"
                    "crosscheck-materialization-receipts/"
                ),
                "--expected-kms-key-arn",
                MODULE.KMS_KEY_ARN,
                "--capture-output",
                str(self.capture_output),
                "--anchor-output",
                str(self.anchor_output),
                "--receipt-output",
                str(self.receipt_output),
                "--region",
                MODULE.REGION,
            ],
        )
        self.assertNotIn("<", command)

    def test_submit_request_hash_matches_submitter_newline_canonical_json(self) -> None:
        self.assertEqual(
            MODULE.canonical_bytes({"z": 1, "a": 2}),
            b'{"a":2,"z":1}\n',
        )
        self.assertEqual(
            hashlib.sha256(
                MODULE.canonical_bytes(self.request["submit_job_request"])
            ).hexdigest(),
            self.response["submit_job_request_sha256"],
        )

    def test_refuses_to_render_from_tampered_request(self) -> None:
        self.response = self.bound_response(self.request)
        self.request["submit_job_request"]["parameters"]["source_vcf_sha256"] = "d" * 64

        with self.assertRaisesRegex(ValueError, "not bound to the request"):
            MODULE.render_from_files(self.args())

    def test_requires_all_materializer_parameters(self) -> None:
        mutations = {
            "missing": lambda params: params.pop("source_vcf_version_id"),
            "bad_sha": lambda params: params.__setitem__("source_vcf_sha256", "A" * 64),
            "whitespace": lambda params: params.__setitem__(
                "source_matrix_version_id", "version with spaces"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                request = copy.deepcopy(self.request)
                mutate(request["submit_job_request"]["parameters"])
                self.response = self.bound_response(request)
                self.request = request

                with self.assertRaises(ValueError):
                    MODULE.render_from_files(self.args())

    def test_write_once_uses_mode_0600_and_refuses_replacement(self) -> None:
        MODULE.write_once(self.output, "one\n")

        self.assertEqual(self.output.read_text(encoding="utf-8"), "one\n")
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            MODULE.write_once(self.output, "two\n")

    def test_write_once_removes_partial_output_after_fsync_failure(self) -> None:
        with (
            mock.patch.object(
                MODULE.os,
                "fsync",
                side_effect=OSError("synthetic fsync failure"),
            ),
            self.assertRaisesRegex(OSError, "synthetic fsync failure"),
        ):
            MODULE.write_once(self.output, "partial\n")

        self.assertFalse(self.output.exists())

    def test_write_once_rejects_symlinked_parent_without_writing_target(self) -> None:
        real_parent = self.root / "real-output"
        real_parent.mkdir()
        symlink_parent = self.root / "linked-output"
        symlink_parent.symlink_to(real_parent, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "output parent is a symlink"):
            MODULE.write_once(symlink_parent / "capture.sh", "redirected\n")

        self.assertFalse((real_parent / "capture.sh").exists())

    def test_write_once_rejects_nested_symlinked_parent_without_writing_target(
        self,
    ) -> None:
        real_parent = self.root / "real-output"
        real_parent.mkdir()
        symlink_parent = self.root / "linked-output"
        symlink_parent.symlink_to(real_parent, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "output parent is a symlink"):
            MODULE.write_once(
                symlink_parent / "missing" / "capture.sh",
                "redirected\n",
            )

        self.assertFalse((real_parent / "missing" / "capture.sh").exists())

    def test_write_once_rejects_existing_child_under_symlinked_parent(self) -> None:
        real_parent = self.root / "real-output"
        (real_parent / "existing").mkdir(parents=True)
        symlink_parent = self.root / "linked-output"
        symlink_parent.symlink_to(real_parent, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "output parent is a symlink"):
            MODULE.write_once(
                symlink_parent / "existing" / "capture.sh",
                "redirected\n",
            )

        self.assertFalse((real_parent / "existing" / "capture.sh").exists())


if __name__ == "__main__":
    unittest.main()
