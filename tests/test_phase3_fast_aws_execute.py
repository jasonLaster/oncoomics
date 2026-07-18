from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import verify_phase3_fast_aws_execute as verify
from diana_omics.utils import write_json

PARABRICKS_CONTAINER = "172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@sha256:" + "a" * 64
PARABRICKS_REPOSITORY = "172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks"


def expected_gpu_params() -> dict:
    return {
        "aws_region": "us-east-2",
        "aws_gpu_queue": "diana-omics-prod-use2-gpu-p5en",
        "parabricks_container": PARABRICKS_CONTAINER,
    }


def parabricks_mirror_receipt() -> dict:
    return {
        "schema_version": 1,
        "manifest_type": "parabricks_mirror_receipt",
        "generated_at": "2026-07-18T00:00:00+00:00",
        "source": {
            "image": "nvcr.io/nvidia/clara/parabricks@sha256:" + "b" * 64,
            "digest": "sha256:" + "b" * 64,
            "platform": "linux/amd64",
        },
        "destination": {
            "region": "us-east-2",
            "repository": PARABRICKS_REPOSITORY,
            "tag": "sha256-" + "b" * 64 + "-diana-" + "c" * 12,
            "digest": "sha256:" + "a" * 64,
            "parabricks_container": PARABRICKS_CONTAINER,
        },
        "diana_omics": {
            "git_commit": "c" * 40,
            "dockerfile_sha256": "sha256:" + "d" * 64,
        },
    }


def current_diana_source() -> dict:
    return {
        "dockerfile_sha256": "sha256:" + "d" * 64,
        "git_commit": "c" * 40,
    }


def passed_smoke_result() -> dict:
    return {
        "schema": "phase3_wgs_fast_gpu_smoke.v1",
        "status": "passed",
        "awsRegion": "us-east-2",
        "awsGpuQueue": "diana-omics-prod-use2-gpu-p5en",
        "parabricksContainer": PARABRICKS_CONTAINER,
        "expectedGpuCount": 8,
        "observedGpuCount": 8,
        "requiredGpuName": "H200",
        "nvidiaSmiCsv": "nvidia-smi-gpus.csv",
        "awsCliVersionTxt": "aws-cli-version.txt",
        "bcftoolsVersionCommand": "bcftools --version",
        "bcftoolsVersionTxt": "bcftools-version.txt",
        "dianaOmicsCliTxt": "diana-omics-cli.txt",
        "javaVersionCommand": "java -version",
        "javaVersionTxt": "java-version.txt",
        "scratchReadinessJson": "scratch-readiness.json",
        "parabricksPreponSmokeCommand": "pbrun prepon",
        "parabricksPreponSmokeTxt": "parabricks-prepon-smoke.txt",
        "parabricksVersionCommand": "pbrun version",
        "parabricksVersionTxt": "parabricks-version.txt",
    }


