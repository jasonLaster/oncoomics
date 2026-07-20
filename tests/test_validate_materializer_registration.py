#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import copy
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
    "validate_materializer_registration",
    SCRIPT_DIR / "validate_materializer_registration.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

RENDER_SPEC = importlib.util.spec_from_file_location(
    "render_materializer_job_definition",
    SCRIPT_DIR / "render_materializer_job_definition.py",
)
assert RENDER_SPEC and RENDER_SPEC.loader
renderer = importlib.util.module_from_spec(RENDER_SPEC)
RENDER_SPEC.loader.exec_module(renderer)


def write_duplicate_json_field(path: Path, key: str, stale_value: object) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(payload, indent=2, sort_keys=True)
    if key not in payload:
        raise AssertionError(f"missing top-level JSON field {key}")
    current = f'  "{key}": '
    if text.count(current) != 1:
        raise AssertionError(f"expected exactly one top-level JSON field {key}")
    duplicate = f'  "{key}": {json.dumps(stale_value, sort_keys=True)},\n{current}'
    path.write_text(text.replace(current, duplicate, 1) + "\n", encoding="utf-8")


class ValidateMaterializerRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.script_anchor = self.root / "materializer-script-freeze-anchor.json"
        self.definition = self.root / "materializer-job-definition.json"
        self.response = self.root / "materializer-registration-response.json"
        self.live = self.root / "materializer-live-definition.json"
        self.output = self.root / "materializer-registration-receipt.json"
        self._write_fixtures()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def rewrite_materializer_script_hash(self, definition: dict, digest: str) -> None:
        shell = definition["containerProperties"]["command"][2]
        definition["containerProperties"]["command"][2] = shell.replace(
            'test "$actual" = ' + "a" * 64,
            f'test "$actual" = {digest}',
        )

    def validate(
        self,
        *,
        script_anchor: dict | None = None,
        definition: dict | None = None,
        registration: dict | None = None,
        live: dict | None = None,
    ) -> dict:
        return module.validate(
            script_anchor=script_anchor
            if script_anchor is not None
            else json.loads(self.script_anchor.read_text(encoding="utf-8")),
            definition=definition
            if definition is not None
            else json.loads(self.definition.read_text(encoding="utf-8")),
            registration=registration
            if registration is not None
            else json.loads(self.response.read_text(encoding="utf-8")),
            live=live
            if live is not None
            else json.loads(self.live.read_text(encoding="utf-8")),
            script_anchor_sha256="a" * 64,
            definition_sha256="b" * 64,
        )

    def render_args(self) -> argparse.Namespace:
        base = (
            "s3://diana-omics-private-results-172630973301-us-east-1/"
            "runs/subject01/unit"
        )
        return argparse.Namespace(
            script_uri=base + "/preparation/scripts/materialize_crosscheck_inputs.py",
            script_version_id="exact-script-version",
            script_sha256="a" * 64,
            source_vcf_uri=base + "/deterministic/artifacts/final.vcf.gz",
            source_vcf_index_uri=base + "/deterministic/artifacts/final.vcf.gz.tbi",
            source_matrix_uri=base + "/deterministic/artifacts/sbs96.csv",
            reference_fasta_uri=base + "/deterministic/reference/reference.fa",
            reference_fai_uri=base + "/deterministic/reference/reference.fa.fai",
            reference_fasta_sha256="b" * 64,
            reference_fai_sha256="c" * 64,
            destination_prefix=base + "/deterministic/final",
            receipt_prefix=base + "/deterministic/provenance/crosscheck-materialization-receipts",
            kms_key_arn=(
                "arn:aws:kms:us-east-1:172630973301:key/"
                "45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
            ),
            image=(
                "172630973301.dkr.ecr.us-east-1.amazonaws.com/"
                "diana-omics@sha256:"
                + "d" * 64
            ),
            job_role_arn="arn:aws:iam::172630973301:role/diana-omics-prod-use1-batch-job",
        )

    def main_argv(self) -> list[str]:
        return [
            "validate_materializer_registration.py",
            "--materializer-script-anchor",
            str(self.script_anchor),
            "--job-definition-payload",
            str(self.definition),
            "--registration-response",
            str(self.response),
            "--live-job-definition",
            str(self.live),
            "--output",
            str(self.output),
        ]

    def _write_fixtures(self) -> None:
        definition = renderer.render(self.render_args())
        arn = module.JOB_DEFINITION_ARN + "5"
        self.write(
            self.script_anchor,
            {
                "schema_version": 1,
                "status": "passed",
                "source": {
                    "logical_path": "scripts/materialize_crosscheck_inputs.py",
                    "sha256": "a" * 64,
                    "bytes": 12345,
                },
                "object": {
                    "uri": self.render_args().script_uri,
                    "bucket": "diana-omics-private-results-172630973301-us-east-1",
                    "key": "runs/subject01/unit/preparation/scripts/materialize_crosscheck_inputs.py",
                    "version_id": "exact-script-version",
                    "server_side_encryption": "aws:kms",
                    "ssekms_key_id": self.render_args().kms_key_arn,
                },
                "checks": {
                    name: True for name in module.EXPECTED_SCRIPT_ANCHOR_CHECKS
                },
            },
        )
        self.write(self.definition, definition)
        self.write(
            self.response,
            {
                "jobDefinitionName": module.JOB_DEFINITION_NAME,
                "jobDefinitionArn": arn,
                "revision": 5,
            },
        )
        live = copy.deepcopy(definition)
        live.update({"jobDefinitionArn": arn, "revision": 5, "status": "ACTIVE"})
        live["retryStrategy"] = {"attempts": 1, "evaluateOnExit": []}
        self.write(self.live, {"jobDefinitions": [live]})

    def test_validate_writes_schema_3_registration_receipt_for_future_revision(self) -> None:
        with mock.patch.object(sys, "argv", self.main_argv()):
            self.assertEqual(module.main(), 0)

        receipt = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], 3)
        self.assertEqual(receipt["status"], "registered_not_submitted")
        self.assertEqual(receipt["authorized_hrd_state"], "no_call")
        self.assertEqual(receipt["batch"]["revision"], 5)
        self.assertTrue(receipt["checks"]["exact_active_revision"])
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_main_binds_hashes_from_loaded_anchor_and_definition_bytes(self) -> None:
        original_hashes = {
            "materializer script anchor": module.sha256_path(self.script_anchor),
            "materializer job definition": module.sha256_path(self.definition),
        }
        rewritten_labels: set[str] = set()
        original_load = module.load_json_with_sha256

        def load_then_rewrite(path: Path, label: str) -> tuple[dict[str, object], str]:
            value, digest = original_load(path, label)
            if label in original_hashes:
                rewritten = json.loads(path.read_text(encoding="utf-8"))
                rewritten["rewritten_after_parse"] = label
                self.write(path, rewritten)
                rewritten_labels.add(label)
            return value, digest

        with (
            mock.patch.object(sys, "argv", self.main_argv()),
            mock.patch.object(
                module,
                "load_json_with_sha256",
                side_effect=load_then_rewrite,
            ),
        ):
            self.assertEqual(module.main(), 0)

        self.assertEqual(rewritten_labels, set(original_hashes))
        self.assertNotEqual(
            module.sha256_path(self.script_anchor),
            original_hashes["materializer script anchor"],
        )
        self.assertNotEqual(
            module.sha256_path(self.definition),
            original_hashes["materializer job definition"],
        )
        receipt = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["script_freeze"]["anchor_sha256"],
            original_hashes["materializer script anchor"],
        )
        self.assertEqual(
            receipt["batch"]["definition_sha256"],
            original_hashes["materializer job definition"],
        )

    def test_rejects_duplicate_input_object_names_before_output(self) -> None:
        cases = (
            ("materializer script anchor", self.script_anchor, "schema_version"),
            ("materializer job definition", self.definition, "containerProperties"),
            ("materializer registration response", self.response, "revision"),
            ("materializer live job definition", self.live, "jobDefinitions"),
        )
        for label, path, duplicate_key in cases:
            with self.subTest(label=label):
                self._write_fixtures()
                write_duplicate_json_field(path, duplicate_key, 0)

                with (
                    mock.patch.object(sys, "argv", self.main_argv()),
                    self.assertRaisesRegex(
                        ValueError,
                        f"duplicate JSON object name in {label}",
                    ),
                ):
                    module.main()

                self.assertFalse(self.output.exists())

    def test_registration_revision_must_match_live_active_arn(self) -> None:
        response = json.loads(self.response.read_text(encoding="utf-8"))
        response["revision"] = 6
        self.write(self.response, response)

        with self.assertRaisesRegex(ValueError, "one active materializer revision"):
            self.validate(registration=response)

    def test_registration_revision_must_be_an_exact_positive_integer(self) -> None:
        registration = json.loads(self.response.read_text(encoding="utf-8"))
        live = json.loads(self.live.read_text(encoding="utf-8"))
        registration["revision"] = True
        registration["jobDefinitionArn"] = module.JOB_DEFINITION_ARN + "True"
        live["jobDefinitions"][0]["revision"] = True
        live["jobDefinitions"][0]["jobDefinitionArn"] = registration["jobDefinitionArn"]

        with self.assertRaisesRegex(ValueError, "one active materializer revision"):
            self.validate(registration=registration, live=live)

    def test_live_definition_must_match_local_payload(self) -> None:
        live = json.loads(self.live.read_text(encoding="utf-8"))
        live["jobDefinitions"][0]["containerProperties"]["memory"] += 1

        with self.assertRaisesRegex(ValueError, "differs from local payload"):
            self.validate(live=live)

    def test_stale_receipt_uri_shape_is_rejected(self) -> None:
        definition = json.loads(self.definition.read_text(encoding="utf-8"))
        shell = definition["containerProperties"]["command"][2]
        shell = shell.replace("--receipt-prefix", "--receipt-uri")
        definition["containerProperties"]["command"][2] = shell
        live = json.loads(self.live.read_text(encoding="utf-8"))
        live["jobDefinitions"][0]["containerProperties"]["command"][2] = shell

        with self.assertRaisesRegex(ValueError, "failed receipt_prefix"):
            self.validate(definition=definition, live=live)

    def test_script_anchor_check_map_must_be_exact(self) -> None:
        cases = (
            (
                "missing",
                lambda checks: checks.pop("exact_kms"),
                "missing exact_kms",
            ),
            (
                "unexpected",
                lambda checks: checks.update({"future_anchor_check": True}),
                "unexpected future_anchor_check",
            ),
            (
                "failed",
                lambda checks: checks.update({"exact_kms": False}),
                "failed exact_kms",
            ),
        )

        for label, mutate, error in cases:
            with self.subTest(label=label):
                anchor = json.loads(self.script_anchor.read_text(encoding="utf-8"))
                mutate(anchor["checks"])

                with self.assertRaisesRegex(ValueError, error):
                    self.validate(script_anchor=anchor)

    def test_script_anchor_rejects_non_integer_schema_version(self) -> None:
        anchor = json.loads(self.script_anchor.read_text(encoding="utf-8"))
        anchor["schema_version"] = 1.0

        with self.assertRaisesRegex(
            ValueError,
            "materializer script anchor must be schema 1 and passed",
        ):
            self.validate(script_anchor=anchor)

    def test_script_anchor_rejects_coerced_source_sha256(self) -> None:
        digest = "1" * 64
        anchor = json.loads(self.script_anchor.read_text(encoding="utf-8"))
        anchor["source"]["sha256"] = int(digest)
        definition = json.loads(self.definition.read_text(encoding="utf-8"))
        live = json.loads(self.live.read_text(encoding="utf-8"))
        self.rewrite_materializer_script_hash(definition, digest)
        self.rewrite_materializer_script_hash(live["jobDefinitions"][0], digest)

        with self.assertRaisesRegex(
            ValueError,
            "materializer source SHA-256 must be a lowercase SHA-256",
        ):
            self.validate(script_anchor=anchor, definition=definition, live=live)

    def test_materializer_command_check_map_must_be_exact(self) -> None:
        cases = (
            (
                frozenset((*module.EXPECTED_COMMAND_CHECKS, "future_command_check")),
                "missing future_command_check",
            ),
            (
                frozenset(
                    name
                    for name in module.EXPECTED_COMMAND_CHECKS
                    if name != "checksum_mode"
                ),
                "unexpected checksum_mode",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(module, "EXPECTED_COMMAND_CHECKS", expected),
                self.assertRaisesRegex(ValueError, error),
            ):
                self.validate()

    def test_failed_materializer_command_check_is_rejected(self) -> None:
        definition = json.loads(self.definition.read_text(encoding="utf-8"))
        shell = definition["containerProperties"]["command"][2]
        definition["containerProperties"]["command"][2] = shell.replace(
            "set -euo pipefail;",
            "set -eo pipefail;",
        )
        live = json.loads(self.live.read_text(encoding="utf-8"))
        live["jobDefinitions"][0]["containerProperties"]["command"][2] = (
            definition["containerProperties"]["command"][2]
        )

        with self.assertRaisesRegex(ValueError, "failed strict"):
            self.validate(definition=definition, live=live)

    def test_registration_check_map_must_be_exact(self) -> None:
        cases = (
            (
                frozenset(
                    (*module.EXPECTED_REGISTRATION_CHECKS, "future_registration_check")
                ),
                "missing future_registration_check",
            ),
            (
                frozenset(
                    name
                    for name in module.EXPECTED_REGISTRATION_CHECKS
                    if name != "no_job_submitted"
                ),
                "unexpected no_job_submitted",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(module, "EXPECTED_REGISTRATION_CHECKS", expected),
                self.assertRaisesRegex(ValueError, error),
            ):
                self.validate()

    def test_failed_registration_check_is_rejected(self) -> None:
        definition = json.loads(self.definition.read_text(encoding="utf-8"))
        definition["retryStrategy"] = {"attempts": 2}
        live = json.loads(self.live.read_text(encoding="utf-8"))
        live["jobDefinitions"][0]["retryStrategy"] = {
            "attempts": 2,
            "evaluateOnExit": [],
        }

        with self.assertRaisesRegex(ValueError, "failed one_attempt"):
            self.validate(definition=definition, live=live)

    def test_batch_retry_and_timeout_checks_require_exact_integers(self) -> None:
        cases = (
            ("retry_bool", "retryStrategy", {"attempts": True}, "failed one_attempt"),
            ("retry_float", "retryStrategy", {"attempts": 1.0}, "failed one_attempt"),
            (
                "timeout_float",
                "timeout",
                {"attemptDurationSeconds": 21600.0},
                "failed timeout_21600",
            ),
            (
                "timeout_bool",
                "timeout",
                {"attemptDurationSeconds": True},
                "failed timeout_21600",
            ),
        )

        for label, field, value, error in cases:
            with self.subTest(label=label):
                definition = json.loads(self.definition.read_text(encoding="utf-8"))
                live = json.loads(self.live.read_text(encoding="utf-8"))
                definition[field] = value
                live["jobDefinitions"][0][field] = value

                with self.assertRaisesRegex(ValueError, error):
                    self.validate(definition=definition, live=live)

    def test_output_below_symlinked_parent_is_rejected(self) -> None:
        real_parent = self.root / "real"
        real_parent.mkdir()
        linked_parent = self.root / "linked"
        linked_parent.symlink_to(real_parent, target_is_directory=True)

        with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
            module.write_json_create_only(
                linked_parent / "materializer-registration-receipt.json",
                {"status": "passed"},
            )

        self.assertFalse((real_parent / "materializer-registration-receipt.json").exists())

    def test_sha256_path_rejects_symlinked_hash_inputs(self) -> None:
        real_input = self.root / "real-definition.json"
        linked_input = self.root / "job-definition-link.json"
        real_input.write_text("{}\n", encoding="utf-8")
        linked_input.symlink_to(real_input)

        with self.assertRaisesRegex(
            ValueError,
            "job-definition-link.json SHA-256 input must be a real file",
        ):
            module.sha256_path(linked_input)

    def test_sha256_path_rejects_changing_hash_inputs(self) -> None:
        hash_input = self.root / "materializer-script-anchor.json"
        hash_input.write_text('{"status":"first"}\n', encoding="utf-8")
        real_read_once = module.read_real_file_once
        reads = 0

        def mutate_after_first_read(path: Path, label: str) -> bytes:
            nonlocal reads
            data = real_read_once(path, label)
            if path == hash_input and reads == 0:
                hash_input.write_text('{"status":"second"}\n', encoding="utf-8")
            reads += 1
            return data

        with (
            mock.patch.object(
                module,
                "read_real_file_once",
                side_effect=mutate_after_first_read,
            ),
            self.assertRaisesRegex(
                ValueError,
                "materializer-script-anchor.json SHA-256 input changed during read",
            ),
        ):
            module.sha256_path(hash_input)

    def test_load_json_rejects_changing_json_inputs(self) -> None:
        receipt = self.root / "registration-response.json"
        receipt.write_text('{"status":"first"}\n', encoding="utf-8")
        real_read_once = module.read_real_file_once
        reads = 0

        def mutate_after_first_read(path: Path, label: str) -> bytes:
            nonlocal reads
            data = real_read_once(path, label)
            if path == receipt and reads == 0:
                receipt.write_text('{"status":"second"}\n', encoding="utf-8")
            reads += 1
            return data

        with (
            mock.patch.object(
                module,
                "read_real_file_once",
                side_effect=mutate_after_first_read,
            ),
            self.assertRaisesRegex(
                ValueError,
                "materializer registration response changed during read",
            ),
        ):
            module.load_json_with_sha256(
                receipt,
                "materializer registration response",
            )

    def test_read_stable_file_rejects_leaf_swapped_to_symlink_after_preflight(
        self,
    ) -> None:
        path = self.root / "registration-response.json"
        path.write_text('{"status":"first"}\n', encoding="utf-8")
        real_os_open = module.os.open
        moved = False

        def swap_to_symlink_before_open(
            input_path: Path,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal moved
            if input_path == path and not moved:
                moved = True
                real_path = self.root / "registration-response.real.json"
                path.rename(real_path)
                path.symlink_to(real_path)
            return real_os_open(input_path, flags, mode, dir_fd=dir_fd)

        with (
            mock.patch.object(
                module.os,
                "open",
                side_effect=swap_to_symlink_before_open,
            ),
            self.assertRaisesRegex(
                ValueError,
                "materializer registration response changed during read",
            ),
        ):
            module.load_json(path, "materializer registration response")

        self.assertTrue(moved)

    def test_output_rehashes_after_parent_fsync(self) -> None:
        real_fsync_directory = module.fsync_directory

        def tamper_after_parent_fsync(path: Path) -> None:
            real_fsync_directory(path)
            self.output.write_text('{"status":"tampered"}\n', encoding="utf-8")

        with (
            mock.patch.object(
                module,
                "fsync_directory",
                side_effect=tamper_after_parent_fsync,
            ),
            self.assertRaisesRegex(ValueError, "output changed during write"),
        ):
            module.write_json_create_only(self.output, {"status": "passed"})

        self.assertFalse(self.output.exists())

    def test_output_rechecks_mode_after_parent_fsync(self) -> None:
        real_fsync_directory = module.fsync_directory

        def chmod_after_parent_fsync(path: Path) -> None:
            real_fsync_directory(path)
            self.output.chmod(0o644)

        with (
            mock.patch.object(
                module,
                "fsync_directory",
                side_effect=chmod_after_parent_fsync,
            ),
            self.assertRaisesRegex(ValueError, "output mode changed during write"),
        ):
            module.write_json_create_only(self.output, {"status": "passed"})

        self.assertFalse(self.output.exists())

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
                    module.exact_schema_version(
                        {"schema_version": value},
                        expected,
                    ),
                    accepted,
                )

    def test_schema_version_checks_avoid_raw_comparisons(self) -> None:
        tree = ast.parse(
            (SCRIPT_DIR / "validate_materializer_registration.py").read_text(
                encoding="utf-8"
            )
        )
        parent_by_child = {
            child: parent
            for parent in ast.walk(tree)
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
            for node in ast.walk(tree)
            if isinstance(node, ast.Compare)
            and "schema_version" in ast.unparse(node)
            and not in_exact_schema_helper(node)
        ]

        self.assertEqual(raw_schema_version_comparisons, [])


if __name__ == "__main__":
    unittest.main()
