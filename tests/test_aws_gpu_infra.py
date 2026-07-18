from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
MAIN_TF = ROOT / "infra/aws/main.tf"
VARIABLES_TF = ROOT / "infra/aws/variables.tf"
OUTPUTS_TF = ROOT / "infra/aws/outputs.tf"
NEXTFLOW_CONFIG = ROOT / "nextflow.config"
PUSH_IMAGE = ROOT / "infra/aws/push-image.sh"
MIRROR_PARABRICKS = ROOT / "infra/aws/mirror-parabricks.sh"
PARABRICKS_DOCKERFILE = ROOT / "infra/aws/Dockerfile.parabricks"
AWS_README = ROOT / "infra/aws/README.md"
NEXT_GEN_DOC = ROOT / "docs/operations/next-generation-fast-rerun.md"
DOCKERIGNORE = ROOT / ".dockerignore"


def resource_block(text: str, resource_type: str, resource_name: str) -> str:
    pattern = re.compile(rf'resource "{re.escape(resource_type)}" "{re.escape(resource_name)}" \{{')
    match = pattern.search(text)
    if not match:
        raise AssertionError(f"Missing {resource_type}.{resource_name}")

    depth = 0
    for index in range(match.end() - 1, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start() : index + 1]
    raise AssertionError(f"Unterminated {resource_type}.{resource_name}")


