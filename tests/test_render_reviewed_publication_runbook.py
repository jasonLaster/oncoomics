from __future__ import annotations

import base64
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "render_reviewed_publication_runbook",
    SCRIPT_DIR / "render_reviewed_publication_runbook.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def checksum_from_digest(value: str) -> str:
    return base64.b64encode(bytes.fromhex(value)).decode("ascii")


def write_receipts(root: Path) -> list[Path]:
    receipt_root = root / "receipts"
    receipt_root.mkdir()
    receipts = []
    for method_id in MODULE.REPORT_METHOD_IDS:
        expected = tuple(sorted(MODULE.METHOD_CONTRACTS[method_id]["files"]))
        prefix = (
            f"s3://{MODULE.PRIVATE_BUCKET}/runs/{MODULE.SUBJECT_ALIAS}/"
            f"{MODULE.RUN_ID}/reports/{method_id}/revisions/{'b' * 64}/"
        )
        key_prefix = prefix.removeprefix(f"s3://{MODULE.PRIVATE_BUCKET}/")
        rows = []
        for index, relative in enumerate(expected, 1):
            sha256 = f"{index:064x}"
            key = key_prefix + relative
            rows.append(
                {
                    "relative_path": relative,
                    "bucket": MODULE.PRIVATE_BUCKET,
                    "key": key,
                    "uri": f"s3://{MODULE.PRIVATE_BUCKET}/{key}",
                    "version_id": f"private-version-{index}",
                    "bytes": index + 100,
                    "sha256": sha256,
                    "checksum_sha256": checksum_from_digest(sha256),
                    "checksum_type": "FULL_OBJECT",
                    "server_side_encryption": "aws:kms",
                    "kms_key_id": MODULE.PRIVATE_KMS_KEY_ARN,
                    "status": "passed",
                    "checks": {"version_id": True, "kms": True},
                }
            )
        receipt = {
            "schema_version": 1,
            "status": "passed",
            "subject_alias": MODULE.SUBJECT_ALIAS,
            "run_id": MODULE.RUN_ID,
            "method_id": method_id,
            "destination_prefix": prefix,
            "kms_key_arn": MODULE.PRIVATE_KMS_KEY_ARN,
            "expected_files": list(expected),
            "object_count": len(expected),
            "passed_count": len(expected),
            "objects": rows,
        }
        path = receipt_root / f"{method_id}.json"
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        receipts.append(path)
    return receipts


