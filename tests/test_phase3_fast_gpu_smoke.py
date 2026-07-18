from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import verify_phase3_fast_gpu_smoke as verify
from diana_omics.utils import write_json

PARABRICKS_REPOSITORY = "172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks"
SOURCE_DIGEST = "sha256:" + "b" * 64
DESTINATION_DIGEST = "sha256:" + "a" * 64
DIANA_GIT_COMMIT = "c" * 40
EXPECTED_TAG = "sha256-" + "b" * 64 + "-diana-" + "c" * 12


def p5en_params(**overrides):
    params = {
        "aws_gpu_queue": "diana-omics-prod-use2-gpu-p5en",
        "aws_job_role": "arn:aws:iam::172630973301:role/diana-omics-prod-use2-batch-job",
        "aws_logs_group": "/aws/batch/diana-omics-prod-use2",
        "aws_private_results_dir": "s3://diana-omics-private-results-172630973301-us-east-2/runs",
        "aws_region": "us-east-2",
        "aws_workdir": "s3://diana-omics-work-172630973301-us-east-2/work",
        "batch_gpu_p5en_instance_types": ["p5en.48xlarge"],
        "gpu_p5en_max_vcpus": 384,
        "parabricks_container": f"{PARABRICKS_REPOSITORY}@{DESTINATION_DIGEST}",
        "parabricks_mirror_repository": PARABRICKS_REPOSITORY,
        "phase3_fast_cache_kms_key_arn": ("arn:aws:kms:us-east-2:172630973301:key/12345678-abcd-1234-abcd-123456789abc"),
        "phase3_fast_cache_prefix": ("s3://diana-omics-private-results-172630973301-us-east-2/phase3-fast-cache/wgs-v2"),
        "phase3_fast_cache_region": "us-east-2",
    }
    params.update(overrides)
    return params


def parabricks_mirror_receipt() -> dict:
    return {
        "schema_version": 1,
        "manifest_type": "parabricks_mirror_receipt",
        "generated_at": "2026-07-18T00:00:00+00:00",
        "source": {
            "image": f"nvcr.io/nvidia/clara/parabricks@{SOURCE_DIGEST}",
            "digest": SOURCE_DIGEST,
            "platform": "linux/amd64",
        },
        "destination": {
            "region": "us-east-2",
            "repository": PARABRICKS_REPOSITORY,
            "tag": EXPECTED_TAG,
            "digest": DESTINATION_DIGEST,
            "parabricks_container": f"{PARABRICKS_REPOSITORY}@{DESTINATION_DIGEST}",
        },
        "diana_omics": {
            "git_commit": DIANA_GIT_COMMIT,
            "dockerfile_sha256": "sha256:" + "d" * 64,
        },
    }


def current_diana_source() -> dict:
    return {
        "dockerfile_sha256": "sha256:" + "d" * 64,
        "git_commit": DIANA_GIT_COMMIT,
    }