def run_mirror_parabricks_preflight(*, source_image: str, platform: str = "linux/amd64") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PARABRICKS_SOURCE_IMAGE"] = source_image
    env["PARABRICKS_PLATFORM"] = platform
    return subprocess.run(
        ["bash", str(MIRROR_PARABRICKS)],
        check=False,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def mirror_parabricks_receipt_writer() -> str:
    script = MIRROR_PARABRICKS.read_text(encoding="utf-8")
    start = script.index("<<'PY'\n") + len("<<'PY'\n")
    end = script.index("\nPY\n\nPARABRICKS_MIRROR_RECEIPT=", start)
    return script[start:end]


def run_mirror_parabricks_receipt_writer(receipt_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-",
            str(receipt_path),
            "nvcr.io/nvidia/clara/parabricks@sha256:" + "a" * 64,
            "sha256:" + "a" * 64,
            "linux/amd64",
            "us-east-2",
            "172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks",
            "sha256-" + "a" * 64 + "-diana-" + "b" * 12,
            "sha256:" + "c" * 64,
            "b" * 40,
            "sha256:" + "d" * 64,
        ],
        input=mirror_parabricks_receipt_writer(),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


class AwsGpuInfraTests(unittest.TestCase):
    def test_gpu_p5en_compute_environment_is_isolated_nvidia_ondemand(self) -> None:
        text = MAIN_TF.read_text(encoding="utf-8")
        block = resource_block(text, "aws_batch_compute_environment", "gpu_p5en_ondemand")

        self.assertIn('name         = "${local.name_prefix}-gpu-p5en-ondemand"', block)
        self.assertIn('type                = "EC2"', block)
        self.assertIn("max_vcpus           = var.gpu_p5en_max_vcpus", block)
        self.assertIn("instance_type       = var.batch_gpu_p5en_instance_types", block)
        self.assertIn('image_type = "ECS_AL2023_NVIDIA"', block)
        self.assertIn('Workload     = "parabricks-p5en"', block)
        self.assertNotIn("var.batch_arm_instance_families", block)

    def test_gpu_queue_targets_only_gpu_environment(self) -> None:
        text = MAIN_TF.read_text(encoding="utf-8")
        block = resource_block(text, "aws_batch_job_queue", "gpu_p5en")

        self.assertIn('name     = "${local.name_prefix}-gpu-p5en"', block)
        self.assertIn("aws_batch_compute_environment.gpu_p5en_ondemand.arn", block)
        self.assertNotIn("aws_batch_compute_environment.ondemand.arn", block)
        self.assertNotIn("aws_batch_compute_environment.spot.arn", block)

    def test_launch_template_mounts_p5en_instance_store_as_scratch(self) -> None:
        text = MAIN_TF.read_text(encoding="utf-8")
        block = resource_block(text, "aws_launch_template", "batch")

        self.assertIn("prepare_scratch()", block)
        self.assertIn("mkdir -p /scratch", block)
        self.assertIn("chmod 1777 /scratch", block)
        self.assertIn("nvme-Amazon_EC2_NVMe_Instance_Storage", block)
        self.assertIn("dnf install -y mdadm xfsprogs", block)
        self.assertIn("mdadm --create /dev/md0", block)
        self.assertIn('--raid-devices="$${#instance_store_devices[@]}"', block)
        self.assertIn("mkfs.xfs -f /dev/md0", block)
        self.assertIn("mount -o noatime,nodiratime /dev/md0 /scratch", block)

    def test_nextflow_params_export_gpu_queue_and_unselected_parabricks_image(self) -> None:
        text = MAIN_TF.read_text(encoding="utf-8")
        variables = VARIABLES_TF.read_text(encoding="utf-8")
        outputs = OUTPUTS_TF.read_text(encoding="utf-8")

        self.assertIn('filename        = "${path.module}/${var.nextflow_params_filename}"', text)
        self.assertIn('variable "nextflow_params_filename"', variables)
        self.assertRegex(text, r"aws_gpu_queue\s+=\s+aws_batch_job_queue\.gpu_p5en\.name")
        self.assertRegex(text, r"batch_gpu_p5en_instance_types\s+=\s+var\.batch_gpu_p5en_instance_types")
        self.assertRegex(text, r"gpu_p5en_max_vcpus\s+=\s+var\.gpu_p5en_max_vcpus")
        self.assertRegex(text, r"parabricks_container\s+=\s+var\.parabricks_container")
        self.assertIn('parabricks_mirror_repository  = try(aws_ecr_repository.parabricks[0].repository_url, "")', text)
        self.assertIn('output "parabricks_mirror_repository_url"', outputs)
        self.assertRegex(text, r"phase3_fast_cache_kms_key_arn\s+=\s+aws_kms_key\.main\.arn")
        self.assertRegex(text, r"phase3_fast_cache_region\s+=\s+var\.region")
        self.assertIn(
            'phase3_fast_cache_prefix      = "s3://${aws_s3_bucket.this["private_results"].bucket}/phase3-fast-cache/wgs-v2"',
            text,
        )

    def test_gpu_defaults_match_requested_quota_and_leave_image_unpinned(self) -> None:
        text = VARIABLES_TF.read_text(encoding="utf-8")

        self.assertIn('variable "gpu_p5en_max_vcpus"', text)
        self.assertIn("default     = 384", text)
        self.assertIn('default     = ["p5en.48xlarge"]', text)
        self.assertIn('variable "parabricks_container"', text)
        self.assertIn('variable "enable_parabricks_mirror"', text)
        self.assertIn('default     = ""', text)
        self.assertIn("default     = false", text)

    def test_parabricks_mirror_repository_is_optional_and_immutable(self) -> None:
        text = MAIN_TF.read_text(encoding="utf-8")
        block = resource_block(text, "aws_ecr_repository", "parabricks")

        self.assertIn("count = var.enable_parabricks_mirror ? 1 : 0", block)
        self.assertIn('name                 = "${var.project}/parabricks"', block)
        self.assertIn('image_tag_mutability = "IMMUTABLE"', block)
        self.assertIn("kms_key         = aws_kms_key.main.arn", block)
        self.assertIn('Workload     = "parabricks-p5en"', block)

    def test_bootstrap_cli_can_track_exact_service_quota_requests(self) -> None:
        text = MAIN_TF.read_text(encoding="utf-8")

        self.assertIn('resource "aws_iam_policy" "bootstrap_local_cli"', text)
        self.assertIn('resource "aws_iam_user_policy_attachment" "bootstrap_local_cli"', text)
        self.assertNotIn('resource "aws_iam_user_policy" "bootstrap_local_cli"', text)
        self.assertIn('"servicequotas:RequestServiceQuotaIncrease"', text)
        self.assertIn('"servicequotas:GetRequestedServiceQuotaChange"', text)
        self.assertIn('"servicequotas:GetServiceQuota"', text)

    def test_use2_can_reuse_account_global_service_linked_roles(self) -> None:
        text = MAIN_TF.read_text(encoding="utf-8")
        variables = VARIABLES_TF.read_text(encoding="utf-8")

        self.assertIn('variable "manage_service_linked_roles"', variables)
        self.assertIn("count = var.manage_service_linked_roles ? 1 : 0", text)
        self.assertIn("from = aws_iam_service_linked_role.batch", text)
        self.assertIn("to   = aws_iam_service_linked_role.batch[0]", text)
        self.assertIn('batch_service_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}', text)
        self.assertIn("service_role = local.batch_service_role_arn", text)

    def test_batch_job_role_can_replicate_versioned_phase3_fast_sources(self) -> None:
        text = MAIN_TF.read_text(encoding="utf-8")
        variables = VARIABLES_TF.read_text(encoding="utf-8")

        self.assertIn('variable "phase3_fast_source_region"', variables)
        self.assertIn('default     = "us-east-1"', variables)
        self.assertIn('variable "phase3_fast_source_environment"', variables)
        self.assertIn('default     = "prod-use1"', variables)
        self.assertIn("phase3_fast_source_bucket_names", text)
        self.assertIn(
            "${var.project}-private-results-${data.aws_caller_identity.current.account_id}-${var.phase3_fast_source_region}", text
        )
        self.assertIn("${var.project}-raw-inputs-${data.aws_caller_identity.current.account_id}-${var.phase3_fast_source_region}", text)
        self.assertIn('sid    = "ReadPhase3FastVersionedSourceObjects"', text)
        self.assertIn('"s3:GetObjectVersion"', text)
        self.assertIn('sid    = "DecryptPhase3FastSourceKmsKey"', text)
        self.assertIn('"arn:aws:kms:${var.phase3_fast_source_region}:${data.aws_caller_identity.current.account_id}:key/*"', text)
        self.assertIn('variable = "kms:ResourceAliases"', text)
        self.assertIn('"alias/${var.project}-${var.phase3_fast_source_environment}"', text)

    def test_outputs_and_nextflow_profile_expose_gpu_queue(self) -> None:
        outputs = OUTPUTS_TF.read_text(encoding="utf-8")
        nextflow = NEXTFLOW_CONFIG.read_text(encoding="utf-8")
        awsbatch_gpu = nextflow[nextflow.index("awsbatch_gpu {") :]

        self.assertIn('output "gpu_p5en_compute_environment"', outputs)
        self.assertIn('output "gpu_p5en_queue"', outputs)
        self.assertIn("aws_gpu_queue = null", nextflow)
        self.assertIn("parabricks_container = null", nextflow)
        self.assertIn("awsbatch_gpu", nextflow)
        self.assertIn("withLabel: gpu_parabricks", nextflow)
        self.assertIn("queue = params.aws_gpu_queue", nextflow)
        self.assertIn("container = params.parabricks_container", nextflow)
        self.assertIn("accelerator = params.phase3_fast_parabricks_num_gpus as int", nextflow)
        self.assertIn("withLabel: cpu_io", nextflow)
        self.assertIn("queue = params.aws_ondemand_queue", nextflow)
        self.assertIn("container = params.container", nextflow)
        self.assertIn("aws.batch.volumes = ['/scratch:/scratch']", awsbatch_gpu)

    def test_ecr_push_can_target_dedicated_workspaces(self) -> None:
        script = PUSH_IMAGE.read_text(encoding="utf-8")

        self.assertIn("DIANA_AWS_TERRAFORM_WORKSPACE", script)
        self.assertIn('terraform -chdir="${ROOT_DIR}/infra/aws" workspace select "${TARGET_WORKSPACE}"', script)
        self.assertIn("trap restore_workspace EXIT", script)
        self.assertIn("output -raw region", script)

    def test_parabricks_mirror_requires_reviewed_digest_and_writes_pin_receipt(self) -> None:
        script = MIRROR_PARABRICKS.read_text(encoding="utf-8")

        self.assertIn("PARABRICKS_SOURCE_IMAGE must be pinned as <registry>/<image>@sha256:<64 hex>", script)
        self.assertNotIn(",,}", script)
        self.assertIn("tr 'A-F' 'a-f'", script)
        self.assertIn('git -C "${ROOT_DIR}" status --porcelain --untracked-files=all', script)
        self.assertIn("results/full_wes_benchmark/full_wes_benchmark_summary.json", script)
        self.assertIn('diana_revision="$(git -C "${ROOT_DIR}" rev-parse --verify HEAD)"', script)
        self.assertIn("for-each-ref", script)
        self.assertIn("push ${diana_revision} to a remote", script)
        self.assertIn('target_tag="sha256-${source_digest_hex}-diana-${diana_revision_short}"', script)
        self.assertNotIn("PARABRICKS_MIRROR_TAG", script)
        self.assertIn("Reusing immutable", script)
        self.assertIn('docker pull --platform "${PLATFORM}" "${SOURCE_IMAGE}"', script)
        self.assertIn("Dockerfile.parabricks", script)
        self.assertIn("PARABRICKS_BASE_IMAGE", script)
        self.assertIn("docker build", script)
        self.assertIn("DIANA_PARABRICKS_DOCKERFILE", script)
        self.assertIn("Diana Parabricks Dockerfile must be a real file", script)
        self.assertNotIn('docker tag "${SOURCE_IMAGE}" "${target_image}"', script)
        self.assertIn("output -raw parabricks_mirror_repository_url", script)
        self.assertIn("aws ecr describe-images", script)
        self.assertIn('"parabricks_mirror_receipt"', script)
        self.assertIn("Parabricks mirror receipt output may not be a symlink", script)
        self.assertIn("Parabricks mirror receipt parent may not be a symlink", script)
        self.assertIn("Temporary Parabricks mirror receipt already exists", script)
        self.assertIn("temporary_path.replace(receipt_path)", script)
        self.assertIn("verify:parabricks-mirror-receipt", script)
        self.assertIn("TF_VAR_parabricks_container", script)

    def test_parabricks_mirror_rejects_malformed_source_image_before_git_aws_or_docker(self) -> None:
        for source_image in (
            "nvcr.io/nvidia/clara/parabricks:latest",
            "bad mirror@sha256:" + "a" * 64,
        ):
            with self.subTest(source_image=source_image):
                result = run_mirror_parabricks_preflight(source_image=source_image)

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "PARABRICKS_SOURCE_IMAGE must be pinned as <registry>/<image>@sha256:<64 hex>",
                    result.stderr,
                )

    def test_parabricks_mirror_rejects_non_amd64_platform_before_git_aws_or_docker(self) -> None:
        result = run_mirror_parabricks_preflight(
            source_image="nvcr.io/nvidia/clara/parabricks@sha256:" + "a" * 64,
            platform="linux/arm64",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("PARABRICKS_PLATFORM must be linux/amd64", result.stderr)

    def test_parabricks_mirror_receipt_writer_refuses_redirected_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_receipt = root / "real-receipt.json"
            symlink_receipt = root / "receipt.json"
            symlink_receipt.symlink_to(real_receipt)

            result = run_mirror_parabricks_receipt_writer(symlink_receipt)

            self.assertFalse(real_receipt.exists())

        self.assertNotEqual(0, result.returncode)
        self.assertIn("may not be a symlink", result.stderr)

    def test_parabricks_mirror_receipt_writer_refuses_symlinked_parents(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-receipts"
            linked_parent = root / "receipts"
            real_parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            result = run_mirror_parabricks_receipt_writer(linked_parent / "receipt.json")

            self.assertEqual([], list(real_parent.iterdir()))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("parent may not be a symlink", result.stderr)

    def test_parabricks_mirror_receipt_writer_uses_single_use_temporary_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".receipt.json.tmp").write_text("stale\n", encoding="utf-8")

            result = run_mirror_parabricks_receipt_writer(root / "receipt.json")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Temporary Parabricks mirror receipt already exists", result.stderr)

    def test_parabricks_mirror_receipt_writer_writes_real_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "receipt.json"

            result = run_mirror_parabricks_receipt_writer(path)

            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("parabricks_mirror_receipt", payload["manifest_type"])
        self.assertEqual("linux/amd64", payload["source"]["platform"])
        self.assertEqual("b" * 40, payload["diana_omics"]["git_commit"])

    def test_parabricks_mirror_image_extends_base_with_diana_runtime(self) -> None:
        dockerfile = PARABRICKS_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("ARG PARABRICKS_BASE_IMAGE", dockerfile)
        self.assertIn("FROM ${PARABRICKS_BASE_IMAGE}", dockerfile)
        self.assertIn("awscli", dockerfile)
        self.assertIn("bcftools", dockerfile)
        self.assertIn("openjdk-17-jre-headless", dockerfile)
        self.assertIn('aws_path="$(command -v aws)"', dockerfile)
        self.assertIn("/opt/diana-aws/bin/aws", dockerfile)
        self.assertIn("COPY . /opt/diana-omics", dockerfile)
        self.assertIn("bcftools --version", dockerfile)
        self.assertIn("java -version", dockerfile)
        self.assertIn("java_major=", dockerfile)
        self.assertIn('if [ -z "${java_major}" ] || [ "${java_major}" -lt 17 ]', dockerfile)
        self.assertIn("Java 17+ is required in the Diana Parabricks runtime", dockerfile)
        self.assertIn("command -v pbrun", dockerfile)
        self.assertIn("python3 -m diana_omics --help", dockerfile)

    def test_parabricks_mirror_context_excludes_local_scratch_and_generated_secrets(self) -> None:
        dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")

        for pattern in (
            ".DS_Store",
            ".claude/",
            ".codex-tmp/",
            ".next/",
            ".nextflow/",
            ".nextflow.log*",
            ".ipynb_checkpoints/",
            ".venv/",
            ".mypy_cache/",
            ".pytest_cache/",
            ".ruff_cache/",
            "node_modules/",
            "apps/data/dist/",
            ".vercel/",
            "tmp/",
            ".env",
            ".env.*",
            "**/.env",
            "**/.env.*",
            "!**/.env.example",
            "data/raw/**",
            "data/processed/**",
            "results/**",
            "!results/full_wes_benchmark/",
            "!results/full_wes_benchmark/full_wes_benchmark_summary.json",
            "infra/aws/.terraform/**",
            "infra/aws/terraform.tfstate.d/**",
            "infra/aws/*.tfstate",
            "infra/aws/*.tfstate.*",
            "infra/aws/*.tfplan",
            "infra/aws/nextflow.aws.json",
            "infra/aws/nextflow.aws.*.json",
        ):
            self.assertIn(pattern, dockerignore)

    def test_gpu_smoke_is_documented_as_placement_only(self) -> None:
        readme = AWS_README.read_text(encoding="utf-8")
        next_gen = NEXT_GEN_DOC.read_text(encoding="utf-8")

        self.assertIn("Diana Parabricks runtime", readme)
        self.assertIn("aws --version", readme)
        self.assertIn("python3 -m diana_omics --help", readme)
        self.assertIn("nf:aws:phase3-wgs-fast:gpu-smoke", readme)
        self.assertIn("does not run Parabricks MutectCaller", readme)
        self.assertIn("nf:aws:phase3-wgs-fast:gpu-smoke", next_gen)


if __name__ == "__main__":
    unittest.main()