def write_smoke_result(
    root: Path,
    payload: dict | None = None,
    *,
    csv: str | None = None,
    aws_version: str | None = "aws-cli/2.15.0\n",
    bcftools_version: str | None = "bcftools 1.17\n",
    diana_omics_cli: str | None = "verify:phase3-fast-gpu-smoke\n",
    java_version: str | None = 'openjdk version "17.0.15"\n',
    parabricks_prepon_smoke: str | None = "command: pbrun prepon\n",
    parabricks_version: str | None = "Parabricks v4.5.1-1\n",
    scratch_readiness: dict | None = None,
) -> Path:
    path = root / "gpu_smoke.json"
    write_json(path, payload or passed_smoke_result())
    (root / "nvidia-smi-gpus.csv").write_text(
        csv or "\n".join(f"{index}, NVIDIA H200, GPU-00000000-0000-0000-0000-{index:012d}" for index in range(8)) + "\n",
        encoding="utf-8",
    )
    if parabricks_version is not None:
        (root / "parabricks-version.txt").write_text(parabricks_version, encoding="utf-8")
    else:
        (root / "parabricks-version.txt").unlink(missing_ok=True)
    if java_version is not None:
        (root / "java-version.txt").write_text(java_version, encoding="utf-8")
    else:
        (root / "java-version.txt").unlink(missing_ok=True)
    if bcftools_version is not None:
        (root / "bcftools-version.txt").write_text(bcftools_version, encoding="utf-8")
    else:
        (root / "bcftools-version.txt").unlink(missing_ok=True)
    if aws_version is not None:
        (root / "aws-cli-version.txt").write_text(aws_version, encoding="utf-8")
    else:
        (root / "aws-cli-version.txt").unlink(missing_ok=True)
    if diana_omics_cli is not None:
        (root / "diana-omics-cli.txt").write_text(diana_omics_cli, encoding="utf-8")
    else:
        (root / "diana-omics-cli.txt").unlink(missing_ok=True)
    if parabricks_prepon_smoke is not None:
        (root / "parabricks-prepon-smoke.txt").write_text(parabricks_prepon_smoke, encoding="utf-8")
    else:
        (root / "parabricks-prepon-smoke.txt").unlink(missing_ok=True)
    write_json(
        root / "scratch-readiness.json",
        scratch_readiness
        or {
            "schema": "diana_p5en_nvme_scratch.v1",
            "mountPoint": "/scratch",
            "mountedSource": "/dev/md0",
            "fileSystem": "xfs",
            "instanceStoreDeviceCount": 8,
            "probePath": "/scratch/diana/phase3_wgs_fast/gpu_smoke/scratch-probe.txt",
            "probeStatus": "passed",
        },
    )
    return path


def write_bytes(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)


