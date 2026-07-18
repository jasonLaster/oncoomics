#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
        argv = [
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

        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(module.main(), 0)

        receipt = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], 3)
        self.assertEqual(receipt["status"], "registered_not_submitted")
        self.assertEqual(receipt["authorized_hrd_state"], "no_call")
        self.assertEqual(receipt["batch"]["revision"], 5)
        self.assertTrue(receipt["checks"]["exact_active_revision"])
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_registration_revision_must_match_live_active_arn(self) -> None:
        response = json.loads(self.response.read_text(encoding="utf-8"))
        response["revision"] = 6
        self.write(self.response, response)

        with self.assertRaisesRegex(ValueError, "one active materializer revision"):
            module.validate(
                script_anchor=json.loads(self.script_anchor.read_text(encoding="utf-8")),
                definition=json.loads(self.definition.read_text(encoding="utf-8")),
                registration=response,
                live=json.loads(self.live.read_text(encoding="utf-8")),
                script_anchor_sha256="a" * 64,
                definition_sha256="b" * 64,
            )

    def test_live_definition_must_match_local_payload(self) -> None:
        live = json.loads(self.live.read_text(encoding="utf-8"))
        live["jobDefinitions"][0]["containerProperties"]["memory"] += 1

        with self.assertRaisesRegex(ValueError, "differs from local payload"):
            module.validate(
                script_anchor=json.loads(self.script_anchor.read_text(encoding="utf-8")),
                definition=json.loads(self.definition.read_text(encoding="utf-8")),
                registration=json.loads(self.response.read_text(encoding="utf-8")),
                live=live,
                script_anchor_sha256="a" * 64,
                definition_sha256="b" * 64,
            )

    def test_stale_receipt_uri_shape_is_rejected(self) -> None:
        definition = json.loads(self.definition.read_text(encoding="utf-8"))
        shell = definition["containerProperties"]["command"][2]
        shell = shell.replace("--receipt-prefix", "--receipt-uri")
        definition["containerProperties"]["command"][2] = shell
        live = json.loads(self.live.read_text(encoding="utf-8"))
        live["jobDefinitions"][0]["containerProperties"]["command"][2] = shell

        with self.assertRaisesRegex(ValueError, "not exact"):
            module.validate(
                script_anchor=json.loads(self.script_anchor.read_text(encoding="utf-8")),
                definition=definition,
                registration=json.loads(self.response.read_text(encoding="utf-8")),
                live=live,
                script_anchor_sha256="a" * 64,
                definition_sha256="b" * 64,
            )

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


if __name__ == "__main__":
    unittest.main()