class RenderReviewedPublicationRunbookTests(unittest.TestCase):
    def test_renderer_publishes_ten_reports_in_canonical_order(self) -> None:
        receipts = [
            Path(f"/receipts/{method_id}.json")
            for method_id in MODULE.REPORT_METHOD_IDS
        ]
        text = MODULE.render(Path("/repo"), receipts, "terminal")

        self.assertEqual(text.count("/repo/scripts/publish_reviewed_public_report.py"), 20)
        self.assertEqual(text.count("--private-publication-receipt "), 20)
        self.assertEqual(text.count("--destination-prefix "), 20)
        previous = -1
        for method_id in MODULE.REPORT_METHOD_IDS:
            index = text.find(f"--method-id {method_id}", previous + 1)
            self.assertGreater(index, previous)
            self.assertIn(MODULE.destination_prefix(method_id), text)
            previous = index

    def test_publish_command_has_exact_dry_and_apply_argv(self) -> None:
        receipt = Path("/receipts/deterministic_full_wgs.json")
        output = Path("/receipts/deterministic_full_wgs.public.json")
        scripts = Path("/repo/scripts")

        dry_command = MODULE.publish_command(
            scripts,
            receipt,
            "deterministic_full_wgs",
            output,
            apply=False,
        )
        apply_command = MODULE.publish_command(
            scripts,
            receipt,
            "deterministic_full_wgs",
            output,
            apply=True,
        )

        self.assertEqual(
            dry_command,
            [
                "python3",
                Path("/repo/scripts/publish_reviewed_public_report.py"),
                "--private-publication-receipt",
                receipt,
                "--method-id",
                "deterministic_full_wgs",
                "--destination-prefix",
                MODULE.destination_prefix("deterministic_full_wgs"),
                "--receipt-output",
                output,
                "--region",
                MODULE.REGION,
            ],
        )
        self.assertEqual(apply_command, [*dry_command, "--apply"])

    def test_renderer_rebuilds_and_publishes_public_index(self) -> None:
        receipts = [
            Path(f"/receipts/{method_id}.json")
            for method_id in MODULE.REPORT_METHOD_IDS
        ]
        text = MODULE.render(Path("/repo"), receipts, "terminal")

        self.assertIn("/repo/scripts/build_public_results_index.py", text)
        self.assertEqual(text.count("/repo/scripts/publish_public_results_index.py"), 2)
        self.assertIn("/repo/.codex-tmp/public-index/public-index.terminal.dry.json", text)
        self.assertIn("/repo/.codex-tmp/public-index/public-index.terminal.json", text)
        for stale in MODULE.STALE_TOKENS:
            self.assertNotIn(stale, text)

    def test_index_commands_have_exact_build_dry_and_apply_argv(self) -> None:
        index = Path("/repo/.codex-tmp/public-index/objects.json")
        commands = MODULE.index_commands(Path("/repo"), "unit")

        self.assertEqual(
            commands,
            [
                [
                    "python3",
                    Path("/repo/scripts/build_public_results_index.py"),
                    "--output",
                    index,
                ],
                [
                    "python3",
                    Path("/repo/scripts/publish_public_results_index.py"),
                    "--index",
                    index,
                    "--receipt-output",
                    Path("/repo/.codex-tmp/public-index/public-index.unit.dry.json"),
                ],
                [
                    "python3",
                    Path("/repo/scripts/publish_public_results_index.py"),
                    "--index",
                    index,
                    "--receipt-output",
                    Path("/repo/.codex-tmp/public-index/public-index.unit.json"),
                    "--apply",
                ],
            ],
        )

    def test_private_receipt_gate_accepts_current_checked_in_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipts = write_receipts(Path(temporary))

            summaries = MODULE.validate_private_report_receipts(receipts)

            self.assertEqual(
                [summary["method_id"] for summary in summaries],
                list(MODULE.REPORT_METHOD_IDS),
            )
            self.assertEqual(
                summaries[-1]["destination_prefix"],
                MODULE.destination_prefix("comparative_hrd_synthesis"),
            )

            with self.assertRaisesRegex(ValueError, "canonical"):
                MODULE.validate_private_report_receipts(
                    [receipts[1], receipts[0], *receipts[2:]]
                )
            with self.assertRaisesRegex(ValueError, "exactly ten"):
                MODULE.validate_private_report_receipts(receipts[:-1])

            failed = json.loads(receipts[0].read_text())
            failed["status"] = "failed"
            receipts[0].write_text(json.dumps(failed, indent=2, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "not exact and passed"):
                MODULE.validate_private_report_receipts(receipts)

    def test_required_existing_points_at_checked_in_scripts(self) -> None:
        prerequisites = {
            path.as_posix() for path in MODULE.required_existing(Path("/repo"))
        }

        self.assertEqual(
            prerequisites,
            {
                "/repo/scripts/hrd_report_inventory.py",
                "/repo/scripts/publish_reviewed_public_report.py",
                "/repo/scripts/build_public_results_index.py",
                "/repo/scripts/publish_public_results_index.py",
            },
        )

    def test_required_absent_includes_publication_receipts(self) -> None:
        outputs = [
            path.as_posix()
            for path in MODULE.required_absent(Path("/repo"), "unit")
        ]

        self.assertEqual(
            outputs[:20],
            [
                (
                    "/repo/.codex-tmp/hrd-reports/publication/"
                    f"unit.{method_id}.public{suffix}.json"
                )
                for method_id in MODULE.REPORT_METHOD_IDS
                for suffix in (".dry", "")
            ],
        )
        self.assertEqual(
            outputs[20:],
            [
                "/repo/.codex-tmp/public-index/public-index.unit.dry.json",
                "/repo/.codex-tmp/public-index/public-index.unit.json",
            ],
        )

    def test_main_rejects_preexisting_publication_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path in MODULE.required_existing(root):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            receipts = write_receipts(root)

            stale = (
                root
                / ".codex-tmp/hrd-reports/publication/"
                "terminal.rosalind_diana_wgs.public.json"
            )
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_text("{}\n", encoding="utf-8")
            output = root / "reviewed-public.md"

            argv = [
                "render_reviewed_publication_runbook.py",
                "--output",
                str(output),
                "--root",
                str(root),
            ]
            for receipt in receipts:
                argv.extend(["--private-publication-receipt", str(receipt)])

            with (
                patch.object(sys, "argv", argv),
                self.assertRaisesRegex(SystemExit, "create-only outputs"),
            ):
                MODULE.main()

            self.assertFalse(output.exists())

    def test_runbook_can_include_private_receipt_gate(self) -> None:
        summaries = (
            {
                "method_id": "comparative_hrd_synthesis",
                "receipt": "receipt.json",
                "destination_prefix": MODULE.destination_prefix(
                    "comparative_hrd_synthesis"
                ),
                "object_count": 3,
            },
        )

        text = MODULE.render(
            Path("/repo"),
            [Path(f"/receipts/{method_id}.json") for method_id in MODULE.REPORT_METHOD_IDS],
            "unit",
            receipt_summaries=summaries,
        )

        self.assertIn("## 0. Private publication receipt gate", text)
        self.assertIn("comparative_hrd_synthesis", text)


if __name__ == "__main__":
    unittest.main()