class Phase3FastAwsExecutePreflightTests(unittest.TestCase):
    def test_validates_passed_eight_h200_smoke_result(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(root)

            summary = verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

        self.assertEqual(
            {
                "aws_cli_version_txt": "aws-cli-version.txt",
                "aws_gpu_queue": "diana-omics-prod-use2-gpu-p5en",
                "aws_region": "us-east-2",
                "bcftools_version_command": "bcftools --version",
                "bcftools_version_txt": "bcftools-version.txt",
                "diana_omics_cli_txt": "diana-omics-cli.txt",
                "expected_gpu_count": 8,
                "java_version_command": "java -version",
                "java_version_txt": "java-version.txt",
                "observed_gpu_count": 8,
                "parabricks_container": PARABRICKS_CONTAINER,
                "parabricks_prepon_smoke_command": "pbrun prepon",
                "parabricks_prepon_smoke_txt": "parabricks-prepon-smoke.txt",
                "parabricks_version_command": "pbrun version",
                "parabricks_version_txt": "parabricks-version.txt",
                "required_gpu_name": "H200",
                "scratch_instance_store_device_count": 8,
                "scratch_readiness_json": "scratch-readiness.json",
                "status": "passed",
            },
            summary,
        )

    def test_rejects_stubbed_or_underallocated_smoke_result(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(root)

            stubbed = passed_smoke_result()
            stubbed["status"] = "stubbed"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "passed"):
                verify.validate_gpu_smoke_result(stubbed, csv_root=root, expected_params=expected_gpu_params())

            underallocated = passed_smoke_result()
            underallocated["observedGpuCount"] = 4
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "exactly 8"):
                verify.validate_gpu_smoke_result(underallocated, csv_root=root, expected_params=expected_gpu_params())

    def test_rejects_smoke_result_without_h200_csv_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(
                root,
                csv="\n".join(f"{index}, NVIDIA A100, GPU-00000000-0000-0000-0000-{index:012d}" for index in range(8)) + "\n",
            )

            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "not an H200"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

    def test_rejects_smoke_result_without_distinct_gpu_csv_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(
                root,
                csv="\n".join("0, NVIDIA H200, GPU-00000000-0000-0000-0000-000000000000" for _ in range(8)) + "\n",
            )

            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "distinct GPU indexes"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(
                root,
                csv="\n".join(f"{index}, NVIDIA H200, GPU-duplicate" for index in range(8)) + "\n",
            )

            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "unique GPU UUIDs"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

    def test_rejects_unbound_or_stale_queue_and_image_smoke_result(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(root)

            legacy = passed_smoke_result()
            del legacy["awsGpuQueue"]
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "awsGpuQueue"):
                verify.validate_gpu_smoke_result(legacy, csv_root=root, expected_params=expected_gpu_params())

            stale_queue = passed_smoke_result()
            stale_queue["awsGpuQueue"] = "diana-omics-prod-use2-gpu-test"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "awsGpuQueue"):
                verify.validate_gpu_smoke_result(stale_queue, csv_root=root, expected_params=expected_gpu_params())

            stale_image = passed_smoke_result()
            stale_image["parabricksContainer"] = "172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@sha256:" + "b" * 64
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "parabricksContainer"):
                verify.validate_gpu_smoke_result(stale_image, csv_root=root, expected_params=expected_gpu_params())

    def test_rejects_smoke_result_without_parabricks_startup_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(root, parabricks_version=None)
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "Parabricks version"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root, parabricks_version="")
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "non-empty"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root, parabricks_version="tool v1.0\n")
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "Parabricks or pbrun"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            path_traversal = passed_smoke_result()
            path_traversal["parabricksVersionTxt"] = "../parabricks-version.txt"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "sibling basename"):
                verify.validate_gpu_smoke_result(path_traversal, csv_root=root, expected_params=expected_gpu_params())

            wrong_command = passed_smoke_result()
            wrong_command["parabricksVersionCommand"] = "pbrun mutectcaller"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "pbrun version"):
                verify.validate_gpu_smoke_result(wrong_command, csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root, parabricks_prepon_smoke=None)
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "Parabricks prepon smoke"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            prepon_path_traversal = passed_smoke_result()
            prepon_path_traversal["parabricksPreponSmokeTxt"] = "../parabricks-prepon-smoke.txt"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "parabricksPreponSmokeTxt"):
                verify.validate_gpu_smoke_result(prepon_path_traversal, csv_root=root, expected_params=expected_gpu_params())

            wrong_prepon_command = passed_smoke_result()
            wrong_prepon_command["parabricksPreponSmokeCommand"] = "pbrun version"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "pbrun prepon"):
                verify.validate_gpu_smoke_result(wrong_prepon_command, csv_root=root, expected_params=expected_gpu_params())

    def test_rejects_smoke_result_without_p5en_scratch_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(root)

            invalid = passed_smoke_result()
            invalid["scratchReadinessJson"] = "../scratch-readiness.json"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "scratchReadinessJson"):
                verify.validate_gpu_smoke_result(invalid, csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root, scratch_readiness={"schema": "diana_p5en_nvme_scratch.v1"})
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "/scratch"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(
                root,
                scratch_readiness={
                    "schema": "diana_p5en_nvme_scratch.v1",
                    "mountPoint": "/scratch",
                    "mountedSource": "/dev/xvda",
                    "fileSystem": "xfs",
                    "instanceStoreDeviceCount": 8,
                    "probeStatus": "passed",
                },
            )
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "NVMe instance storage"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(
                root,
                scratch_readiness={
                    "schema": "diana_p5en_nvme_scratch.v1",
                    "mountPoint": "/scratch",
                    "mountedSource": "/dev/md0",
                    "fileSystem": "xfs",
                    "instanceStoreDeviceCount": 4,
                    "probeStatus": "passed",
                },
            )
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "exactly 8"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

    def test_rejects_smoke_result_without_filter_mutect_runtime_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(root, java_version=None)
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "Java version"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root, java_version='openjdk version "11.0.24"\n')
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "Java 17"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            java_path_traversal = passed_smoke_result()
            java_path_traversal["javaVersionTxt"] = "../java-version.txt"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "javaVersionTxt"):
                verify.validate_gpu_smoke_result(java_path_traversal, csv_root=root, expected_params=expected_gpu_params())

            wrong_java_command = passed_smoke_result()
            wrong_java_command["javaVersionCommand"] = "java --help"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "java -version"):
                verify.validate_gpu_smoke_result(wrong_java_command, csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root, bcftools_version=None)
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "bcftools version"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root, bcftools_version="samtools 1.17\n")
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "identify bcftools"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            bcftools_path_traversal = passed_smoke_result()
            bcftools_path_traversal["bcftoolsVersionTxt"] = "../bcftools-version.txt"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "bcftoolsVersionTxt"):
                verify.validate_gpu_smoke_result(bcftools_path_traversal, csv_root=root, expected_params=expected_gpu_params())

            wrong_bcftools_command = passed_smoke_result()
            wrong_bcftools_command["bcftoolsVersionCommand"] = "bcftools index"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "bcftools --version"):
                verify.validate_gpu_smoke_result(wrong_bcftools_command, csv_root=root, expected_params=expected_gpu_params())

    def test_rejects_smoke_result_without_diana_runtime_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(root, aws_version=None)
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "AWS CLI version"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root, aws_version="")
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "AWS CLI version output must be non-empty"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root, aws_version="python/3.11\n")
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "identify aws-cli"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            aws_path_traversal = passed_smoke_result()
            aws_path_traversal["awsCliVersionTxt"] = "../aws-cli-version.txt"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "awsCliVersionTxt"):
                verify.validate_gpu_smoke_result(aws_path_traversal, csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root, diana_omics_cli=None)
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "Diana omics CLI"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root, diana_omics_cli="usage only\n")
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "verify:phase3-fast-gpu-smoke"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            diana_path_traversal = passed_smoke_result()
            diana_path_traversal["dianaOmicsCliTxt"] = "../diana-omics-cli.txt"
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "dianaOmicsCliTxt"):
                verify.validate_gpu_smoke_result(diana_path_traversal, csv_root=root, expected_params=expected_gpu_params())

    def test_rejects_csv_path_traversal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(root)
            payload = passed_smoke_result()
            payload["nvidiaSmiCsv"] = "../nvidia-smi-gpus.csv"

            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "sibling basename"):
                verify.validate_gpu_smoke_result(payload, csv_root=root, expected_params=expected_gpu_params())

    def test_decodes_smoke_text_artifacts_with_replacement(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(root)
            write_bytes(root / "nvidia-smi-gpus.csv", b"0, NVIDIA H200, GPU-0\xab\n")

            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "GPU count"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root, expected_params=expected_gpu_params())

            write_smoke_result(root)
            write_bytes(root / "diana-omics-cli.txt", b"verify:phase3-fast-gpu-smoke\xab\n")

            summary = verify.validate_gpu_smoke_result(
                passed_smoke_result(),
                csv_root=root,
                expected_params=expected_gpu_params(),
            )

        self.assertEqual("diana-omics-cli.txt", summary["diana_omics_cli_txt"])

    def test_environment_loader_requires_reviewed_gpu_smoke_result(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "PHASE3_FAST_GPU_SMOKE_RESULT"):
                verify.load_gpu_smoke_result_from_environment(expected_params=expected_gpu_params())

    def test_environment_loader_reads_reviewed_gpu_smoke_result(self) -> None:
        with TemporaryDirectory() as tmp:
            path = write_smoke_result(Path(tmp))

            with patch.dict("os.environ", {"PHASE3_FAST_GPU_SMOKE_RESULT": str(path)}, clear=False):
                summary, loaded_path = verify.load_gpu_smoke_result_from_environment(expected_params=expected_gpu_params())

        self.assertEqual(path, loaded_path)
        self.assertEqual(8, summary["observed_gpu_count"])

    def test_environment_loader_rejects_gpu_smoke_below_symlinked_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-smoke"
            linked_parent = root / "linked-smoke"
            real_parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            path = write_smoke_result(linked_parent)

            with patch.dict("os.environ", {"PHASE3_FAST_GPU_SMOKE_RESULT": str(path)}, clear=False):
                with self.assertRaisesRegex(verify.Phase3FastExecuteError, "parent may not be a symlink"):
                    verify.load_gpu_smoke_result_from_environment(expected_params=expected_gpu_params())

    def test_rejects_smoke_support_file_below_symlinked_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-smoke"
            linked_parent = root / "linked-smoke"
            real_parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            write_smoke_result(linked_parent)

            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "parent may not be a symlink"):
                verify.validate_gpu_smoke_result(
                    passed_smoke_result(),
                    csv_root=linked_parent,
                    expected_params=expected_gpu_params(),
                )

    def test_rejects_stale_parabricks_mirror_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "parabricks_mirror_receipt.json"
            stale = parabricks_mirror_receipt()
            stale["destination"]["parabricks_container"] = PARABRICKS_REPOSITORY + "@sha256:" + "c" * 64
            write_json(path, stale)

            with patch.dict("os.environ", {"PARABRICKS_MIRROR_RECEIPT": str(path)}, clear=False):
                with self.assertRaisesRegex(verify.Phase3FastExecuteError, "Parabricks mirror receipt"):
                    verify.load_mirror_receipt_from_environment(expected_params=expected_gpu_params())

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.mirror_receipt.current_diana_source")
    def test_rejects_parabricks_mirror_receipt_from_stale_diana_source(self, current_source) -> None:
        current_source.return_value = current_diana_source()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "parabricks_mirror_receipt.json"
            stale = parabricks_mirror_receipt()
            stale["diana_omics"]["git_commit"] = "e" * 40
            stale["destination"]["tag"] = "sha256-" + "b" * 64 + "-diana-" + "e" * 12
            write_json(path, stale)

            with patch.dict("os.environ", {"PARABRICKS_MIRROR_RECEIPT": str(path)}, clear=False):
                with self.assertRaisesRegex(verify.Phase3FastExecuteError, "current Diana Git HEAD"):
                    verify.load_mirror_receipt_from_environment(expected_params=expected_gpu_params())

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.mirror_receipt.current_diana_source")
    def test_rejects_parabricks_mirror_receipt_from_stale_dockerfile(self, current_source) -> None:
        current_source.return_value = current_diana_source()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "parabricks_mirror_receipt.json"
            stale = parabricks_mirror_receipt()
            stale["diana_omics"]["dockerfile_sha256"] = "sha256:" + "e" * 64
            write_json(path, stale)

            with patch.dict("os.environ", {"PARABRICKS_MIRROR_RECEIPT": str(path)}, clear=False):
                with self.assertRaisesRegex(verify.Phase3FastExecuteError, "current Diana Parabricks Dockerfile"):
                    verify.load_mirror_receipt_from_environment(expected_params=expected_gpu_params())

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.mirror_receipt.current_diana_source")
    def test_environment_loader_reads_matching_parabricks_mirror_receipt(self, current_source) -> None:
        current_source.return_value = current_diana_source()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "parabricks_mirror_receipt.json"
            write_json(path, parabricks_mirror_receipt())

            with patch.dict("os.environ", {"PARABRICKS_MIRROR_RECEIPT": str(path)}, clear=False):
                summary, loaded_path = verify.load_mirror_receipt_from_environment(expected_params=expected_gpu_params())

        self.assertEqual(path, loaded_path)
        self.assertEqual(PARABRICKS_CONTAINER, summary["parabricks_container"])

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.mirror_receipt.load_receipt_from_environment")
    def test_environment_loader_requires_explicit_reviewed_parabricks_mirror_receipt(self, load_receipt) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "PARABRICKS_MIRROR_RECEIPT"):
                verify.load_mirror_receipt_from_environment(expected_params=expected_gpu_params())

        load_receipt.assert_not_called()

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.load_mirror_receipt_from_environment")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.load_gpu_batch_compute_environment")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.validate_gpu_batch_job_queue")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.load_gpu_batch_job_queue")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.validate_gpu_smoke_params")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.load_params_from_environment")
    def test_execute_main_stops_before_mirror_when_p5en_queue_is_not_ready(
        self,
        load_params,
        validate_params,
        load_queue,
        validate_queue,
        load_compute_environment,
        load_mirror,
    ) -> None:
        load_params.return_value = ({}, Path("infra/aws/nextflow.aws.use2.json"))
        validate_params.return_value = expected_gpu_params()
        load_queue.return_value = {"jobQueueName": "diana-omics-prod-use2-gpu-p5en"}
        validate_queue.side_effect = verify.gpu_smoke.GpuSmokeConfigError("P5en Batch queue is not ready")

        with self.assertRaisesRegex(SystemExit, "P5en Batch queue is not ready"):
            verify.main()

        load_queue.assert_called_once_with(queue="diana-omics-prod-use2-gpu-p5en", region="us-east-2")
        load_compute_environment.assert_not_called()
        load_mirror.assert_not_called()

    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.load_mirror_receipt_from_environment")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.load_gpu_smoke_result_from_environment")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.load_parabricks_mirror_image_digest")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.load_running_on_demand_p_vcpus")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.validate_gpu_batch_compute_environment")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.load_gpu_batch_compute_environment")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.validate_gpu_batch_job_queue")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.load_gpu_batch_job_queue")
    @patch("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute.gpu_smoke.load_params_from_environment")
    def test_execute_main_rechecks_mirrored_parabricks_digest(
        self,
        load_params,
        load_queue,
        validate_queue,
        load_compute_environment,
        validate_compute_environment,
        load_quota,
        load_image,
        load_smoke,
        load_mirror,
    ) -> None:
        load_params.return_value = (
            {
                "aws_region": "us-east-2",
                "aws_gpu_queue": "diana-omics-prod-use2-gpu-p5en",
                "aws_job_role": "arn:aws:iam::172630973301:role/diana-omics-prod-use2-batch-job",
                "aws_logs_group": "/aws/batch/diana-omics-prod-use2",
                "aws_private_results_dir": "s3://diana-omics-private-results-172630973301-us-east-2/runs",
                "aws_workdir": "s3://diana-omics-work-172630973301-us-east-2/work",
                "batch_gpu_p5en_instance_types": ["p5en.48xlarge"],
                "gpu_p5en_max_vcpus": 384,
                "parabricks_container": ("172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@sha256:" + "a" * 64),
                "parabricks_mirror_repository": ("172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks"),
                "phase3_fast_cache_kms_key_arn": ("arn:aws:kms:us-east-2:172630973301:key/12345678-abcd-1234-abcd-123456789abc"),
                "phase3_fast_cache_prefix": ("s3://diana-omics-private-results-172630973301-us-east-2/phase3-fast-cache/wgs-v2"),
                "phase3_fast_cache_region": "us-east-2",
            },
            Path("infra/aws/nextflow.aws.use2.json"),
        )
        load_queue.return_value = {"jobQueueName": "diana-omics-prod-use2-gpu-p5en"}
        validate_queue.return_value = {
            "compute_environment": ("arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"),
            "job_queue": "diana-omics-prod-use2-gpu-p5en",
            "status": "ready",
        }
        load_compute_environment.return_value = {
            "computeEnvironmentArn": ("arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand")
        }
        validate_compute_environment.return_value = {
            "compute_environment": ("arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"),
            "instance_types": ["p5en.48xlarge"],
            "max_vcpus": 384,
            "status": "ready",
        }
        load_quota.return_value = 384.0
        load_image.return_value = "sha256:" + "a" * 64
        load_smoke.return_value = ({"observed_gpu_count": 8}, Path("gpu_smoke.json"))
        load_mirror.return_value = (
            {
                "parabricks_container": PARABRICKS_CONTAINER,
                "tag": "sha256-" + "b" * 64 + "-diana-" + "c" * 12,
            },
            Path("parabricks_mirror_receipt.json"),
        )

        verify.main()

        load_queue.assert_called_once_with(queue="diana-omics-prod-use2-gpu-p5en", region="us-east-2")
        validate_queue.assert_called_once_with(
            {"jobQueueName": "diana-omics-prod-use2-gpu-p5en"},
            expected_queue="diana-omics-prod-use2-gpu-p5en",
        )
        load_compute_environment.assert_called_once_with(
            compute_environment=("arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"),
            region="us-east-2",
        )
        validate_compute_environment.assert_called_once_with(
            {"computeEnvironmentArn": ("arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand")},
            expected_compute_environment=(
                "arn:aws:batch:us-east-2:172630973301:compute-environment/diana-omics-prod-use2-gpu-p5en-ondemand"
            ),
        )
        load_mirror.assert_called_once()
        load_image.assert_called_once_with(
            parabricks_container=PARABRICKS_CONTAINER,
            region="us-east-2",
            expected_tag="sha256-" + "b" * 64 + "-diana-" + "c" * 12,
        )
        load_smoke.assert_called_once()


if __name__ == "__main__":
    unittest.main()
