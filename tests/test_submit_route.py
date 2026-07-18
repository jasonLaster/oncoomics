#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("submit_route_exact", ROOT / "aws/submit_route.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SubmitRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.request = self.root / "request.json"
        self.response = self.root / "response.json"
        self.submission_id = "20260717T010203Z-unit0001"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def live_definition(self, route_name: str = "sigprofiler_sbs3") -> dict:
        route = MODULE.ROUTES[route_name]
        return {
            "jobDefinitionName": route["job_definition_name"],
            "jobDefinitionArn": route["job_definition_arn"],
            "revision": 3,
            "status": "ACTIVE",
            "type": "container",
            "platformCapabilities": ["EC2"],
            "retryStrategy": {"attempts": 1, "evaluateOnExit": []},
            "timeout": {"attemptDurationSeconds": route["timeout_seconds"]},
            "containerProperties": {
                "image": route["image"],
                "vcpus": route["vcpus"],
                "memory": route["memory"],
                "command": route["command"],
                "jobRoleArn": MODULE.EXPECTED_JOB_ROLE,
                "environment": [{"name": name, "value": value} for name, value in route["definition_environment"].items()],
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": MODULE.LOG_GROUP,
                        "awslogs-region": MODULE.REGION,
                        "awslogs-stream-prefix": MODULE.LOG_STREAM_PREFIX,
                    },
                    "secretOptions": [],
                },
            },
        }

    def live_queue(self) -> dict:
        return {
            "jobQueueArn": MODULE.QUEUE_ARN,
            "jobQueueName": MODULE.QUEUE_NAME,
            "state": "ENABLED",
            "status": "VALID",
            "priority": 30,
            "computeEnvironmentOrder": [
                {
                    "order": 1,
                    "computeEnvironment": MODULE.COMPUTE_ENVIRONMENT_ARN,
                }
            ],
        }

    def live_compute(self) -> dict:
        return {
            "computeEnvironmentArn": MODULE.COMPUTE_ENVIRONMENT_ARN,
            "computeEnvironmentName": MODULE.QUEUE_NAME,
            "state": "ENABLED",
            "status": "VALID",
            "type": "MANAGED",
            "containerOrchestrationType": "ECS",
            "computeResources": {
                "type": "EC2",
                "allocationStrategy": "BEST_FIT_PROGRESSIVE",
                "minvCpus": 0,
                "maxvCpus": 128,
                "instanceTypes": list(MODULE.EXPECTED_INSTANCE_TYPES),
                "launchTemplate": {
                    "launchTemplateId": "lt-0b2375486d24af74a",
                    "version": "3",
                    "overrides": [],
                },
                "ec2Configuration": [{"imageType": "ECS_AL2023"}],
            },
        }

    def image_payload(
        self,
        route_name: str = "sigprofiler_sbs3",
        platform: dict | None = None,
    ) -> dict:
        route = MODULE.ROUTES[route_name]
        manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "digest": "sha256:" + "a" * 64,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "platform": platform or {"architecture": "amd64", "os": "linux"},
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
                    "imageId": {"imageDigest": str(route["image"]).rsplit("@", 1)[1]},
                    "imageManifestMediaType": ("application/vnd.oci.image.index.v1+json"),
                    "imageManifest": json.dumps(manifest),
                }
            ],
        }

    def preflight_receipt(self) -> dict:
        job_name = "subject01-sigprofiler-sbs3-unit0001-deadbeef"
        return {
            "schema_version": 1,
            "status": "submission_authorized",
            "route": "sigprofiler_sbs3",
            "submission_id": self.submission_id,
            "submit_job_request": {
                "jobName": job_name,
                "jobQueue": MODULE.QUEUE_NAME,
                "jobDefinition": MODULE.ROUTES["sigprofiler_sbs3"]["job_definition_arn"],
                "containerOverrides": {"environment": []},
                "retryStrategy": {"attempts": 1},
            },
        }

    def argv(self, *, submit: bool = False) -> list[str]:
        values = [
            "submit_route.py",
            "--route",
            "sigprofiler_sbs3",
            "--contract",
            str(self.root / "contract.json"),
            "--contract-uri",
            "s3://diana-omics-private-results-172630973301-us-east-1/contract.json",
            "--contract-version-id",
            "exact-version",
            "--contract-publication-anchor",
            str(self.root / "anchor.json"),
            "--submission-id",
            self.submission_id,
            "--request-output",
            str(self.request),
        ]
        if submit:
            values.extend(["--response-output", str(self.response), "--submit"])
        return values

    def test_both_routes_are_exact_revision_3_immutable_images(self) -> None:
        self.assertEqual(set(MODULE.ROUTES), {"sigprofiler_sbs3", "sequenza_scarhrd"})
        for route in MODULE.ROUTES.values():
            self.assertEqual(route["revision"], 3)
            self.assertTrue(route["job_definition_arn"].endswith(":3"))
            self.assertIn("@sha256:", route["image"])
            self.assertEqual(
                route["definition_environment"]["HRD_CROSSCHECK_IMAGE_REFERENCE"],
                route["image"],
            )

    def test_live_definition_requires_exact_active_static_environment(self) -> None:
        definition = self.live_definition()
        with mock.patch.object(
            MODULE,
            "aws_json",
            return_value={"jobDefinitions": [definition]},
        ):
            result = MODULE.validate_live_definition("sigprofiler_sbs3", MODULE.REGION)
        self.assertTrue(all(result["checks"].values()))
        for mutation in ("status", "environment", "image"):
            altered = copy.deepcopy(definition)
            if mutation == "status":
                altered["status"] = "INACTIVE"
            elif mutation == "environment":
                altered["containerProperties"]["environment"][0]["value"] = "wrong"
            else:
                altered["containerProperties"]["image"] = "registry.invalid/image@sha256:" + "0" * 64
            with (
                self.subTest(mutation=mutation),
                mock.patch.object(
                    MODULE,
                    "aws_json",
                    return_value={"jobDefinitions": [altered]},
                ),
                self.assertRaisesRegex(ValueError, "exact expected definition"),
            ):
                MODULE.validate_live_definition("sigprofiler_sbs3", MODULE.REGION)

    def test_live_image_requires_exact_linux_amd64_index(self) -> None:
        with mock.patch.object(
            MODULE,
            "aws_json",
            return_value=self.image_payload(),
        ):
            result = MODULE.validate_live_image("sigprofiler_sbs3", MODULE.REGION)
        self.assertTrue(all(result["checks"].values()))
        with (
            mock.patch.object(
                MODULE,
                "aws_json",
                return_value=self.image_payload(platform={"architecture": "arm64", "os": "linux"}),
            ),
            self.assertRaisesRegex(ValueError, "not exact amd64"),
        ):
            MODULE.validate_live_image("sigprofiler_sbs3", MODULE.REGION)

    def test_live_queue_requires_exact_x86_compute_environment(self) -> None:
        queue = self.live_queue()
        compute = self.live_compute()
        with mock.patch.object(
            MODULE,
            "aws_json",
            side_effect=[
                {"jobQueues": [queue]},
                {"computeEnvironments": [compute]},
            ],
        ):
            result = MODULE.validate_live_queue(MODULE.REGION)
        self.assertTrue(all(result["checks"].values()))
        altered = copy.deepcopy(compute)
        altered["computeResources"]["instanceTypes"] = ["c7g"]
        with (
            mock.patch.object(
                MODULE,
                "aws_json",
                side_effect=[
                    {"jobQueues": [queue]},
                    {"computeEnvironments": [altered]},
                ],
            ),
            self.assertRaisesRegex(ValueError, "queue/compute environment"),
        ):
            MODULE.validate_live_queue(MODULE.REGION)

    def test_exact_job_name_is_scanned_across_every_queue_and_status(self) -> None:
        calls: list[tuple[str, ...]] = []

        def pages(region: str, arguments: list[str], field: str):
            self.assertEqual(region, MODULE.REGION)
            calls.append(tuple(arguments))
            if field == "jobQueues":
                return [
                    {"jobQueueArn": MODULE.QUEUE_ARN},
                    {"jobQueueArn": "arn:aws:batch:us-east-1:172630973301:job-queue/other"},
                ]
            return []

        with mock.patch.object(MODULE, "paginated_rows", side_effect=pages):
            result = MODULE.require_no_existing_job("exact-name", MODULE.REGION)
        self.assertEqual(result["queue_count"], 2)
        list_calls = [call for call in calls if call[:2] == ("batch", "list-jobs")]
        self.assertEqual(len(list_calls), 2 * len(MODULE.JOB_STATUSES))

    def test_prior_exact_job_name_in_any_queue_status_is_rejected(self) -> None:
        def pages(region: str, arguments: list[str], field: str):
            del region
            if field == "jobQueues":
                return [{"jobQueueArn": MODULE.QUEUE_ARN}]
            if arguments[-1] == "FAILED":
                return [
                    {
                        "jobId": "prior",
                        "jobName": "exact-name",
                        "status": "FAILED",
                    }
                ]
            return []

        with (
            mock.patch.object(MODULE, "paginated_rows", side_effect=pages),
            self.assertRaisesRegex(ValueError, "exact route job name already exists"),
        ):
            MODULE.require_no_existing_job("exact-name", MODULE.REGION)

    def test_dry_run_writes_only_create_only_mode_0600_request_receipt(self) -> None:
        receipt = self.preflight_receipt()
        with (
            mock.patch.object(sys, "argv", self.argv()),
            mock.patch.object(MODULE, "preflight", return_value=receipt),
            mock.patch.object(MODULE, "submit") as submit,
        ):
            self.assertEqual(MODULE.main(), 0)
        submit.assert_not_called()
        self.assertEqual(self.request.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.request.read_text()), receipt)
        self.assertFalse(self.response.exists())
        with (
            mock.patch.object(sys, "argv", self.argv()),
            mock.patch.object(MODULE, "preflight") as preflight,
            self.assertRaisesRegex(SystemExit, "refusing to overwrite"),
        ):
            MODULE.main()
        preflight.assert_not_called()

    def test_submit_guards_fire_before_receipts_or_aws(self) -> None:
        for environment, message in (
            ({}, "EXPENSIVE_RUN=YES"),
            ({"HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES"}, "LICENSE_REVIEWED=YES"),
        ):
            with (
                self.subTest(environment=environment),
                mock.patch.object(sys, "argv", self.argv(submit=True)),
                mock.patch.dict(os.environ, environment, clear=True),
                mock.patch.object(MODULE, "preflight") as preflight,
                self.assertRaisesRegex(SystemExit, message),
            ):
                MODULE.main()
            preflight.assert_not_called()
            self.assertFalse(self.request.exists())
            self.assertFalse(self.response.exists())

    def test_request_receipt_fsyncs_parent_directory(self) -> None:
        with mock.patch.object(
            MODULE,
            "fsync_directory",
            wraps=MODULE.fsync_directory,
        ) as fsync_directory:
            MODULE.create_private(self.request, b'{"status":"passed"}\n')

        fsync_directory.assert_called_once_with(self.request.parent)

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
            MODULE.create_private(self.request, b'{"status":"passed"}\n')

        self.assertFalse(self.request.exists())

    def test_request_receipt_rehashes_after_parent_fsync(self) -> None:
        real_fsync_directory = MODULE.fsync_directory

        def tamper_after_parent_fsync(parent: Path) -> None:
            real_fsync_directory(parent)
            self.request.write_bytes(b"tampered")

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
            MODULE.create_private(self.request, b'{"status":"passed"}\n')

        self.assertFalse(self.request.exists())

    def test_response_reservation_fsyncs_parent_directory(self) -> None:
        descriptor = -1
        try:
            with mock.patch.object(
                MODULE,
                "fsync_directory",
                wraps=MODULE.fsync_directory,
            ) as fsync_directory:
                descriptor = MODULE.reserve_private(self.response)

            fsync_directory.assert_called_once_with(self.response.parent)
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
            MODULE.reserve_private(self.response)

        self.assertFalse(self.response.exists())

    def test_completed_response_receipt_rehashes_after_fsync(self) -> None:
        descriptor = MODULE.reserve_private(self.response)
        real_fsync = MODULE.os.fsync

        def tamper_after_fsync(file_descriptor: int) -> None:
            real_fsync(file_descriptor)
            self.response.write_bytes(b"tampered")

        with (
            mock.patch.object(MODULE.os, "fsync", side_effect=tamper_after_fsync),
            self.assertRaisesRegex(
                ValueError,
                "private output changed during write",
            ),
        ):
            MODULE.complete_reserved(
                descriptor,
                self.response,
                {"status": "submitted"},
            )

        self.assertTrue(self.response.exists())

    def test_submit_captures_job_id_and_arn_in_distinct_mode_0600_receipt(self) -> None:
        receipt = self.preflight_receipt()
        job_id = "12345678-1234-1234-1234-123456789abc"
        response = {
            "jobName": receipt["submit_job_request"]["jobName"],
            "jobId": job_id,
            "jobArn": f"arn:aws:batch:{MODULE.REGION}:{MODULE.ACCOUNT_ID}:job/{job_id}",
        }
        with (
            mock.patch.object(sys, "argv", self.argv(submit=True)),
            mock.patch.dict(
                os.environ,
                {
                    "HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES",
                    "HRD_CROSSCHECK_LICENSE_REVIEWED": "YES",
                },
                clear=True,
            ),
            mock.patch.object(MODULE, "preflight", return_value=receipt),
            mock.patch.object(MODULE, "submit", return_value=response),
        ):
            self.assertEqual(MODULE.main(), 0)
        for path in (self.request, self.response):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        persisted = json.loads(self.response.read_text())
        self.assertEqual(persisted["status"], "submitted")
        self.assertEqual(persisted["job_id"], job_id)
        self.assertEqual(persisted["job_arn"], response["jobArn"])
        self.assertEqual(persisted["response"], response)

    def test_submit_failure_writes_ambiguity_receipt_and_forbids_retry(self) -> None:
        receipt = self.preflight_receipt()
        with (
            mock.patch.object(sys, "argv", self.argv(submit=True)),
            mock.patch.dict(
                os.environ,
                {
                    "HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES",
                    "HRD_CROSSCHECK_LICENSE_REVIEWED": "YES",
                },
                clear=True,
            ),
            mock.patch.object(MODULE, "preflight", return_value=receipt),
            mock.patch.object(MODULE, "submit", side_effect=TimeoutError("uncertain")),
            self.assertRaisesRegex(SystemExit, "do not retry"),
        ):
            MODULE.main()
        persisted = json.loads(self.response.read_text())
        self.assertEqual(persisted["status"], "submission_failed_or_ambiguous")
        self.assertTrue(persisted["manual_reconciliation_required"])
        self.assertEqual(self.response.stat().st_mode & 0o777, 0o600)

    def test_response_receipt_is_reserved_before_submit(self) -> None:
        receipt = self.preflight_receipt()

        def verify_reserved(request: dict, region: str) -> dict:
            del request, region
            self.assertTrue(self.response.exists())
            self.assertEqual(self.response.stat().st_mode & 0o777, 0o600)
            raise TimeoutError("uncertain")

        with (
            mock.patch.object(sys, "argv", self.argv(submit=True)),
            mock.patch.dict(
                os.environ,
                {
                    "HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES",
                    "HRD_CROSSCHECK_LICENSE_REVIEWED": "YES",
                },
                clear=True,
            ),
            mock.patch.object(MODULE, "preflight", return_value=receipt),
            mock.patch.object(MODULE, "submit", side_effect=verify_reserved),
            self.assertRaises(SystemExit),
        ):
            MODULE.main()

    def test_submit_response_must_bind_job_name_id_and_arn(self) -> None:
        request = self.preflight_receipt()["submit_job_request"]
        responses = (
            {
                "jobName": "wrong",
                "jobId": "12345678-1234-1234-1234-123456789abc",
                "jobArn": "x",
            },
            {
                "jobName": request["jobName"],
                "jobId": "not-a-uuid",
                "jobArn": "x",
            },
        )
        for response in responses:
            with (
                self.subTest(response=response),
                mock.patch.object(MODULE, "aws_json", return_value=response),
                self.assertRaisesRegex(ValueError, "does not bind"),
            ):
                MODULE.submit(request, MODULE.REGION)

    def test_request_and_response_paths_must_be_distinct_and_new(self) -> None:
        same = self.root / "same.json"
        with self.assertRaisesRegex(ValueError, "must be distinct"):
            MODULE.require_new_outputs([same, same])
        same.write_text("existing", encoding="utf-8")
        with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
            MODULE.require_new_outputs([same])

    def test_request_and_response_paths_may_not_traverse_symlinks(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        direct_target = real_parent / "direct-target.json"
        linked_output = self.root / "linked-output.json"
        linked_output.symlink_to(direct_target)
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)

        with self.assertRaisesRegex(FileExistsError, "may not be a symlink"):
            MODULE.require_new_outputs([linked_output])
        with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
            MODULE.require_new_outputs([linked_parent / "request.json"])
        with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
            MODULE.require_new_outputs([linked_parent / "missing" / "request.json"])

    def test_symlinked_request_path_fails_before_preflight(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        self.request = linked_parent / "request.json"

        with (
            mock.patch.object(sys, "argv", self.argv()),
            mock.patch.object(MODULE, "preflight") as preflight,
            self.assertRaisesRegex(SystemExit, "parent may not be a symlink"),
        ):
            MODULE.main()

        preflight.assert_not_called()
        self.assertFalse((real_parent / "request.json").exists())

    def test_symlinked_response_path_fails_before_submit(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        self.response = linked_parent / "response.json"

        with (
            mock.patch.object(sys, "argv", self.argv(submit=True)),
            mock.patch.dict(
                os.environ,
                {
                    "HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN": "YES",
                    "HRD_CROSSCHECK_LICENSE_REVIEWED": "YES",
                },
                clear=True,
            ),
            mock.patch.object(MODULE, "preflight") as preflight,
            mock.patch.object(MODULE, "submit") as submit,
            self.assertRaisesRegex(SystemExit, "parent may not be a symlink"),
        ):
            MODULE.main()

        preflight.assert_not_called()
        submit.assert_not_called()
        self.assertFalse(self.request.exists())
        self.assertFalse((real_parent / "response.json").exists())

    def test_submission_environment_has_exact_seven_names(self) -> None:
        environment = MODULE.build_submission_environment(
            contract_uri="s3://private/contract",
            contract_version_id="version",
            contract_sha256="a" * 64,
            output_uri="s3://private/output",
            route_output_uri="s3://private/route/",
            publication_receipt_prefix="s3://private/receipts/",
            submission_id=self.submission_id,
        )
        self.assertEqual(
            tuple(row["name"] for row in environment),
            MODULE.SUBMISSION_ENVIRONMENT_NAMES,
        )
        self.assertEqual(len(environment), 7)


if __name__ == "__main__":
    unittest.main()
