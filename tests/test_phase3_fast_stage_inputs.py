from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import render_phase3_fast_staging_plan as staging
from diana_omics.commands.phase3_wgs import stage_phase3_fast_inputs as stage
from diana_omics.utils import write_json
from tests.test_phase3_fast_input_manifest import SHA_1
from tests.test_phase3_fast_staging_plan import ready_cache_manifest


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def downloadable_staging_plan(root: Path) -> tuple[dict, dict[str, bytes]]:
    plan = staging.build_phase3_fast_staging_plan(
        ready_cache_manifest(),
        cache_manifest_sha256=SHA_1,
        staging_root=root / "scratch",
    )
    payloads = {}
    total_bytes = 0
    for row in plan["staged_objects"]:
        artifact = row["artifact"]
        data = (
            b"chr1\t25\t0\t50\t51\nchr2\t10\t0\t50\t51\nchrM\t5\t0\t50\t51\n"
            if artifact == "reference.fa.fai"
            else f"downloaded {artifact}\n".encode()
        )
        payloads[artifact] = data
        row["bytes"] = len(data)
        row["sha256"] = _sha256(data)
        total_bytes += len(data)
    plan["total_bytes"] = total_bytes
    return plan, payloads


class FakeS3GetObjectClient:
    def __init__(self, payloads: Mapping[str, bytes]) -> None:
        self.payloads = payloads
        self.commands: list[list[str]] = []

    def get_object(self, row: Mapping[str, Any]) -> None:
        self.commands.append(list(row["get_object_command"]))
        Path(row["local_path"]).write_bytes(self.payloads[str(row["artifact"])])


class FailingS3GetObjectClient:
    def get_object(self, row: Mapping[str, Any]) -> None:
        Path(row["local_path"]).write_bytes(b"partial")
        raise RuntimeError("boom")