class Phase3FastGpuSmokeConfigTests(unittest.TestCase):
    def test_validates_p5en_gpu_params_before_aws_submission(self) -> None:
        summary = verify.validate_gpu_smoke_params(p5en_params())

        self.assertEqual("ready", summary["status"])
        self.assertEqual("diana-omics-prod-use2-gpu-p5en", summary["aws_gpu_queue"])
        self.assertEqual("us-east-2", summary["phase3_fast_cache_region"])
        self.assertEqual(384, summary["gpu_p5en_max_vcpus"])
        self.assertEqual(["p5en.48xlarge"], summary["instance_types"])
        self.assertEqual(
            "172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@sha256:" + "a" * 64,
            summary["parabricks_container"],
        )
        self.assertEqual(
            "172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks",
            summary["parabricks_mirror_repository"],
        )

    def test_rejects_empty_or_tagged_parabricks_container(self) -> None:
        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "parabricks_container"):
            verify.validate_gpu_smoke_params(p5en_params(parabricks_container=""))

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "sha256"):
            verify.validate_gpu_smoke_params(
                p5en_params(parabricks_container="172630973301.dkr.ecr.us-east-2.amazonaws.com/parabricks:latest")
            )

    def test_rejects_parabricks_container_outside_mirror(self) -> None:
        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "parabricks_mirror_repository"):
            verify.validate_gpu_smoke_params(p5en_params(parabricks_mirror_repository=""))

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "ECR repository URI in us-east-2"):
            verify.validate_gpu_smoke_params(
                p5en_params(parabricks_mirror_repository="172630973301.dkr.ecr.us-east-1.amazonaws.com/diana-omics/parabricks")
            )

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "pinned to parabricks_mirror_repository"):
            verify.validate_gpu_smoke_params(
                p5en_params(parabricks_container=("172630973301.dkr.ecr.us-east-2.amazonaws.com/other/parabricks@sha256:" + "a" * 64))
            )

    def test_rejects_non_p5en_queue_and_capacity(self) -> None:
        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "P5en GPU smoke is not ready"):
            verify.validate_gpu_smoke_params(
                p5en_params(
                    aws_gpu_queue="diana-omics-prod-use1-spot",
                    batch_gpu_p5en_instance_types=["p5.48xlarge"],
                    gpu_p5en_max_vcpus=8,
                )
            )

    def test_rejects_missing_or_public_phase3_fast_cache(self) -> None:
        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "phase3_fast_cache_prefix"):
            verify.validate_gpu_smoke_params(p5en_params(phase3_fast_cache_prefix=""))

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "private results bucket"):
            verify.validate_gpu_smoke_params(
                p5en_params(
                    phase3_fast_cache_prefix="s3://diana-omics-results-172630973301-us-east-2/phase3-fast-cache/wgs-v2",
                )
            )

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "phase3-fast-cache/wgs-v2"):
            verify.validate_gpu_smoke_params(
                p5en_params(
                    phase3_fast_cache_prefix="s3://diana-omics-private-results-172630973301-us-east-2/runs",
                )
            )

    def test_rejects_stale_cache_region_or_kms_key(self) -> None:
        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "phase3_fast_cache_region"):
            verify.validate_gpu_smoke_params(p5en_params(phase3_fast_cache_region="us-east-1"))

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "must end with -us-east-2"):
            verify.validate_gpu_smoke_params(
                p5en_params(
                    aws_workdir="s3://diana-omics-work-172630973301-us-east-20/work",
                    aws_private_results_dir="s3://diana-omics-private-results-172630973301-us-east-20/runs",
                    phase3_fast_cache_prefix=("s3://diana-omics-private-results-172630973301-us-east-20/phase3-fast-cache/wgs-v2"),
                )
            )

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "phase3_fast_cache_kms_key_arn"):
            verify.validate_gpu_smoke_params(
                p5en_params(
                    phase3_fast_cache_kms_key_arn=("arn:aws:kms:us-east-1:172630973301:key/12345678-abcd-1234-abcd-123456789abc"),
                )
            )

    def test_environment_loader_requires_real_generated_use2_params(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_params = root / "real-nextflow.aws.use2.json"
            write_json(real_params, p5en_params())
            cases = {
                "directory": root / "nextflow-dir",
                "missing": root / "missing-nextflow.aws.use2.json",
                "symlink": root / "nextflow.aws.use2.json",
            }
            cases["directory"].mkdir()
            cases["symlink"].symlink_to(real_params)

            for label, path in cases.items():
                with self.subTest(label=label), patch.dict(
                    "os.environ",
                    {"PHASE3_FAST_GPU_NEXTFLOW_PARAMS": str(path)},
                    clear=False,
                ):
                    with self.assertRaisesRegex(verify.GpuSmokeConfigError, "real file"):
                        verify.load_params_from_environment()

    def test_environment_loader_reads_override_path(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nextflow.aws.use2.json"
            write_json(path, p5en_params())

            with patch.dict("os.environ", {"PHASE3_FAST_GPU_NEXTFLOW_PARAMS": str(path)}, clear=False):
                params, loaded_path = verify.load_params_from_environment()

        self.assertEqual(path, loaded_path)
        self.assertEqual("us-east-2", params["aws_region"])

    def p5en_batch_queue(self, **overrides):
        queue = {
            "jobQueueName": "diana-omics-prod-use2-gpu-p5en",
            "state": "ENABLED",
            "status": "VALID",
            "computeEnvironmentOrder": [
                {
                    "order": 1,
                    "computeEnvironment": (
                        "arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"
                    ),
                }
            ],
        }
        queue.update(overrides)
        return queue

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.subprocess.run")
    def test_loads_live_p5en_batch_queue(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"jobQueues":[{"jobQueueName":"diana-omics-prod-use2-gpu-p5en"}]}',
        )

        queue = verify.load_gpu_batch_job_queue(queue="diana-omics-prod-use2-gpu-p5en", region="us-east-2")

        self.assertEqual("diana-omics-prod-use2-gpu-p5en", queue["jobQueueName"])
        self.assertEqual(
            [
                "aws",
                "batch",
                "describe-job-queues",
                "--region",
                "us-east-2",
                "--job-queues",
                "diana-omics-prod-use2-gpu-p5en",
                "--output",
                "json",
            ],
            run.call_args.args[0],
        )

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.subprocess.run")
    def test_live_p5en_batch_queue_cli_errors_are_reported(self, run) -> None:
        run.side_effect = subprocess.CalledProcessError(
            returncode=254,
            cmd=["aws"],
            output="AccessDenied",
        )

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "AccessDenied"):
            verify.load_gpu_batch_job_queue(queue="diana-omics-prod-use2-gpu-p5en", region="us-east-2")

    def test_validates_live_p5en_batch_queue(self) -> None:
        summary = verify.validate_gpu_batch_job_queue(
            self.p5en_batch_queue(),
            expected_queue="diana-omics-prod-use2-gpu-p5en",
        )

        self.assertEqual("ready", summary["status"])
        self.assertEqual("diana-omics-prod-use2-gpu-p5en", summary["job_queue"])
        self.assertTrue(summary["compute_environment"].endswith("/diana-omics-prod-use2-gpu-p5en-ondemand"))

    def test_rejects_invalid_or_drifted_p5en_batch_queue(self) -> None:
        for queue in (
            self.p5en_batch_queue(state="DISABLED"),
            self.p5en_batch_queue(status="INVALID"),
            self.p5en_batch_queue(computeEnvironmentOrder=[]),
            self.p5en_batch_queue(
                computeEnvironmentOrder=[
                    {
                        "order": 1,
                        "computeEnvironment": ("arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-ondemand"),
                    }
                ],
            ),
            self.p5en_batch_queue(
                computeEnvironmentOrder=[
                    {
                        "order": 2,
                        "computeEnvironment": (
                            "arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"
                        ),
                    }
                ],
            ),
            self.p5en_batch_queue(
                computeEnvironmentOrder=[
                    {
                        "computeEnvironment": (
                            "arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"
                        ),
                    }
                ],
            ),
        ):
            with self.subTest(queue=queue):
                with self.assertRaisesRegex(verify.GpuSmokeConfigError, "P5en Batch queue is not ready"):
                    verify.validate_gpu_batch_job_queue(
                        queue,
                        expected_queue="diana-omics-prod-use2-gpu-p5en",
                    )

    def p5en_compute_environment(self, **overrides):
        environment = {
            "computeEnvironmentArn": ("arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"),
            "computeEnvironmentName": "diana-omics-prod-use2-gpu-p5en-ondemand",
            "type": "MANAGED",
            "state": "ENABLED",
            "status": "VALID",
            "computeResources": {
                "allocationStrategy": "BEST_FIT_PROGRESSIVE",
                "type": "EC2",
                "minvCpus": 0,
                "instanceTypes": ["p5en.48xlarge"],
                "maxvCpus": 384,
                "ec2Configuration": [{"imageType": "ECS_AL2023_NVIDIA"}],
            },
        }
        environment.update(overrides)
        return environment

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.subprocess.run")
    def test_loads_live_p5en_compute_environment(self, run) -> None:
        arn = "arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"computeEnvironments":[{"computeEnvironmentArn":"' + arn + '"}]}',
        )

        environment = verify.load_gpu_batch_compute_environment(
            compute_environment=arn,
            region="us-east-2",
        )

        self.assertEqual(arn, environment["computeEnvironmentArn"])
        self.assertEqual(
            [
                "aws",
                "batch",
                "describe-compute-environments",
                "--region",
                "us-east-2",
                "--compute-environments",
                arn,
                "--output",
                "json",
            ],
            run.call_args.args[0],
        )

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.subprocess.run")
    def test_live_p5en_compute_environment_cli_errors_are_reported(self, run) -> None:
        run.side_effect = subprocess.CalledProcessError(
            returncode=254,
            cmd=["aws"],
            output="AccessDenied",
        )

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "AccessDenied"):
            verify.load_gpu_batch_compute_environment(
                compute_environment=("arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"),
                region="us-east-2",
            )

    def test_validates_live_p5en_compute_environment(self) -> None:
        arn = "arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"

        summary = verify.validate_gpu_batch_compute_environment(
            self.p5en_compute_environment(),
            expected_compute_environment=arn,
        )

        self.assertEqual(
            {
                "compute_environment": arn,
                "instance_types": ["p5en.48xlarge"],
                "max_vcpus": 384,
                "status": "ready",
            },
            summary,
        )

    def test_rejects_invalid_or_drifted_p5en_compute_environment(self) -> None:
        arn = "arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"

        for environment in (
            self.p5en_compute_environment(state="DISABLED"),
            self.p5en_compute_environment(status="INVALID"),
            self.p5en_compute_environment(type="UNMANAGED"),
            self.p5en_compute_environment(computeResources={"type": "SPOT"}),
            self.p5en_compute_environment(
                computeResources={
                    "allocationStrategy": "BEST_FIT_PROGRESSIVE",
                    "type": "EC2",
                    "minvCpus": 0,
                    "instanceTypes": ["g5.48xlarge"],
                    "maxvCpus": 384,
                    "ec2Configuration": [{"imageType": "ECS_AL2023_NVIDIA"}],
                }
            ),
            self.p5en_compute_environment(
                computeResources={
                    "allocationStrategy": "BEST_FIT_PROGRESSIVE",
                    "type": "EC2",
                    "minvCpus": 0,
                    "instanceTypes": ["p5en.48xlarge"],
                    "maxvCpus": 8,
                    "ec2Configuration": [{"imageType": "ECS_AL2023_NVIDIA"}],
                }
            ),
            self.p5en_compute_environment(
                computeResources={
                    "allocationStrategy": "BEST_FIT_PROGRESSIVE",
                    "type": "EC2",
                    "minvCpus": 0,
                    "instanceTypes": ["p5en.48xlarge"],
                    "maxvCpus": 384,
                    "ec2Configuration": [{"imageType": "ECS_AL2023"}],
                }
            ),
            self.p5en_compute_environment(
                computeResources={
                    "allocationStrategy": "BEST_FIT_PROGRESSIVE",
                    "type": "EC2",
                    "minvCpus": 192,
                    "instanceTypes": ["p5en.48xlarge"],
                    "maxvCpus": 384,
                    "ec2Configuration": [{"imageType": "ECS_AL2023_NVIDIA"}],
                }
            ),
            self.p5en_compute_environment(
                computeResources={
                    "allocationStrategy": "BEST_FIT_PROGRESSIVE",
                    "type": "EC2",
                    "minvCpus": 0,
                    "instanceTypes": ["p5en.48xlarge"],
                    "maxvCpus": 384,
                    "ec2Configuration": [
                        {"imageType": "ECS_AL2023"},
                        {"imageType": "ECS_AL2023_NVIDIA"},
                    ],
                }
            ),
            self.p5en_compute_environment(
                computeResources={
                    "allocationStrategy": "BEST_FIT",
                    "type": "EC2",
                    "minvCpus": 0,
                    "instanceTypes": ["p5en.48xlarge"],
                    "maxvCpus": 384,
                    "ec2Configuration": [{"imageType": "ECS_AL2023_NVIDIA"}],
                }
            ),
        ):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(verify.GpuSmokeConfigError, "P5en compute environment is not ready"):
                    verify.validate_gpu_batch_compute_environment(
                        environment,
                        expected_compute_environment=arn,
                    )

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.subprocess.run")
    def test_loads_live_running_on_demand_p_quota(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"Quota":{"Value":384.0}}',
        )

        quota = verify.load_running_on_demand_p_vcpus("us-east-2")

        self.assertEqual(384.0, quota)
        self.assertEqual(
            [
                "aws",
                "service-quotas",
                "get-service-quota",
                "--region",
                "us-east-2",
                "--service-code",
                "ec2",
                "--quota-code",
                "L-417A185B",
                "--output",
                "json",
            ],
            run.call_args.args[0],
        )

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.subprocess.run")
    def test_live_quota_cli_errors_are_reported(self, run) -> None:
        run.side_effect = subprocess.CalledProcessError(
            returncode=254,
            cmd=["aws"],
            output="AccessDenied",
        )

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "AccessDenied"):
            verify.load_running_on_demand_p_vcpus("us-east-2")

    def test_rejects_live_p_quota_below_one_p5en(self) -> None:
        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "at least 192"):
            verify.validate_running_on_demand_p_quota(8.0)

        verify.validate_running_on_demand_p_quota(192.0)

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.mirror_receipt.current_diana_source")
    def test_loads_source_bound_parabricks_mirror_receipt(self, current_source) -> None:
        current_source.return_value = current_diana_source()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "parabricks_mirror_receipt.json"
            write_json(path, parabricks_mirror_receipt())

            with patch.dict("os.environ", {"PARABRICKS_MIRROR_RECEIPT": str(path)}, clear=False):
                summary, loaded_path = verify.load_mirror_receipt_for_smoke(expected_params=verify.validate_gpu_smoke_params(p5en_params()))

        self.assertEqual(path, loaded_path)
        self.assertEqual(EXPECTED_TAG, summary["tag"])

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.mirror_receipt.current_diana_source")
    def test_rejects_source_mismatched_parabricks_mirror_receipt(self, current_source) -> None:
        current_source.return_value = current_diana_source()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "parabricks_mirror_receipt.json"
            stale = parabricks_mirror_receipt()
            stale["diana_omics"]["git_commit"] = "e" * 40
            stale["destination"]["tag"] = "sha256-" + "b" * 64 + "-diana-" + "e" * 12
            write_json(path, stale)

            with patch.dict("os.environ", {"PARABRICKS_MIRROR_RECEIPT": str(path)}, clear=False):
                with self.assertRaisesRegex(verify.GpuSmokeConfigError, "current Diana Git HEAD"):
                    verify.load_mirror_receipt_for_smoke(expected_params=verify.validate_gpu_smoke_params(p5en_params()))

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.mirror_receipt.current_diana_source")
    def test_rejects_wrong_image_parabricks_mirror_receipt(self, current_source) -> None:
        current_source.return_value = current_diana_source()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "parabricks_mirror_receipt.json"
            wrong_image = parabricks_mirror_receipt()
            wrong_image["destination"]["digest"] = "sha256:" + "e" * 64
            wrong_image["destination"]["parabricks_container"] = f"{PARABRICKS_REPOSITORY}@sha256:" + "e" * 64
            write_json(path, wrong_image)

            with patch.dict("os.environ", {"PARABRICKS_MIRROR_RECEIPT": str(path)}, clear=False):
                with self.assertRaisesRegex(verify.GpuSmokeConfigError, "current Nextflow params"):
                    verify.load_mirror_receipt_for_smoke(expected_params=verify.validate_gpu_smoke_params(p5en_params()))

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.subprocess.run")
    def test_loads_mirrored_parabricks_image_digest_from_ecr(self, run) -> None:
        digest = "sha256:" + "a" * 64
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"imageDetails":[{"imageDigest":"' + digest + '","imageTags":["' + EXPECTED_TAG + '"]}]}',
        )

        observed = verify.load_parabricks_mirror_image_digest(
            parabricks_container=("172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@" + digest),
            region="us-east-2",
            expected_tag=EXPECTED_TAG,
        )

        self.assertEqual(digest, observed)
        self.assertEqual(
            [
                "aws",
                "ecr",
                "describe-images",
                "--region",
                "us-east-2",
                "--repository-name",
                "diana-omics/parabricks",
                "--image-ids",
                "imageDigest=" + digest,
                "--output",
                "json",
            ],
            run.call_args.args[0],
        )

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.subprocess.run")
    def test_rejects_ambiguous_mirrored_parabricks_ecr_response(self, run) -> None:
        digest = "sha256:" + "a" * 64
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=('{"imageDetails":[{"imageDigest":"' + digest + '"},{"imageDigest":"sha256:' + "b" * 64 + '"}]}'),
        )

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "exactly one imageDetails"):
            verify.load_parabricks_mirror_image_digest(
                parabricks_container=("172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@" + digest),
                region="us-east-2",
            )

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.subprocess.run")
    def test_rejects_mirrored_parabricks_digest_without_source_tag(self, run) -> None:
        digest = "sha256:" + "a" * 64
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"imageDetails":[{"imageDigest":"' + digest + '","imageTags":["other"]}]}',
        )

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "imageTags"):
            verify.load_parabricks_mirror_image_digest(
                parabricks_container=("172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@" + digest),
                region="us-east-2",
                expected_tag=EXPECTED_TAG,
            )

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke.subprocess.run")
    def test_missing_mirrored_parabricks_image_is_reported_before_gpu_submission(self, run) -> None:
        run.side_effect = subprocess.CalledProcessError(
            returncode=254,
            cmd=["aws"],
            output="ImageNotFound",
        )

        with self.assertRaisesRegex(verify.GpuSmokeConfigError, "ImageNotFound"):
            verify.load_parabricks_mirror_image_digest(
                parabricks_container=("172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@sha256:" + "a" * 64),
                region="us-east-2",
            )


if __name__ == "__main__":
    unittest.main()
