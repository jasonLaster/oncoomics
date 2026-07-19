from __future__ import annotations

import ast
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
            "schema_version": 1,
            "status": "submission_authorized",
            "generated_at_utc": "2026-07-18T00:00:00Z",
            "scope": "private one-shot materializer-v4 submission preflight",
            "run_id": MODULE.RUN_ID,
            "classification_authorization": "none",
            "authorized_hrd_state": "no_call",
            "input_receipts": {},
            "custody": {},
            "live_preflight": {},
            "submit_job_request": {
                "jobName": "diana-wgs-hrd-materialize-20260716T033101Z",
                "jobQueue": "diana-omics-prod-use1-ondemand",
                "jobDefinition": (
                    "arn:aws:batch:us-east-1:172630973301:job-definition/"
                    "diana-wgs-hrd-materialize-crosscheck-inputs:4"
                ),
                "retryStrategy": {"attempts": 1},
                "parameters": {
                    name: self.parameters[name] for name in MODULE.PARAMETER_NAMES
                },
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
            "submitted_at_utc": "2026-07-18T00:01:00Z",
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
            "classification_authorization": "none",
            "authorized_hrd_state": "no_call",
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

    def test_rejects_inexact_submit_and_response_receipt_envelopes(self) -> None:
        original_request = copy.deepcopy(self.request)
        cases = (
            (
                "request_schema_float",
                lambda: self.request.__setitem__("schema_version", 1.0),
                True,
                "request receipt envelope is not exact",
            ),
            (
                "request",
                lambda: self.request.__setitem__("legacy_note", "accepted"),
                True,
                "request receipt envelope is not exact",
            ),
            (
                "submit_job_request",
                lambda: self.request["submit_job_request"].__setitem__(
                    "containerOverrides",
                    {},
                ),
                True,
                "SubmitJob request envelope is not exact",
            ),
            (
                "response_schema_float",
                lambda: self.response.__setitem__("schema_version", 1.0),
                False,
                "response receipt envelope is not exact",
            ),
            (
                "response",
                lambda: self.response.__setitem__("legacy_note", "accepted"),
                False,
                "response receipt envelope is not exact",
            ),
            (
                "request_summary",
                lambda: self.response["request_receipt"].__setitem__(
                    "legacy_note",
                    "accepted",
                ),
                False,
                "response request receipt summary is not exact",
            ),
            (
                "response_checks",
                lambda: self.response["checks"].__setitem__(
                    "legacy_check",
                    True,
                ),
                False,
                "response receipt checks are not exact",
            ),
            (
                "batch_response",
                lambda: self.response["response"].__setitem__(
                    "ResponseMetadata",
                    {},
                ),
                False,
                "Batch response envelope is not exact",
            ),
        )
        for label, mutate, rebind_response, message in cases:
            with self.subTest(label=label):
                self.request = copy.deepcopy(original_request)
                self.response = self.bound_response(self.request)
                mutate()
                if rebind_response:
                    self.response = self.bound_response(self.request)

                with self.assertRaisesRegex(ValueError, message):
                    MODULE.render_from_files(self.args())

    def test_rejects_request_below_symlinked_parent(self) -> None:
        args = self.args()
        real_parent = self.root / "real-inputs"
        real_parent.mkdir()
        relocated = real_parent / self.request_path.name
        relocated.write_bytes(self.request_path.read_bytes())
        linked_parent = self.root / "linked-inputs"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        args.request_receipt = linked_parent / self.request_path.name

        with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
            MODULE.render_from_files(args)

    def test_rejects_duplicate_receipt_object_names(self) -> None:
        for label, select_path in (
            ("request receipt", lambda args: args.request_receipt),
            ("response receipt", lambda args: args.response_receipt),
        ):
            with self.subTest(label=label):
                args = self.args()
                write_duplicate_json_field(select_path(args), "schema_version", 0)

                with self.assertRaisesRegex(
                    ValueError,
                    f"duplicate JSON object name in {label}: schema_version",
                ):
                    MODULE.render_from_files(args)

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

    def test_write_once_fsyncs_parent_directory(self) -> None:
        with mock.patch.object(
            MODULE,
            "fsync_directory",
            wraps=MODULE.fsync_directory,
        ) as fsync_directory:
            MODULE.write_once(self.output, "one\n")

        fsync_directory.assert_called_once_with(self.output.parent)

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

    def test_write_once_removes_output_after_parent_fsync_failure(self) -> None:
        with (
            mock.patch.object(
                MODULE,
                "fsync_directory",
                side_effect=OSError("synthetic parent fsync failure"),
            ),
            self.assertRaisesRegex(OSError, "synthetic parent fsync failure"),
        ):
            MODULE.write_once(self.output, "partial\n")

        self.assertFalse(self.output.exists())

    def test_write_once_rehashes_after_parent_fsync(self) -> None:
        real_fsync_directory = MODULE.fsync_directory

        def tamper_after_parent_fsync(path: Path) -> None:
            real_fsync_directory(path)
            self.output.write_text("tampered\n", encoding="utf-8")

        with (
            mock.patch.object(
                MODULE,
                "fsync_directory",
                side_effect=tamper_after_parent_fsync,
            ),
            self.assertRaisesRegex(ValueError, "output changed during write"),
        ):
            MODULE.write_once(self.output, "complete\n")

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

    def test_schema_version_checks_use_exact_integer_helper(self) -> None:
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
                    MODULE.exact_schema_version(
                        {"schema_version": value},
                        expected,
                    ),
                    accepted,
                )

    def test_schema_version_checks_avoid_raw_comparisons(self) -> None:
        module = ast.parse(
            (SCRIPT_DIR / "render_materializer_capture_command.py").read_text(
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


if __name__ == "__main__":
    unittest.main()