class Phase3FastStageInputsTests(unittest.TestCase):
    def test_stage_inputs_materializes_exact_get_object_plan_then_verifies(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, payloads = downloadable_staging_plan(Path(tmp))
            client = FakeS3GetObjectClient(payloads)

            manifest = stage.stage_phase3_fast_inputs(
                plan,
                client=client,
                staging_plan_sha256=SHA_1,
            )

            self.assertEqual(
                [row["get_object_command"][:-1] for row in plan["staged_objects"]],
                [command[:-1] for command in client.commands],
            )
            self.assertTrue(all(command[-1].endswith(".tmp") for command in client.commands))
            self.assertEqual("phase3_wgs_fast_staged_inputs_manifest", manifest["manifest_type"])
            self.assertEqual("ready", manifest["status"])
            self.assertEqual("no_call", manifest["interpretation"]["authorized_hrd_state"])
            self.assertEqual(15, manifest["object_count"])
            self.assertEqual("subject01_tumor", manifest["bam_pair"]["tumor"]["bam"]["sample_id"])
            self.assertTrue(Path(manifest["bam_pair"]["tumor"]["bam"]["local_path"]).is_file())

    def test_rejects_drifted_get_object_command_before_download(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, payloads = downloadable_staging_plan(Path(tmp))
            plan["staged_objects"][0]["get_object_command"] = ["aws", "s3", "cp"]
            client = FakeS3GetObjectClient(payloads)

            with self.assertRaisesRegex(stage.ManifestError, "get_object_command"):
                stage.stage_phase3_fast_inputs(
                    plan,
                    client=client,
                    staging_plan_sha256=SHA_1,
                )

        self.assertEqual([], client.commands)

    def test_rejects_non_no_call_plan_before_download(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, payloads = downloadable_staging_plan(Path(tmp))
            plan["interpretation"]["authorized_hrd_state"] = "partial_evidence"
            client = FakeS3GetObjectClient(payloads)

            with self.assertRaisesRegex(stage.ManifestError, "no_call"):
                stage.stage_phase3_fast_inputs(
                    plan,
                    client=client,
                    staging_plan_sha256=SHA_1,
                )

        self.assertEqual([], client.commands)

    def test_removes_partial_file_after_failed_download(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, _payloads = downloadable_staging_plan(Path(tmp))
            first_path = Path(plan["staged_objects"][0]["local_path"])

            with self.assertRaisesRegex(RuntimeError, "boom"):
                stage.stage_phase3_fast_inputs(
                    plan,
                    client=FailingS3GetObjectClient(),
                    staging_plan_sha256=SHA_1,
                )

            self.assertFalse(first_path.exists())
            self.assertEqual([], list(first_path.parent.glob("*.tmp")))

    def test_rejects_symlinked_staging_root_before_download(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_scratch = root / "real-scratch"
            real_scratch.mkdir()
            (root / "scratch").symlink_to(real_scratch, target_is_directory=True)
            plan, payloads = downloadable_staging_plan(root)
            client = FakeS3GetObjectClient(payloads)

            with self.assertRaisesRegex(stage.ManifestError, "parent may not be a symlink"):
                stage.stage_phase3_fast_inputs(
                    plan,
                    client=client,
                    staging_plan_sha256=SHA_1,
                )

            self.assertEqual([], client.commands)
            self.assertEqual([], list(real_scratch.rglob("*")))

    def test_rejects_duplicate_local_paths_before_download(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, payloads = downloadable_staging_plan(Path(tmp))
            duplicate = plan["staged_objects"][0]["local_path"]
            plan["staged_objects"][1]["local_path"] = duplicate
            plan["staged_objects"][1]["get_object_command"][-1] = duplicate
            client = FakeS3GetObjectClient(payloads)

            with self.assertRaisesRegex(stage.ManifestError, "duplicate local paths"):
                stage.stage_phase3_fast_inputs(
                    plan,
                    client=client,
                    staging_plan_sha256=SHA_1,
                )

        self.assertEqual([], client.commands)

    def test_rejects_duplicate_artifacts_before_download(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, payloads = downloadable_staging_plan(Path(tmp))
            plan["staged_objects"][1]["artifact"] = plan["staged_objects"][0]["artifact"]
            client = FakeS3GetObjectClient(payloads)

            with self.assertRaisesRegex(stage.ManifestError, "duplicate artifact"):
                stage.stage_phase3_fast_inputs(
                    plan,
                    client=client,
                    staging_plan_sha256=SHA_1,
                )

        self.assertEqual([], client.commands)

    def test_rejects_extra_artifacts_before_download(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, payloads = downloadable_staging_plan(Path(tmp))
            plan["staged_objects"][0]["artifact"] = "extra.vcf"
            client = FakeS3GetObjectClient(payloads)

            with self.assertRaisesRegex(stage.ManifestError, "expected exact artifacts"):
                stage.stage_phase3_fast_inputs(
                    plan,
                    client=client,
                    staging_plan_sha256=SHA_1,
                )

        self.assertEqual([], client.commands)

    def test_environment_command_writes_staged_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "staging-plan.json"
            output_path = root / "staged-inputs.json"
            plan, payloads = downloadable_staging_plan(root)
            write_json(input_path, plan)

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_STAGING_PLAN": str(input_path),
                    "PHASE3_WGS_FAST_STAGED_INPUTS_OUTPUT": str(output_path),
                },
                clear=False,
            ):
                manifest, manifest_path = stage.load_manifest_from_environment(
                    FakeS3GetObjectClient(payloads),
                )
                stage.write_manifest(manifest_path, manifest)

            self.assertEqual(output_path, manifest_path)
            self.assertEqual("ready", manifest["status"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_staged_inputs_manifest"', output_path.read_text(encoding="utf-8"))

    def test_environment_command_rejects_redirected_staging_plan(self) -> None:
        for bad_kind in ("missing", "directory", "symlink"):
            with self.subTest(bad_kind=bad_kind), TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_plan = root / "real-staging-plan.json"
                bad_plan = root / f"staging-plan-{bad_kind}.json"
                plan, payloads = downloadable_staging_plan(root)
                write_json(real_plan, plan)
                if bad_kind == "directory":
                    bad_plan.mkdir()
                elif bad_kind == "symlink":
                    bad_plan.symlink_to(real_plan)
                client = FakeS3GetObjectClient(payloads)

                with patch.dict(
                    "os.environ",
                    {
                        "PHASE3_WGS_FAST_STAGING_PLAN": str(bad_plan),
                        "PHASE3_WGS_FAST_STAGED_INPUTS_OUTPUT": str(root / "staged-inputs.json"),
                    },
                    clear=False,
                ):
                    with self.assertRaisesRegex(stage.ManifestError, "staging_plan"):
                        stage.load_manifest_from_environment(client)

                self.assertEqual([], client.commands)

    def test_manifest_output_rejects_symlinked_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_output = root / "real-output"
            real_output.mkdir()
            linked_output = root / "linked-output"
            linked_output.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(stage.ManifestError, "parent may not be a symlink"):
                stage.write_manifest(linked_output / "staged-inputs.json", {"status": "redirected"})

            self.assertEqual([], list(real_output.rglob("*")))


if __name__ == "__main__":
    unittest.main()
