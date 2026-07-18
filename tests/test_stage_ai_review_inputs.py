from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
STAGE_SCRIPT = SCRIPT_DIR / "stage_ai_review_inputs.py"
STAGE_SPEC = importlib.util.spec_from_file_location(
    "stage_ai_review_inputs",
    STAGE_SCRIPT,
)
assert STAGE_SPEC and STAGE_SPEC.loader
STAGE = importlib.util.module_from_spec(STAGE_SPEC)
STAGE_SPEC.loader.exec_module(STAGE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StageAiReviewInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.write_bundle(self.bundle)
        self.output_root = self.root / "inputs"
        self.receipt = self.root / "stage-receipt.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_bundle(self, bundle: Path) -> None:
        bundle.mkdir()
        (bundle / "review_bundle.json").write_text(
            '{"subject_alias":"subject01"}\n',
            encoding="utf-8",
        )
        (bundle / "reviewer-a.prompt.md").write_text(
            "reviewer A\n",
            encoding="utf-8",
        )
        (bundle / "reviewer-b.prompt.md").write_text(
            "reviewer B\n",
            encoding="utf-8",
        )
        self.write_bundle_manifest(bundle)

    def write_manifest(self) -> None:
        self.write_bundle_manifest(self.bundle)

    def write_bundle_manifest(self, bundle: Path) -> None:
        (bundle / "bundle_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "review_bundle_sha256": sha256(
                        bundle / "review_bundle.json"
                    ),
                    "prompt_sha256": {
                        "A": sha256(bundle / "reviewer-a.prompt.md"),
                        "B": sha256(bundle / "reviewer-b.prompt.md"),
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_stages_exact_two_file_directories_from_bundle_manifest(self) -> None:
        receipt = STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(stat.S_IMODE(self.receipt.stat().st_mode), 0o600)
        for role, prompt in (
            ("A", "reviewer-a.prompt.md"),
            ("B", "reviewer-b.prompt.md"),
        ):
            directory = self.output_root / STAGE.ROLE_DIRS[role]
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(
                sorted(path.name for path in directory.iterdir()),
                ["review_bundle.json", prompt],
            )
            self.assertEqual(
                sha256(directory / "review_bundle.json"),
                sha256(self.bundle / "review_bundle.json"),
            )
            self.assertEqual(
                sha256(directory / prompt),
                sha256(self.bundle / prompt),
            )

    def test_cli_prints_reviewer_input_locations(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(
                STAGE.main(
                    [
                        "--bundle-dir",
                        str(self.bundle),
                        "--output-root",
                        str(self.output_root),
                        "--receipt-output",
                        str(self.receipt),
                    ]
                ),
                0,
            )

        payload = json.loads(out.getvalue())
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(
            payload["reviewer_a_input"],
            str(self.output_root.resolve() / "reviewer-a-input"),
        )
        self.assertEqual(
            payload["reviewer_b_input"],
            str(self.output_root.resolve() / "reviewer-b-input"),
        )
        self.assertEqual(payload["receipt_output"], str(self.receipt))

    def test_rejects_tampered_prompt_before_creating_outputs(self) -> None:
        (self.bundle / "reviewer-a.prompt.md").write_text(
            "tampered\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertFalse(self.output_root.exists())
        self.assertFalse(self.receipt.exists())

    def test_rejects_staged_bytes_that_differ_from_bundle_manifest(self) -> None:
        real_write_once = STAGE.write_once

        def write_tampered_once(path: Path, data: bytes) -> None:
            real_write_once(path, data)
            if path.name == "reviewer-a.prompt.md":
                path.write_text("tampered during staging\n", encoding="utf-8")

        with mock.patch.object(
            STAGE,
            "write_once",
            side_effect=write_tampered_once,
        ):
            with self.assertRaisesRegex(ValueError, "reviewer A .* SHA-256 mismatch"):
                STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertFalse((self.output_root / "reviewer-a-input").exists())
        self.assertFalse(self.receipt.exists())

    def test_refuses_existing_reviewer_directories(self) -> None:
        (self.output_root / STAGE.ROLE_DIRS["A"]).mkdir(parents=True)

        with self.assertRaisesRegex(FileExistsError, "exists"):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

    def test_refuses_existing_receipt(self) -> None:
        self.receipt.write_text("do not replace\n", encoding="utf-8")

        with self.assertRaisesRegex(FileExistsError, "receipt output already exists"):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

    def test_rejects_symlinked_custody_paths(self) -> None:
        cases = (
            "bundle",
            "output-root",
            "output-root-parent",
            "receipt",
            "receipt-parent",
            "bundle-manifest",
        )

        for target in cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle = root / "bundle"
                output_root = root / "inputs"
                receipt = root / "stage-receipt.json"
                self.write_bundle(bundle)

                if target == "bundle":
                    real_bundle = root / "bundle-real"
                    bundle.rename(real_bundle)
                    bundle.symlink_to(real_bundle, target_is_directory=True)
                    message = "bundle directory"
                elif target == "output-root":
                    output_root.symlink_to(
                        root / "inputs-real",
                        target_is_directory=True,
                    )
                    message = "output root"
                elif target == "output-root-parent":
                    real_parent = root / "real-output-parent"
                    real_parent.mkdir()
                    linked_parent = root / "linked-output-parent"
                    linked_parent.symlink_to(
                        real_parent,
                        target_is_directory=True,
                    )
                    output_root = linked_parent / "missing" / "inputs"
                    message = "output root parent"
                elif target == "receipt":
                    receipt.symlink_to(root / "receipt-real.json")
                    message = "receipt output"
                elif target == "receipt-parent":
                    real_parent = root / "real-receipt-parent"
                    real_parent.mkdir()
                    linked_parent = root / "linked-receipt-parent"
                    linked_parent.symlink_to(
                        real_parent,
                        target_is_directory=True,
                    )
                    receipt = linked_parent / "missing" / "stage-receipt.json"
                    message = "receipt output parent"
                else:
                    real_manifest = bundle / "bundle_manifest.real.json"
                    (bundle / "bundle_manifest.json").rename(real_manifest)
                    (bundle / "bundle_manifest.json").symlink_to(real_manifest)
                    message = "bundle_manifest.json"

                with self.assertRaisesRegex(ValueError, message):
                    STAGE.stage(bundle, output_root, receipt)

                self.assertFalse((output_root / "reviewer-a-input").exists())
                self.assertFalse((output_root / "reviewer-b-input").exists())
                self.assertFalse(receipt.exists())
                self.assertFalse((root / "real-output-parent" / "missing").exists())
                self.assertFalse((root / "real-receipt-parent" / "missing").exists())

    def test_rejects_overlapping_bundle_output_and_receipt_paths(self) -> None:
        cases = (
            (
                self.bundle / "reviewer-inputs",
                self.receipt,
                "output root must be separate",
            ),
            (
                self.output_root,
                self.output_root / "reviewer-a-input" / "stage-receipt.json",
                "receipt output must be separate",
            ),
            (
                self.output_root,
                self.bundle / "stage-receipt.json",
                "receipt output must be separate",
            ),
        )

        for output_root, receipt, message in cases:
            with self.subTest(output_root=output_root, receipt=receipt):
                with self.assertRaisesRegex(ValueError, message):
                    STAGE.stage(self.bundle, output_root, receipt)

                self.assertFalse((self.bundle / "reviewer-inputs").exists())
                self.assertFalse((self.output_root / "reviewer-a-input").exists())
                self.assertFalse((self.output_root / "reviewer-b-input").exists())
                self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
