from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_TF = ROOT / "infra/aws/main.tf"
VARIABLES_TF = ROOT / "infra/aws/variables.tf"
OUTPUTS_TF = ROOT / "infra/aws/outputs.tf"
NEXTFLOW_CONFIG = ROOT / "nextflow.config"
AWS_README = ROOT / "infra/aws/README.md"
NEXT_GEN_DOC = ROOT / "docs/operations/next-generation-fast-rerun.md"


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

    def test_nextflow_params_export_gpu_queue_and_unselected_parabricks_image(self) -> None:
        text = MAIN_TF.read_text(encoding="utf-8")

        self.assertIn("aws_gpu_queue           = aws_batch_job_queue.gpu_p5en.name", text)
        self.assertIn("parabricks_container    = var.parabricks_container", text)

    def test_gpu_defaults_match_requested_quota_and_leave_image_unpinned(self) -> None:
        text = VARIABLES_TF.read_text(encoding="utf-8")

        self.assertIn('variable "gpu_p5en_max_vcpus"', text)
        self.assertIn("default     = 384", text)
        self.assertIn('default     = ["p5en.48xlarge"]', text)
        self.assertIn('variable "parabricks_container"', text)
        self.assertIn('default     = ""', text)

    def test_outputs_and_nextflow_profile_expose_gpu_queue(self) -> None:
        outputs = OUTPUTS_TF.read_text(encoding="utf-8")
        nextflow = NEXTFLOW_CONFIG.read_text(encoding="utf-8")

        self.assertIn('output "gpu_p5en_compute_environment"', outputs)
        self.assertIn('output "gpu_p5en_queue"', outputs)
        self.assertIn("aws_gpu_queue = null", nextflow)
        self.assertIn("parabricks_container = null", nextflow)
        self.assertIn("awsbatch_gpu", nextflow)
        self.assertIn("process.queue = params.aws_gpu_queue", nextflow)
        self.assertIn("process.container = params.parabricks_container", nextflow)

    def test_gpu_smoke_is_documented_as_placement_only(self) -> None:
        readme = AWS_README.read_text(encoding="utf-8")
        next_gen = NEXT_GEN_DOC.read_text(encoding="utf-8")

        self.assertIn("nf:aws:phase3-wgs-fast:gpu-smoke", readme)
        self.assertIn("does not run Parabricks MutectCaller", readme)
        self.assertIn("nf:aws:phase3-wgs-fast:gpu-smoke", next_gen)


if __name__ == "__main__":
    unittest.main()
