from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import verify_phase3_fast_aws_execute as verify
from diana_omics.utils import write_json


def passed_smoke_result() -> dict:
    return {
        "schema": "phase3_wgs_fast_gpu_smoke.v1",
        "status": "passed",
        "expectedGpuCount": 8,
        "observedGpuCount": 8,
        "requiredGpuName": "H200",
        "nvidiaSmiCsv": "nvidia-smi-gpus.csv",
    }


def write_smoke_result(root: Path, payload: dict | None = None, *, csv: str | None = None) -> Path:
    path = root / "gpu_smoke.json"
    write_json(path, payload or passed_smoke_result())
    (root / "nvidia-smi-gpus.csv").write_text(
        csv
        or "\n".join(f"{index}, NVIDIA H200, GPU-00000000-0000-0000-0000-{index:012d}" for index in range(8))
        + "\n",
        encoding="utf-8",
    )
    return path


class Phase3FastAwsExecutePreflightTests(unittest.TestCase):
    def test_validates_passed_eight_h200_smoke_result(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(root)

            summary = verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root)

        self.assertEqual(
            {
                "expected_gpu_count": 8,
                "observed_gpu_count": 8,
                "required_gpu_name": "H200",
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
                verify.validate_gpu_smoke_result(stubbed, csv_root=root)

            underallocated = passed_smoke_result()
            underallocated["observedGpuCount"] = 4
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "exactly 8"):
                verify.validate_gpu_smoke_result(underallocated, csv_root=root)

    def test_rejects_smoke_result_without_h200_csv_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(
                root,
                csv="\n".join(f"{index}, NVIDIA A100, GPU-00000000-0000-0000-0000-{index:012d}" for index in range(8))
                + "\n",
            )

            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "not an H200"):
                verify.validate_gpu_smoke_result(passed_smoke_result(), csv_root=root)

    def test_rejects_csv_path_traversal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_smoke_result(root)
            payload = passed_smoke_result()
            payload["nvidiaSmiCsv"] = "../nvidia-smi-gpus.csv"

            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "sibling basename"):
                verify.validate_gpu_smoke_result(payload, csv_root=root)

    def test_environment_loader_requires_reviewed_gpu_smoke_result(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(verify.Phase3FastExecuteError, "PHASE3_FAST_GPU_SMOKE_RESULT"):
                verify.load_gpu_smoke_result_from_environment()

    def test_environment_loader_reads_reviewed_gpu_smoke_result(self) -> None:
        with TemporaryDirectory() as tmp:
            path = write_smoke_result(Path(tmp))

            with patch.dict("os.environ", {"PHASE3_FAST_GPU_SMOKE_RESULT": str(path)}, clear=False):
                summary, loaded_path = verify.load_gpu_smoke_result_from_environment()

        self.assertEqual(path, loaded_path)
        self.assertEqual(8, summary["observed_gpu_count"])


if __name__ == "__main__":
    unittest.main()
