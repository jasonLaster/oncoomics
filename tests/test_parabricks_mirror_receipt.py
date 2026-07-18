from __future__ import annotations

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


def receipt() -> dict:
    source_hex = SOURCE_DIGEST.removeprefix("sha256:")
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
            "tag": f"sha256-{source_hex}",
            "digest": DESTINATION_DIGEST,
            "parabricks_container": f"{REPOSITORY}@{DESTINATION_DIGEST}",
        },
    }


class ParabricksMirrorReceiptTests(unittest.TestCase):
    def test_validates_reviewed_use2_mirror_receipt(self) -> None:
        summary = verify.validate_mirror_receipt(receipt())

        self.assertEqual(DESTINATION_DIGEST, summary["destination_digest"])
        self.assertEqual(f"{REPOSITORY}@{DESTINATION_DIGEST}", summary["parabricks_container"])
        self.assertEqual("sha256-" + "a" * 64, summary["tag"])

    def test_rejects_unpinned_source_image(self) -> None:
        malformed = receipt()
        malformed["source"]["image"] = "nvcr.io/nvidia/clara/parabricks:latest"

        with self.assertRaisesRegex(verify.MirrorReceiptError, "source.image"):
            verify.validate_mirror_receipt(malformed)

    def test_rejects_short_digest_tag(self) -> None:
        malformed = receipt()
        malformed["destination"]["tag"] = "sha256-" + "a" * 16

        with self.assertRaisesRegex(verify.MirrorReceiptError, "full source digest tag"):
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

    @patch("diana_omics.commands.phase3_wgs.verify_parabricks_mirror_receipt.subprocess.run")
    def test_loads_destination_image_digest_from_ecr(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"imageDetails":[{"imageDigest":"' + DESTINATION_DIGEST + '"}]}',
        )

        observed = verify.load_mirror_digest(
            parabricks_container=f"{REPOSITORY}@{DESTINATION_DIGEST}",
            region="us-east-2",
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
            )


if __name__ == "__main__":
    unittest.main()
