#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

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
        with self.assertRaisesRegex(ValueError, "timeout is invalid"):
            MODULE.effective_job_controls(
                {
                    "retryStrategy": {"attempts": 1},
                    "timeout": {"attemptDurationSeconds": 0},
                }
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
        self.assertTrue(all(evidence["checks"].values()))

        wrong_host = dict(container_instance, ec2InstanceId="i-other-host")
        with self.assertRaisesRegex(ValueError, "ec2_instance"):
            MODULE.validate_host_binding(task, wrong_host, source, "cluster-1")


if __name__ == "__main__":
    unittest.main()
