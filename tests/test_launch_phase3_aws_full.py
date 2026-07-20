from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/launch_phase3_aws_full.sh"


def write_fake_nextflow(directory: Path) -> Path:
    executable = directory / "nextflow"
    executable.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$@\" > \"$FAKE_NEXTFLOW_ARGV\"\n"
        "exit \"${FAKE_NEXTFLOW_EXIT:-0}\"\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def write_fake_aws(directory: Path) -> Path:
    executable = directory / "aws"
    executable.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$@\" > \"$FAKE_AWS_ARGV\"\n"
        "printf '{\"Item\":{\"estimated_daily_ec2_usd\":{\"N\":\"%s\"}}}\\n' "
        "\"${FAKE_AWS_SPEND:-0}\"\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def write_cost_guard_config(directory: Path) -> Path:
    config = directory / "nextflow.aws.json"
    config.write_text(
        json.dumps(
            {
                "aws_region": "us-east-1",
                "daily_cost_guard_ledger": "diana-omics-prod-use1-daily-cost-guard-ledger",
                "daily_cost_guard_limit_usd": "200",
                "daily_cost_guard_live_stop_usd": "160",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return config


class Phase3AwsFullLauncherTests(unittest.TestCase):
    def test_default_legacy_phase3_wgs_requires_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            result = subprocess.run(
                [
                    "bash",
                    str(LAUNCHER),
                    "legacy-full",
                    str(run_dir),
                    "container:tag",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 64)
            self.assertIn("Refusing to launch", result.stderr)
            self.assertIn("phase3_wgs_fast", result.stderr)
            self.assertFalse(run_dir.exists())

    def test_monolith_workflow_requires_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = subprocess.run(
                [
                    "bash",
                    str(LAUNCHER),
                    "legacy-monolith",
                    str(root / "run"),
                    "container:tag",
                ],
                cwd=root,
                env={**os.environ, "PHASE3_WORKFLOW": "phase3_wgs_monolith"},
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 64)
            self.assertIn("legacy full-source Phase 3 WGS", result.stderr)

    def test_explicit_legacy_override_reaches_nextflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            write_fake_nextflow(bin_dir)
            write_fake_aws(bin_dir)
            argv = root / "nextflow.argv"
            config = write_cost_guard_config(root)
            run_dir = root / "run"

            env = {
                **os.environ,
                "ALLOW_LEGACY_PHASE3_AWS_FULL": "YES",
                "DIANA_AWS_CONFIG": str(config),
                "FAKE_AWS_ARGV": str(root / "aws.argv"),
                "FAKE_NEXTFLOW_ARGV": str(argv),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            result = subprocess.run(
                [
                    "bash",
                    str(LAUNCHER),
                    "legacy-full",
                    str(run_dir),
                    "container:tag",
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual((run_dir / "nextflow.exit").read_text(), "0\n")
            self.assertIn("--workflow\nphase3_wgs\n", argv.read_text())
            self.assertIn("--allow_legacy_phase3_cpu_full\ntrue\n", argv.read_text())

    def test_explicit_legacy_override_still_fails_before_nextflow_when_cost_guard_is_spent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            write_fake_nextflow(bin_dir)
            write_fake_aws(bin_dir)
            config = write_cost_guard_config(root)
            run_dir = root / "run"

            env = {
                **os.environ,
                "ALLOW_LEGACY_PHASE3_AWS_FULL": "YES",
                "DIANA_AWS_CONFIG": str(config),
                "FAKE_AWS_ARGV": str(root / "aws.argv"),
                "FAKE_AWS_SPEND": "160",
                "FAKE_NEXTFLOW_ARGV": str(root / "nextflow.argv"),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            result = subprocess.run(
                [
                    "bash",
                    str(LAUNCHER),
                    "legacy-full",
                    str(run_dir),
                    "container:tag",
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 64)
            self.assertIn("refusing AWS Batch submission", result.stderr)
            self.assertFalse(run_dir.exists())
            self.assertFalse((root / "nextflow.argv").exists())

    def test_distributed_scatter_workflow_does_not_need_legacy_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            write_fake_nextflow(bin_dir)
            write_fake_aws(bin_dir)
            argv = root / "nextflow.argv"
            config = write_cost_guard_config(root)

            env = {
                **os.environ,
                "DIANA_AWS_CONFIG": str(config),
                "FAKE_AWS_ARGV": str(root / "aws.argv"),
                "FAKE_NEXTFLOW_ARGV": str(argv),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "PHASE3_WORKFLOW": "phase3_wgs_align_scatter",
            }
            result = subprocess.run(
                [
                    "bash",
                    str(LAUNCHER),
                    "scatter-full",
                    str(root / "run"),
                    "container:tag",
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn("--workflow\nphase3_wgs_align_scatter\n", argv.read_text())


if __name__ == "__main__":
    unittest.main()
