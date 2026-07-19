#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SPEC = importlib.util.spec_from_file_location(
    "capture_batch_provenance", SCRIPT_DIR / "capture_batch_provenance.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class CaptureBatchProvenanceTests(unittest.TestCase):
    def test_evidence_path_is_exclusively_reserved_mode_0600_and_atomically_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "execution.json"
            MODULE.reserve_json(output, {"status": "reserved"})
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.reserve_json(output, {"status": "other"})
            MODULE.write_json_atomic(output, {"status": "passed"})
            self.assertEqual(json.loads(output.read_text()), {"status": "passed"})
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertFalse(any(output.parent.glob(".execution.json.*.tmp")))

    def test_reserve_json_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "execution.json"
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(ValueError, "JSON output changed during write"),
            ):
                MODULE.reserve_json(output, {"status": "in_progress"})

            self.assertFalse(output.exists())

    def test_write_json_atomic_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "execution.json"
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(ValueError, "JSON output changed during write"),
            ):
                MODULE.write_json_atomic(output, {"status": "passed"})

    def test_evidence_path_rejects_symlinked_parent_without_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-provenance"
            real_parent.mkdir()
            linked_parent = root / "linked-provenance"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
                MODULE.reserve_json(
                    linked_parent / "missing" / "execution.json",
                    {"status": "reserved"},
                )

            self.assertFalse((real_parent / "missing").exists())

    def test_evidence_path_rejects_existing_dir_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-provenance"
            real_parent.mkdir()
            (real_parent / "existing").mkdir()
            linked_parent = root / "linked-provenance"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            output = linked_parent / "existing" / "execution.json"

            with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
                MODULE.reserve_json(output, {"status": "reserved"})

            with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
                MODULE.write_json_atomic(output, {"status": "passed"})

            self.assertFalse((real_parent / "existing" / "execution.json").exists())

    def test_evidence_replacement_rejects_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-provenance"
            real_parent.mkdir()
            output = real_parent / "execution.json"
            MODULE.reserve_json(output, {"status": "reserved"})

            linked_parent = root / "linked-provenance"
            real_parent.rename(linked_parent)
            real_parent.symlink_to(linked_parent, target_is_directory=True)

            with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
                MODULE.write_json_atomic(output, {"status": "passed"})

            self.assertEqual(
                json.loads((linked_parent / "execution.json").read_text()),
                {"status": "reserved"},
            )

    def test_failure_receipt_replaces_only_the_current_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context = {
                "run_id": "run-1",
                "job_id": "job-1",
                "expected_status": "SUCCEEDED",
                "region": "us-east-1",
                "output": Path(temporary) / "execution.json",
            }
            MODULE.reserve_json(context["output"], MODULE.reserved_payload(context))

            MODULE.write_failure_if_reserved(
                context,
                SystemExit("Fail-closed: Batch job status is RUNNING"),
            )

            self.assertEqual(
                json.loads(context["output"].read_text()),
                {
                    **MODULE.reserved_payload(context),
                    "status": "failed",
                    "error": "Fail-closed: Batch job status is RUNNING",
                },
            )

    def test_failure_receipt_preserves_existing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "execution.json"
            context = {
                "run_id": "run-1",
                "job_id": "job-1",
                "expected_status": "SUCCEEDED",
                "region": "us-east-1",
                "output": output,
            }
            MODULE.reserve_json(output, {"status": "passed"})

            MODULE.write_failure_if_reserved(
                context,
                SystemExit(
                    "Fail-closed: provenance output already exists; preserve it "
                    "and use a new path"
                ),
            )

            self.assertEqual(json.loads(output.read_text()), {"status": "passed"})

    def test_failure_receipt_preserves_prior_reservations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context = {
                "run_id": "run-1",
                "job_id": "job-1",
                "expected_status": "SUCCEEDED",
                "region": "us-east-1",
                "output": Path(temporary) / "execution.json",
            }
            MODULE.reserve_json(context["output"], MODULE.reserved_payload(context))

            MODULE.write_failure_if_reserved(
                context,
                SystemExit(
                    "Fail-closed: provenance output already exists; preserve it "
                    "and use a new path"
                ),
            )

            self.assertEqual(
                json.loads(context["output"].read_text()),
                MODULE.reserved_payload(context),
            )

    def test_main_rejects_symlinked_worker_receipt_before_reservation_or_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            freeze_receipt = root / "executed-worker-freeze-receipt.json"
            freeze_receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
            linked_freeze = root / "linked-executed-worker-freeze-receipt.json"
            linked_freeze.symlink_to(freeze_receipt)
            receipt_upload = root / "executed-worker-freeze-receipt-upload.json"
            receipt_upload.write_text('{"status":"passed"}\n', encoding="utf-8")
            output = root / "terminal.execution.succeeded.json"
            argv = [
                "capture_batch_provenance.py",
                "--job-id",
                "job-id",
                "--run-id",
                "run-id",
                "--worker-uri",
                "s3://diana-omics-work-172630973301-us-east-1/worker.py",
                "--executed-worker-freeze-receipt",
                str(linked_freeze),
                "--executed-worker-freeze-receipt-upload",
                str(receipt_upload),
                "--output",
                str(output),
                "--expected-status",
                "SUCCEEDED",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(MODULE, "aws", side_effect=AssertionError("AWS called")),
                self.assertRaisesRegex(
                    SystemExit,
                    "executed-worker freeze receipt must be a real JSON file",
                ),
            ):
                MODULE.main()

            self.assertFalse(output.exists())

    def test_load_object_rejects_input_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-receipts"
            real_parent.mkdir()
            (real_parent / "receipt.json").write_text('{"status":"passed"}\n')
            linked_parent = root / "linked-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.load_object(
                    linked_parent / "receipt.json",
                    "executed-worker freeze receipt",
                )

    def test_get_exact_object_rejects_symlinked_worker_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "worker.py"

            def command(command, **kwargs):
                real_worker = destination.with_name("real-worker.py")
                real_worker.write_text("# frozen worker\n", encoding="utf-8")
                destination.symlink_to(real_worker)
                return "{}"

            with (
                patch.object(MODULE.subprocess, "check_output", side_effect=command),
                self.assertRaisesRegex(
                    ValueError,
                    "downloaded worker source may not be a symlink",
                ),
            ):
                MODULE.get_exact_object(
                    "us-east-1",
                    "diana-omics-private-results-unit",
                    "worker.py",
                    "worker-version",
                    destination,
                )

    def _command(
        self,
        command_id: str,
        instance_id: str,
        commands: list[str],
    ) -> dict[str, object]:
        return {
            "CommandId": command_id,
            "DocumentName": "AWS-RunShellScript",
            "InstanceIds": [instance_id],
            "Status": "Success",
            "RequestedDateTime": "2026-07-17T12:00:00Z",
            "Parameters": {"commands": commands},
        }

    def _invocation(
        self,
        command_id: str,
        instance_id: str,
        stdout: str = "expected output\n",
    ) -> dict[str, object]:
        return {
            "CommandId": command_id,
            "InstanceId": instance_id,
            "Status": "Success",
            "ResponseCode": 0,
            "ExecutionStartDateTime": "2026-07-17T12:00:00Z",
            "ExecutionEndDateTime": "2026-07-17T12:00:01Z",
            "StandardOutputContent": stdout,
            "StandardErrorContent": "",
        }

    def test_s3_location_requires_an_object(self) -> None:
        self.assertEqual(MODULE.s3_location("s3://private-bucket/path/to/worker.py"), ("private-bucket", "path/to/worker.py"))
        for invalid in ("https://example.test/file", "s3://bucket", "s3:///key"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                MODULE.s3_location(invalid)

    def test_ecs_cluster_is_derived_from_long_task_arn(self) -> None:
        arn = "arn:aws:ecs:us-east-1:000000000000:task/AWSBatch-example/0123456789abcdef"
        self.assertEqual(MODULE.ecs_cluster(arn), "AWSBatch-example")
        with self.assertRaises(ValueError):
            MODULE.ecs_cluster("arn:aws:ecs:us-east-1:000000000000:task/short")

    def test_parse_hash_command_output_binds_sha_and_bytes(self) -> None:
        digest = "a" * 64
        self.assertEqual(
            MODULE.parse_hash_command_output(
                f"{digest}  /work/runner/worker.py\n42272\n"
            ),
            (digest, 42272),
        )
        for malformed in (
            f"{digest}  /tmp/other.py\n42272\n",
            f"{digest}  /work/runner/worker.py\n0\n",
            "not-a-hash\n42272\n",
        ):
            with self.subTest(malformed=malformed), self.assertRaisesRegex(
                ValueError, "malformed"
            ):
                MODULE.parse_hash_command_output(malformed)

    def test_attempt_summary_preserves_terminal_identity_and_controls_scope(self) -> None:
        attempts = MODULE.summarize_attempts(
            [
                {
                    "startedAt": 10,
                    "stoppedAt": 20,
                    "statusReason": "Essential container exited",
                    "container": {
                        "containerInstanceArn": "arn:container-instance/1",
                        "taskArn": "arn:task/1",
                        "logStreamName": "stream/1",
                        "exitCode": 0,
                        "reason": "",
                        "networkInterfaces": [{"privateIpv4Address": "10.0.0.1"}],
                    },
                }
            ]
        )
        self.assertEqual(
            attempts,
            [
                {
                    "started_at_epoch_ms": 10,
                    "stopped_at_epoch_ms": 20,
                    "status_reason": "Essential container exited",
                    "container_instance_arn": "arn:container-instance/1",
                    "task_arn": "arn:task/1",
                    "log_stream": "stream/1",
                    "exit_code": 0,
                    "reason": "",
                }
            ],
        )
        self.assertEqual(MODULE.summarize_attempts(None), [])
        with self.assertRaisesRegex(ValueError, "not a list"):
            MODULE.summarize_attempts({})

    def test_attempt_summary_requires_exact_runtime_integers(self) -> None:
        cases = (
            ("startedAt", True),
            ("startedAt", 10.0),
            ("startedAt", "10"),
            ("stoppedAt", True),
            ("stoppedAt", 20.0),
            ("stoppedAt", "20"),
            ("exitCode", True),
            ("exitCode", 0.0),
            ("exitCode", "0"),
        )

        for field, value in cases:
            with self.subTest(field=field, value=value):
                attempt = {
                    "startedAt": 10,
                    "stoppedAt": 20,
                    "container": {"exitCode": 0},
                }
                if field == "exitCode":
                    attempt["container"][field] = value
                else:
                    attempt[field] = value

                with self.assertRaisesRegex(ValueError, "exact nonnegative"):
                    MODULE.summarize_attempts([attempt])

    def test_effective_job_controls_preserve_submit_overrides(self) -> None:
        retry, timeout = MODULE.effective_job_controls(
            {
                "retryStrategy": {"attempts": 1, "evaluateOnExit": []},
                "timeout": {"attemptDurationSeconds": 129600},
            }
        )
        self.assertEqual(retry, {"attempts": 1, "evaluateOnExit": []})
        self.assertEqual(timeout, {"attemptDurationSeconds": 129600})
        with self.assertRaisesRegex(ValueError, "omits effective"):
            MODULE.effective_job_controls({})
        with self.assertRaisesRegex(ValueError, "exact positive integer"):
            MODULE.effective_job_controls(
                {
                    "retryStrategy": {"attempts": 1},
                    "timeout": {"attemptDurationSeconds": 0},
                }
            )

    def test_effective_job_controls_require_exact_positive_integers(self) -> None:
        cases = (
            ("retry_bool", {"attempts": True}, {"attemptDurationSeconds": 129600}),
            ("retry_float", {"attempts": 1.0}, {"attemptDurationSeconds": 129600}),
            ("retry_string", {"attempts": "1"}, {"attemptDurationSeconds": 129600}),
            ("timeout_bool", {"attempts": 1}, {"attemptDurationSeconds": True}),
            ("timeout_float", {"attempts": 1}, {"attemptDurationSeconds": 129600.0}),
            ("timeout_string", {"attempts": 1}, {"attemptDurationSeconds": "129600"}),
        )
        for label, retry_strategy, timeout in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "exact positive integer"):
                    MODULE.effective_job_controls(
                        {
                            "retryStrategy": retry_strategy,
                            "timeout": timeout,
                        }
                    )

    def test_job_definition_revision_must_be_an_exact_positive_integer(self) -> None:
        for value in (True, 4.0, "4", 0, None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "exact positive integer"):
                    MODULE.require_positive_exact_int(
                        value,
                        "Batch job definition revision",
                    )

    def test_nonnegative_runtime_helper_requires_exact_integer(self) -> None:
        self.assertEqual(
            MODULE.require_nonnegative_exact_int(0, "Batch attempt exitCode"), 0
        )
        for value in (True, 0.0, "0", -1, None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "exact nonnegative"):
                    MODULE.require_nonnegative_exact_int(
                        value, "Batch attempt exitCode"
                    )

    def test_ssm_evidence_persists_exact_commands_and_hashes(self) -> None:
        command_id = "command-1"
        instance_id = "i-task-host"
        commands = MODULE.expected_hash_commands("runtime-id")
        evidence = MODULE.validate_ssm_command(
            self._command(command_id, instance_id, commands),
            self._invocation(command_id, instance_id),
            command_id=command_id,
            instance_id=instance_id,
            expected_commands=commands,
            label="hash",
        )
        self.assertEqual(evidence["command_bodies"], commands)
        self.assertEqual(
            evidence["command_body_sha256"],
            [hashlib.sha256(value.encode("utf-8")).hexdigest() for value in commands],
        )
        canonical = json.dumps(commands, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(
            evidence["command_set_sha256"],
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
        self.assertTrue(all(evidence["checks"].values()))

    def test_worker_freeze_command_pins_exact_checksum(self) -> None:
        worker_sha256 = "a" * 64
        commands = MODULE.expected_freeze_commands(
            "runtime-id",
            "private-bucket",
            "provenance/executed-workers/worker.py",
            "kms-key",
            worker_sha256,
            "us-east-1",
        )

        self.assertEqual(
            commands,
            [
                " ".join(
                    [
                        "docker",
                        "exec",
                        "runtime-id",
                        "/opt/diana-aws/bin/aws",
                        "s3api",
                        "put-object",
                        "--bucket",
                        "private-bucket",
                        "--key",
                        "provenance/executed-workers/worker.py",
                        "--body",
                        "/work/runner/worker.py",
                        "--server-side-encryption",
                        "aws:kms",
                        "--ssekms-key-id",
                        "kms-key",
                        "--checksum-algorithm",
                        "SHA256",
                        "--checksum-sha256",
                        MODULE.checksum_sha256(worker_sha256),
                        "--metadata",
                        (
                            f"sha256={worker_sha256},"
                            "source=active-ecs-task,classification=private"
                        ),
                        "--region",
                        "us-east-1",
                        "--output",
                        "json",
                    ]
                )
            ],
        )

    def test_fabricated_output_cannot_replace_expected_command(self) -> None:
        command_id = "command-1"
        instance_id = "i-task-host"
        expected = MODULE.expected_hash_commands("runtime-id")
        fabricated = [
            "printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  "
            "/work/runner/worker.py\\n42272\\n'"
        ]
        with self.assertRaisesRegex(ValueError, "exact_command_bodies"):
            MODULE.validate_ssm_command(
                self._command(command_id, instance_id, fabricated),
                self._invocation(
                    command_id,
                    instance_id,
                    "a" * 64 + "  /work/runner/worker.py\n42272\n",
                ),
                command_id=command_id,
                instance_id=instance_id,
                expected_commands=expected,
                label="hash",
            )

    def test_ssm_command_rejects_wrong_host(self) -> None:
        command_id = "command-1"
        expected = MODULE.expected_hash_commands("runtime-id")
        with self.assertRaisesRegex(ValueError, "single_exact_instance"):
            MODULE.validate_ssm_command(
                self._command(command_id, "i-other-host", expected),
                self._invocation(command_id, "i-other-host"),
                command_id=command_id,
                instance_id="i-task-host",
                expected_commands=expected,
                label="hash",
            )

    def test_ssm_command_response_code_must_be_exact_zero(self) -> None:
        command_id = "command-1"
        instance_id = "i-task-host"
        expected = MODULE.expected_hash_commands("runtime-id")

        for value in (True, 0.0, "0", None):
            with self.subTest(value=value):
                invocation = self._invocation(command_id, instance_id)
                invocation["ResponseCode"] = value

                with self.assertRaisesRegex(
                    ValueError, "invocation_response_code"
                ):
                    MODULE.validate_ssm_command(
                        self._command(command_id, instance_id, expected),
                        invocation,
                        command_id=command_id,
                        instance_id=instance_id,
                        expected_commands=expected,
                        label="hash",
                    )

    def test_ssm_command_rejects_extra_or_changed_command_body(self) -> None:
        command_id = "command-1"
        instance_id = "i-task-host"
        expected = MODULE.expected_hash_commands("runtime-id")
        changed = [*expected, "echo forged"]
        with self.assertRaisesRegex(ValueError, "exact_command_bodies"):
            MODULE.validate_ssm_command(
                self._command(command_id, instance_id, changed),
                self._invocation(command_id, instance_id),
                command_id=command_id,
                instance_id=instance_id,
                expected_commands=expected,
                label="hash",
            )

    def test_task_host_binding_requires_live_ec2_mapping(self) -> None:
        task = {"containerInstanceArn": "arn:container-instance/task-host"}
        source = {
            "ecs_cluster": "cluster-1",
            "container_instance_arn": "arn:container-instance/task-host",
            "ec2_instance_id": "i-task-host",
        }
        container_instance = {
            "containerInstanceArn": "arn:container-instance/task-host",
            "ec2InstanceId": "i-task-host",
            "status": "ACTIVE",
            "agentConnected": True,
        }
        evidence = MODULE.validate_host_binding(
            task, container_instance, source, "cluster-1"
        )
        self.assertEqual(
            evidence["checks"],
            MODULE.EXPECTED_TASK_HOST_BINDING_CHECKS,
        )

        wrong_host = dict(container_instance, ec2InstanceId="i-other-host")
        with self.assertRaisesRegex(ValueError, "ec2_instance"):
            MODULE.validate_host_binding(task, wrong_host, source, "cluster-1")

    def test_batch_worker_nested_check_maps_are_exact(self) -> None:
        self.assertEqual(
            MODULE.exact_batch_worker_nested_check_maps(
                dict(MODULE.EXPECTED_TASK_HOST_BINDING_CHECKS),
                dict(MODULE.EXPECTED_SSM_COMMAND_BINDING_CHECKS),
                dict(MODULE.EXPECTED_SSM_COMMAND_BINDING_CHECKS),
            ),
            {
                "task_host_mapping": True,
                "hash_command_definition": True,
                "freeze_command_definition": True,
            },
        )

        for location, label, mutate, failed_check in (
            (
                "host",
                "missing",
                lambda checks: checks.pop("receipt_cluster_matches_task"),
                "task_host_mapping",
            ),
            (
                "host",
                "unexpected",
                lambda checks: checks.__setitem__("forged_extra", True),
                "task_host_mapping",
            ),
            (
                "host",
                "failed",
                lambda checks: checks.__setitem__("ecs_container_instance_matches_task", False),
                "task_host_mapping",
            ),
            (
                "hash",
                "missing",
                lambda checks: checks.pop("exact_command_bodies"),
                "hash_command_definition",
            ),
            (
                "hash",
                "unexpected",
                lambda checks: checks.__setitem__("forged_extra", True),
                "hash_command_definition",
            ),
            (
                "hash",
                "failed",
                lambda checks: checks.__setitem__("invocation_response_code", False),
                "hash_command_definition",
            ),
            (
                "freeze",
                "missing",
                lambda checks: checks.pop("invocation_instance_id"),
                "freeze_command_definition",
            ),
            (
                "freeze",
                "unexpected",
                lambda checks: checks.__setitem__("forged_extra", True),
                "freeze_command_definition",
            ),
            (
                "freeze",
                "failed",
                lambda checks: checks.__setitem__("command_status", False),
                "freeze_command_definition",
            ),
        ):
            host_checks = dict(MODULE.EXPECTED_TASK_HOST_BINDING_CHECKS)
            hash_checks = dict(MODULE.EXPECTED_SSM_COMMAND_BINDING_CHECKS)
            freeze_checks = dict(MODULE.EXPECTED_SSM_COMMAND_BINDING_CHECKS)
            checks_by_location = {
                "host": host_checks,
                "hash": hash_checks,
                "freeze": freeze_checks,
            }
            mutate(checks_by_location[location])

            with self.subTest(location=location, label=label):
                result = MODULE.exact_batch_worker_nested_check_maps(
                    host_checks,
                    hash_checks,
                    freeze_checks,
                )
                self.assertFalse(result[failed_check])

    def test_executed_worker_receipt_check_maps_are_exact(self) -> None:
        self.assertEqual(
            MODULE.exact_executed_worker_check_maps(
                dict(MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_CHECKS),
                dict(MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_UPLOAD_CHECKS),
            ),
            {"freeze_receipt": True, "freeze_receipt_upload": True},
        )

        for location, label, mutate, failed_check in (
            (
                "freeze",
                "missing",
                lambda checks: checks.pop("container_file_uploaded_directly"),
                "freeze_receipt",
            ),
            (
                "freeze",
                "unexpected",
                lambda checks: checks.__setitem__("forged_extra", True),
                "freeze_receipt",
            ),
            (
                "freeze",
                "failed",
                lambda checks: checks.__setitem__("s3_exact_version_present", False),
                "freeze_receipt",
            ),
            (
                "upload",
                "missing",
                lambda checks: checks.pop("local_sha256_matches_s3_checksum"),
                "freeze_receipt_upload",
            ),
            (
                "upload",
                "unexpected",
                lambda checks: checks.__setitem__("forged_extra", True),
                "freeze_receipt_upload",
            ),
            (
                "upload",
                "failed",
                lambda checks: checks.__setitem__("exact_version", False),
                "freeze_receipt_upload",
            ),
        ):
            freeze_checks = dict(MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_CHECKS)
            upload_checks = dict(MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_UPLOAD_CHECKS)
            mutate(freeze_checks if location == "freeze" else upload_checks)

            with self.subTest(location=location, label=label):
                result = MODULE.exact_executed_worker_check_maps(
                    freeze_checks,
                    upload_checks,
                )
                self.assertFalse(result[failed_check])

    def test_executed_worker_receipt_envelopes_are_exact(self) -> None:
        freeze_receipt = {
            key: "value" for key in MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_RECEIPT_KEYS
        }
        freeze_receipt["source"] = {
            key: "value" for key in MODULE.EXPECTED_EXECUTED_WORKER_SOURCE_KEYS
        }
        freeze_receipt["freeze"] = {
            key: "value" for key in MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_KEYS
        }
        freeze_receipt["freeze"]["checksum_sha256_hex"] = "a" * 64
        freeze_receipt["freeze"]["metadata"] = {
            **MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_METADATA,
            "sha256": "a" * 64,
        }
        upload_receipt = {
            key: "value" for key in MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_UPLOAD_KEYS
        }
        upload_receipt["object"] = {
            key: "value"
            for key in MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_UPLOAD_OBJECT_KEYS
        }
        upload_receipt["object"]["metadata"] = (
            MODULE.EXPECTED_EXECUTED_WORKER_FREEZE_UPLOAD_METADATA
        )

        self.assertEqual(
            MODULE.exact_executed_worker_receipt_envelopes(
                freeze_receipt,
                upload_receipt,
            ),
            {
                "receipt_envelope": True,
                "receipt_source_envelope": True,
                "receipt_freeze_envelope": True,
                "receipt_freeze_metadata": True,
                "receipt_upload_envelope": True,
                "receipt_upload_object_envelope": True,
                "receipt_upload_metadata": True,
            },
        )

        for location, label, mutate, failed_check in (
            (
                "freeze_receipt",
                "missing",
                lambda receipt: receipt.pop("captured_at"),
                "receipt_envelope",
            ),
            (
                "freeze_receipt",
                "unexpected",
                lambda receipt: receipt.__setitem__("legacy_timestamp", True),
                "receipt_envelope",
            ),
            (
                "source",
                "missing",
                lambda receipt: receipt["source"].pop("container_path"),
                "receipt_source_envelope",
            ),
            (
                "source",
                "unexpected",
                lambda receipt: receipt["source"].__setitem__("legacy_host", True),
                "receipt_source_envelope",
            ),
            (
                "freeze",
                "missing",
                lambda receipt: receipt["freeze"].pop("head_verified"),
                "receipt_freeze_envelope",
            ),
            (
                "freeze",
                "unexpected",
                lambda receipt: receipt["freeze"].__setitem__(
                    "legacy_checksum",
                    True,
                ),
                "receipt_freeze_envelope",
            ),
            (
                "freeze",
                "missing-metadata",
                lambda receipt: receipt["freeze"]["metadata"].pop("source"),
                "receipt_freeze_metadata",
            ),
            (
                "freeze",
                "stale-metadata",
                lambda receipt: receipt["freeze"]["metadata"].__setitem__(
                    "classification",
                    "public",
                ),
                "receipt_freeze_metadata",
            ),
            (
                "freeze",
                "unexpected-metadata",
                lambda receipt: receipt["freeze"]["metadata"].__setitem__(
                    "legacy_metadata",
                    True,
                ),
                "receipt_freeze_metadata",
            ),
            (
                "upload",
                "missing",
                lambda receipt: receipt.pop("local_receipt_sha256"),
                "receipt_upload_envelope",
            ),
            (
                "upload",
                "unexpected",
                lambda receipt: receipt.__setitem__("legacy_upload", True),
                "receipt_upload_envelope",
            ),
            (
                "upload_object",
                "missing",
                lambda receipt: receipt["object"].pop("metadata"),
                "receipt_upload_object_envelope",
            ),
            (
                "upload_object",
                "unexpected",
                lambda receipt: receipt["object"].__setitem__(
                    "legacy_version",
                    True,
                ),
                "receipt_upload_object_envelope",
            ),
            (
                "upload_object",
                "missing-metadata",
                lambda receipt: receipt["object"]["metadata"].pop("artifact"),
                "receipt_upload_metadata",
            ),
            (
                "upload_object",
                "unexpected-metadata",
                lambda receipt: receipt["object"]["metadata"].__setitem__(
                    "legacy_metadata",
                    True,
                ),
                "receipt_upload_metadata",
            ),
        ):
            freeze = json.loads(json.dumps(freeze_receipt))
            upload = json.loads(json.dumps(upload_receipt))
            mutate(upload if location.startswith("upload") else freeze)

            with self.subTest(location=location, label=label):
                result = MODULE.exact_executed_worker_receipt_envelopes(
                    freeze,
                    upload,
                )
                self.assertFalse(result[failed_check])

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

    def test_exact_int_rejects_coercible_byte_values(self) -> None:
        for value in (1, 7):
            with self.subTest(value=value):
                self.assertTrue(MODULE.exact_int(value, value))
        for value in (True, 1.0, "1", 0, -1, None):
            with self.subTest(value=value):
                self.assertFalse(MODULE.exact_int(value, 1))

    def test_worker_byte_guards_avoid_raw_int_coercion(self) -> None:
        module = ast.parse(
            (SCRIPT_DIR / "capture_batch_provenance.py").read_text(
                encoding="utf-8"
            )
        )
        raw_byte_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "ContentLength",
                    "worker_source.get('bytes'",
                    'worker_source.get("bytes"',
                    "worker_freeze.get('bytes'",
                    'worker_freeze.get("bytes"',
                    "worker_receipt_upload_object.get('bytes'",
                    'worker_receipt_upload_object.get("bytes"',
                )
            )
        ]

        self.assertEqual(raw_byte_coercions, [])

    def test_batch_runtime_guards_avoid_raw_int_coercion(self) -> None:
        module = ast.parse(
            (SCRIPT_DIR / "capture_batch_provenance.py").read_text(
                encoding="utf-8"
            )
        )
        raw_runtime_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "createdAt",
                    "startedAt",
                    "stoppedAt",
                    "exitCode",
                    "ResponseCode",
                )
            )
        ]

        self.assertEqual(raw_runtime_coercions, [])

    def test_schema_version_checks_avoid_raw_comparisons(self) -> None:
        module = ast.parse(
            (SCRIPT_DIR / "capture_batch_provenance.py").read_text(
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
