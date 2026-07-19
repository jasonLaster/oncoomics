from __future__ import annotations

import ast
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import verify_parabricks_mirror_receipt as verify
from diana_omics.utils import write_json

SOURCE_DIGEST = "sha256:" + "a" * 64
DESTINATION_DIGEST = "sha256:" + "b" * 64
REPOSITORY = "172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks"
DIANA_GIT_COMMIT = "c" * 40
EXPECTED_TAG = "sha256-" + "a" * 64 + "-diana-" + "c" * 12


def receipt() -> dict:
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
            "repository": REPOSITORY,
            "tag": EXPECTED_TAG,
            "digest": DESTINATION_DIGEST,
            "parabricks_container": f"{REPOSITORY}@{DESTINATION_DIGEST}",
        },
        "diana_omics": {
            "git_commit": DIANA_GIT_COMMIT,
            "dockerfile_sha256": "sha256:" + "d" * 64,
        },
    }


def ecr_response(*image_details: dict | str) -> str:
    return json.dumps({"imageDetails": list(image_details)})


class ParabricksMirrorReceiptTests(unittest.TestCase):
    def test_schema_version_must_be_an_exact_json_integer(self) -> None:
        for value in (True, 1.0, "1", 2, None):
            malformed = receipt()
            malformed["schema_version"] = value

            with self.subTest(value=value):
                with self.assertRaisesRegex(verify.MirrorReceiptError, "schema_version"):
                    verify.validate_mirror_receipt(malformed)

        self.assertTrue(verify._is_exact_int(1, 1))
        self.assertFalse(verify._is_exact_int(True, 1))
        self.assertFalse(verify._is_exact_int(1.0, 1))

    def test_schema_guards_use_exact_integer_helper(self) -> None:
        source_path = Path(verify.__file__)
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))

        raw_comparisons = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "schema_version" not in segment:
                continue
            if segment in {"type(value) is int", "value == expected"}:
                continue
            raw_comparisons.append(f"{node.lineno}: {segment}")

        self.assertEqual([], raw_comparisons)

    def test_validates_reviewed_use2_mirror_receipt(self) -> None:
        summary = verify.validate_mirror_receipt(receipt())

        self.assertEqual(DESTINATION_DIGEST, summary["destination_digest"])
        self.assertEqual("sha256:" + "d" * 64, summary["diana_omics_dockerfile_sha256"])
        self.assertEqual(DIANA_GIT_COMMIT, summary["diana_omics_git_commit"])
        self.assertEqual(f"{REPOSITORY}@{DESTINATION_DIGEST}", summary["parabricks_container"])
        self.assertEqual(EXPECTED_TAG, summary["tag"])

    def test_validates_current_diana_source_binding(self) -> None:
        summary = verify.validate_mirror_receipt(receipt())

        verify.validate_current_diana_source_binding(
            summary,
            current={
                "dockerfile_sha256": "sha256:" + "d" * 64,
                "git_commit": DIANA_GIT_COMMIT,
            },
        )

        with self.assertRaisesRegex(verify.MirrorReceiptError, "Git HEAD"):
            verify.validate_current_diana_source_binding(
                summary,
                current={
                    "dockerfile_sha256": "sha256:" + "d" * 64,
                    "git_commit": "e" * 40,
                },
            )

        with self.assertRaisesRegex(verify.MirrorReceiptError, "Dockerfile"):
            verify.validate_current_diana_source_binding(
                summary,
                current={
                    "dockerfile_sha256": "sha256:" + "e" * 64,
                    "git_commit": DIANA_GIT_COMMIT,
                },
            )

    def test_rejects_dockerfile_below_symlinked_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-infra"
            linked_parent = root / "infra"
            dockerfile = linked_parent / "aws" / "Dockerfile.parabricks"
            (real_parent / "aws").mkdir(parents=True)
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            (real_parent / "aws" / "Dockerfile.parabricks").write_text(
                "FROM scratch\n",
                encoding="utf-8",
            )

            self.assertTrue(dockerfile.is_file())
            with self.assertRaisesRegex(verify.MirrorReceiptError, "parent may not be a symlink"):
                verify.sha256_path(dockerfile)

    def test_rejects_unpinned_source_image(self) -> None:
        malformed = receipt()
        malformed["source"]["image"] = "nvcr.io/nvidia/clara/parabricks:latest"

        with self.assertRaisesRegex(verify.MirrorReceiptError, "source.image"):
            verify.validate_mirror_receipt(malformed)

    def test_rejects_short_digest_tag(self) -> None:
        malformed = receipt()
        malformed["destination"]["tag"] = "sha256-" + "a" * 16

        with self.assertRaisesRegex(verify.MirrorReceiptError, "Diana git revision"):
            verify.validate_mirror_receipt(malformed)

    def test_rejects_destination_tag_without_diana_revision(self) -> None:
        malformed = receipt()
        malformed["destination"]["tag"] = "sha256-" + "a" * 64

        with self.assertRaisesRegex(verify.MirrorReceiptError, "Diana git revision"):
            verify.validate_mirror_receipt(malformed)

    def test_rejects_malformed_diana_git_commit(self) -> None:
        malformed = receipt()
        malformed["diana_omics"]["git_commit"] = "c" * 12

        with self.assertRaisesRegex(verify.MirrorReceiptError, "40-character Git SHA"):
            verify.validate_mirror_receipt(malformed)

    def test_rejects_malformed_dockerfile_sha256(self) -> None:
        malformed = receipt()
        malformed["diana_omics"]["dockerfile_sha256"] = "d" * 64

        with self.assertRaisesRegex(verify.MirrorReceiptError, "dockerfile_sha256"):
            verify.validate_mirror_receipt(malformed)

    def test_rejects_destination_container_mismatch(self) -> None:
        malformed = receipt()
        malformed["destination"]["parabricks_container"] = f"{REPOSITORY}@sha256:" + "c" * 64

        with self.assertRaisesRegex(verify.MirrorReceiptError, "parabricks_container"):
            verify.validate_mirror_receipt(malformed)

    def test_environment_loader_reads_override_path(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "parabricks-mirror.json"
            write_json(path, receipt())

            with patch.dict("os.environ", {"PARABRICKS_MIRROR_RECEIPT": str(path)}, clear=False):
                payload, loaded_path = verify.load_receipt_from_environment()

        self.assertEqual(path, loaded_path)
        self.assertEqual("parabricks_mirror_receipt", payload["manifest_type"])

    def test_environment_loader_rejects_missing_directory_or_symlinked_receipts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_receipt = root / "real-parabricks-mirror.json"
            write_json(real_receipt, receipt())

            cases = {
                "directory": root / "directory",
                "missing": root / "missing.json",
                "symlink": root / "symlink.json",
            }
            cases["directory"].mkdir()
            cases["symlink"].symlink_to(real_receipt)

            for label, path in cases.items():
                with self.subTest(label=label), patch.dict(
                    "os.environ",
                    {"PARABRICKS_MIRROR_RECEIPT": str(path)},
                    clear=False,
                ):
                    with self.assertRaisesRegex(verify.MirrorReceiptError, "real JSON file"):
                        verify.load_receipt_from_environment()

    def test_environment_loader_rejects_receipt_below_symlinked_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-receipts"
            linked_parent = root / "linked-receipts"
            real_parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            path = linked_parent / "parabricks-mirror.json"
            write_json(path, receipt())

            with patch.dict("os.environ", {"PARABRICKS_MIRROR_RECEIPT": str(path)}, clear=False):
                with self.assertRaisesRegex(verify.MirrorReceiptError, "parent may not be a symlink"):
                    verify.load_receipt_from_environment()

    @patch("diana_omics.commands.phase3_wgs.verify_parabricks_mirror_receipt.subprocess.run")
    def test_loads_destination_image_digest_from_ecr(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=ecr_response(
                {
                    "imageDigest": DESTINATION_DIGEST,
                    "imageTags": [EXPECTED_TAG],
                }
            ),
        )

        observed = verify.load_mirror_digest(
            parabricks_container=f"{REPOSITORY}@{DESTINATION_DIGEST}",
            region="us-east-2",
            expected_tag=EXPECTED_TAG,
        )

        self.assertEqual(DESTINATION_DIGEST, observed)
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
                f"imageDigest={DESTINATION_DIGEST}",
                "--output",
                "json",
            ],
            run.call_args.args[0],
        )

    @patch("diana_omics.commands.phase3_wgs.verify_parabricks_mirror_receipt.subprocess.run")
    def test_load_mirror_digest_rejects_destination_without_source_tag(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=ecr_response(
                {
                    "imageDigest": DESTINATION_DIGEST,
                    "imageTags": ["sha256-" + "c" * 64],
                }
            ),
        )

        with self.assertRaisesRegex(verify.MirrorReceiptError, "imageTags"):
            verify.load_mirror_digest(
                parabricks_container=f"{REPOSITORY}@{DESTINATION_DIGEST}",
                region="us-east-2",
                expected_tag=EXPECTED_TAG,
            )

    @patch("diana_omics.commands.phase3_wgs.verify_parabricks_mirror_receipt.subprocess.run")
    def test_load_mirror_digest_rejects_duplicate_ecr_rows(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=ecr_response(
                {
                    "imageDigest": DESTINATION_DIGEST,
                    "imageTags": [EXPECTED_TAG],
                },
                {
                    "imageDigest": "sha256:" + "c" * 64,
                    "imageTags": [EXPECTED_TAG],
                },
            ),
        )

        with self.assertRaisesRegex(verify.MirrorReceiptError, "exactly one imageDetails"):
            verify.load_mirror_digest(
                parabricks_container=f"{REPOSITORY}@{DESTINATION_DIGEST}",
                region="us-east-2",
                expected_tag=EXPECTED_TAG,
            )

    @patch("diana_omics.commands.phase3_wgs.verify_parabricks_mirror_receipt.subprocess.run")
    def test_load_mirror_digest_rejects_malformed_ecr_row(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=ecr_response("not-an-image-detail"),
        )

        with self.assertRaisesRegex(verify.MirrorReceiptError, "imageDetails\\[0\\]"):
            verify.load_mirror_digest(
                parabricks_container=f"{REPOSITORY}@{DESTINATION_DIGEST}",
                region="us-east-2",
                expected_tag=EXPECTED_TAG,
            )

    @patch("diana_omics.commands.phase3_wgs.verify_parabricks_mirror_receipt.subprocess.run")
    def test_missing_destination_image_is_reported(self, run) -> None:
        run.side_effect = subprocess.CalledProcessError(
            returncode=254,
            cmd=["aws"],
            output="ImageNotFound",
        )

        with self.assertRaisesRegex(verify.MirrorReceiptError, "ImageNotFound"):
            verify.load_mirror_digest(
                parabricks_container=f"{REPOSITORY}@{DESTINATION_DIGEST}",
                region="us-east-2",
                expected_tag=EXPECTED_TAG,
            )


if __name__ == "__main__":
    unittest.main()
