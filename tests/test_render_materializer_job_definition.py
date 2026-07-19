#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SPEC = importlib.util.spec_from_file_location(
    "render_materializer_job_definition",
    SCRIPT_DIR / "render_materializer_job_definition.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class RenderMaterializerJobDefinitionTests(unittest.TestCase):
    def args(self, **overrides):
        base = (
            "s3://diana-omics-private-results-172630973301-us-east-1/"
            "runs/subject01/unit"
        )
        values = {
            "script_uri": base + "/preparation/scripts/materializer.py",
            "script_version_id": "exact-script-version",
            "script_sha256": "a" * 64,
            "source_vcf_uri": base + "/deterministic/artifacts/final.vcf.gz",
            "source_vcf_index_uri": base + "/deterministic/artifacts/final.vcf.gz.tbi",
            "source_matrix_uri": base + "/deterministic/artifacts/sbs96.csv",
            "reference_fasta_uri": base + "/deterministic/reference/reference.fa",
            "reference_fai_uri": base + "/deterministic/reference/reference.fa.fai",
            "reference_fasta_sha256": "b" * 64,
            "reference_fai_sha256": "c" * 64,
            "destination_prefix": base + "/deterministic/final",
            "receipt_prefix": (
                base
                + "/deterministic/provenance/crosscheck-materialization-receipts"
            ),
            "kms_key_arn": (
                "arn:aws:kms:us-east-1:172630973301:key/"
                "45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
            ),
            "image": (
                "172630973301.dkr.ecr.us-east-1.amazonaws.com/"
                "diana-omics@sha256:"
                + "d" * 64
            ),
            "job_role_arn": "arn:aws:iam::172630973301:role/diana-omics-prod-use1-batch-job",
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_render_pins_script_version_and_all_source_hashes_are_runtime_parameters(self) -> None:
        payload = module.render(self.args())

        command = payload["containerProperties"]["command"]
        shell = command[2]
        self.assertIn("s3api get-object", shell)
        self.assertIn("--version-id exact-script-version", shell)
        self.assertIn('test "$actual" = ' + "a" * 64, shell)
        self.assertIn('--source-vcf-sha256 "$4"', shell)
        self.assertIn('--source-matrix-sha256 "$6"', shell)
        self.assertIn("--receipt-prefix", shell)
        self.assertIn("--receipt-anchor-output", shell)
        self.assertNotIn("--receipt-uri", shell)
        self.assertEqual(command[3], "materializer")
        self.assertEqual(command[4:], [f"Ref::{name}" for name in module.PARAMETER_NAMES])
        self.assertEqual(payload["retryStrategy"], {"attempts": 1})
        self.assertEqual(payload["timeout"], {"attemptDurationSeconds": 21600})

    def test_mutable_or_malformed_script_identity_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact S3 VersionId"):
            module.render(self.args(script_version_id=""))
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            module.render(self.args(script_sha256="A" * 64))

    def test_fixed_shell_values_reject_whitespace_and_metacharacters(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsafe shell"):
            module.render(
                self.args(
                    receipt_prefix=(
                        "s3://diana-omics-private-results-172630973301-us-east-1/"
                        "runs/subject01/unit/final;echo-nope"
                    ),
                )
            )
        with self.assertRaisesRegex(ValueError, "unsafe shell"):
            module.render(
                self.args(
                    script_uri=(
                        "s3://diana-omics-private-results-172630973301-us-east-1/"
                        "runs/subject01/unit/script.py extra"
                    ),
                )
            )

    def test_main_writes_create_only_mode_0600_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "materializer-job-definition.json"
            argv = ["render_materializer_job_definition.py", "--output", str(output)]
            for key, value in vars(self.args()).items():
                argv.extend([f"--{key.replace('_', '-')}", value])

            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(module.main(), 0)

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["jobDefinitionName"], module.JOB_DEFINITION_NAME)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

            with (
                mock.patch.object(sys, "argv", argv),
                self.assertRaisesRegex(FileExistsError, "refusing to overwrite"),
            ):
                module.main()

    def test_output_below_symlinked_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real"
            real_parent.mkdir()
            linked_parent = root / "linked"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
                module.write_json_create_only(
                    linked_parent / "materializer-job-definition.json",
                    {"status": "passed"},
                )

            self.assertFalse(
                (real_parent / "materializer-job-definition.json").exists()
            )

    def test_output_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "materializer-job-definition.json"
            real_fsync_directory = module.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    module,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(ValueError, "output changed during write"),
            ):
                module.write_json_create_only(output, {"status": "passed"})

            self.assertFalse(output.exists())

    def test_output_rejects_symlink_swap_before_final_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "materializer-job-definition.json"
            relocated = root / "relocated-job-definition.json"
            real_is_file = Path.is_file
            swapped = False

            def swap_after_first_output_file_check(path: Path) -> bool:
                nonlocal swapped
                result = real_is_file(path)
                if path == output and result and not swapped:
                    output.unlink()
                    relocated.write_text('{"status":"relocated"}\n', encoding="utf-8")
                    output.symlink_to(relocated)
                    swapped = True
                return result

            with (
                mock.patch.object(
                    Path,
                    "is_file",
                    autospec=True,
                    side_effect=swap_after_first_output_file_check,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "materializer-job-definition.json SHA-256 input "
                    "is missing or a symlink",
                ),
            ):
                module.write_json_create_only(output, {"status": "passed"})

            self.assertTrue(swapped)
            self.assertFalse(output.exists())
            self.assertFalse(output.is_symlink())
            self.assertEqual(
                relocated.read_text(encoding="utf-8"),
                '{"status":"relocated"}\n',
            )

    def test_sha256_file_rejects_symlinked_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_source = root / "real-job-definition.json"
            real_source.write_text('{"status":"real"}\n', encoding="utf-8")
            source_link = root / "materializer-job-definition.json"
            source_link.symlink_to(real_source)

            with self.assertRaisesRegex(
                ValueError,
                "materializer-job-definition.json SHA-256 input "
                "is missing or a symlink",
            ):
                module.sha256_file(source_link)

            real_parent = root / "real-parent"
            real_parent.mkdir()
            (real_parent / "materializer-job-definition.json").write_text(
                '{"status":"real"}\n',
                encoding="utf-8",
            )
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "materializer-job-definition.json SHA-256 input "
                "parent may not be a symlink",
            ):
                module.sha256_file(linked_parent / "materializer-job-definition.json")


if __name__ == "__main__":
    unittest.main()
