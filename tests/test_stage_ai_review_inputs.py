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
        self.bundle.mkdir()
        (self.bundle / "review_bundle.json").write_text(
            '{"subject_alias":"subject01"}\n',
            encoding="utf-8",
        )
        (self.bundle / "reviewer-a.prompt.md").write_text(
            "reviewer A\n",
            encoding="utf-8",
        )
        (self.bundle / "reviewer-b.prompt.md").write_text(
            "reviewer B\n",
            encoding="utf-8",
        )
        self.write_manifest()
        self.output_root = self.root / "inputs"
        self.receipt = self.root / "stage-receipt.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_manifest(self) -> None:
        (self.bundle / "bundle_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "review_bundle_sha256": sha256(
                        self.bundle / "review_bundle.json"
                    ),
                    "prompt_sha256": {
                        "A": sha256(self.bundle / "reviewer-a.prompt.md"),
                        "B": sha256(self.bundle / "reviewer-b.prompt.md"),
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

        with self.assertRaisesRegex(FileExistsError, "receipt already exists"):
            STAGE.stage(self.bundle, self.output_root, self.receipt)


if __name__ == "__main__":
    unittest.main()
