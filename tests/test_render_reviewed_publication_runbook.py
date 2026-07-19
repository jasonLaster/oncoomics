from __future__ import annotations

import base64
import hashlib
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
import publish_reviewed_public_report as PUBLISH  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "render_reviewed_publication_runbook",
    SCRIPT_DIR / "render_reviewed_publication_runbook.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def checksum_from_digest(value: str) -> str:
    return base64.b64encode(bytes.fromhex(value)).decode("ascii")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_receipts(root: Path) -> list[Path]:
    receipt_root = root / "receipts"
    receipt_root.mkdir()
    receipts = []
    for method_id in MODULE.REPORT_METHOD_IDS:
        expected = tuple(sorted(MODULE.METHOD_CONTRACTS[method_id]["files"]))
        rows = []
        for index, relative in enumerate(expected, 1):
            sha256 = f"{index:064x}"
            rows.append(
                {
                    "relative_path": relative,
                    "version_id": f"private-version-{index}",
                    "bytes": index + 100,
                    "sha256": sha256,
                    "checksum_sha256": checksum_from_digest(sha256),
                    "checksum_type": "FULL_OBJECT",
                    "server_side_encryption": "aws:kms",
                    "kms_key_id": PUBLISH.PRIVATE_KMS_KEY_ARN,
                    "status": "passed",
                    "checks": dict(PUBLISH.PRIVATE_RECEIPT_OBJECT_CHECKS),
                }
            )
        revision = PUBLISH.canonical_packet_digest(rows)
        prefix = (
            f"s3://{PUBLISH.PRIVATE_BUCKET}/runs/{PUBLISH.SUBJECT_ALIAS}/"
            f"{PUBLISH.RUN_ID}/reports/{method_id}/revisions/{revision}/"
        )
        key_prefix = prefix.removeprefix(f"s3://{PUBLISH.PRIVATE_BUCKET}/")
        for row in rows:
            key = key_prefix + row["relative_path"]
            row["bucket"] = PUBLISH.PRIVATE_BUCKET
            row["key"] = key
            row["uri"] = f"s3://{PUBLISH.PRIVATE_BUCKET}/{key}"
        receipt = {
            "schema_version": 1,
            "status": "passed",
            "generated_at_utc": "2026-07-19T00:00:00+00:00",
            "apply": True,
            "subject_alias": PUBLISH.SUBJECT_ALIAS,
            "run_id": PUBLISH.RUN_ID,
            "method_id": method_id,
            "packet_revision": revision,
            "source_packet_dir": str((root / "packets" / method_id).resolve()),
            "destination_prefix": prefix,
            "kms_key_arn": PUBLISH.PRIVATE_KMS_KEY_ARN,
            "expected_files": list(expected),
            "object_count": len(expected),
            "passed_count": len(expected),
            "forbidden_token_count": 1,
            "forbidden_token_sha256": ["a" * 64],
            "objects": rows,
            "checks": dict(PUBLISH.PRIVATE_RECEIPT_APPLY_CHECKS),
            "dry_run_receipt": {
                "path": str((receipt_root / f"{method_id}.dry.json").resolve()),
                "sha256": "b" * 64,
                "packet_revision": revision,
                "status": "dry_run",
            },
            "destination_final_history_count": len(expected),
            "completed_at_utc": "2026-07-19T00:01:00+00:00",
        }
        path = receipt_root / f"{method_id}.json"
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        receipts.append(path)
    return receipts


def receipt_summaries(
    receipts: list[Path] | None = None,
) -> tuple[dict[str, str | int], ...]:
    receipt_paths = receipts or [
        Path(f"/receipts/{method_id}.json")
        for method_id in MODULE.REPORT_METHOD_IDS
    ]
    return tuple(
        {
            "method_id": method_id,
            "receipt": str(receipt_paths[index - 1]),
            "receipt_sha256": f"{index:064x}",
            "destination_prefix": MODULE.destination_prefix(method_id),
            "object_count": 3,
        }
        for index, method_id in enumerate(MODULE.REPORT_METHOD_IDS, 1)
    )


def render(
    receipts: list[Path] | None = None,
    receipt_stem: str = "terminal",
    forbidden_tokens_file: Path | None = None,
) -> str:
    receipt_paths = receipts or [
        Path(f"/receipts/{method_id}.json")
        for method_id in MODULE.REPORT_METHOD_IDS
    ]
    return MODULE.render(
        Path("/repo"),
        receipt_paths,
        receipt_stem,
        receipt_summaries=receipt_summaries(receipt_paths),
        forbidden_tokens_file=forbidden_tokens_file,
    )


class RenderReviewedPublicationRunbookTests(unittest.TestCase):
    def test_renderer_publishes_ten_reports_in_canonical_order(self) -> None:
        receipts = [
            Path(f"/receipts/{method_id}.json")
            for method_id in MODULE.REPORT_METHOD_IDS
        ]
        text = render(receipts)

        self.assertEqual(text.count("/repo/scripts/publish_reviewed_public_report.py"), 20)
        self.assertEqual(text.count("--private-publication-receipt "), 20)
        self.assertEqual(text.count("--destination-prefix "), 20)
        report_publication_section = text.split("## 2. Rebuild", 1)[0]
        self.assertEqual(report_publication_section.count("--dry-run-receipt "), 10)
        previous = -1
        for method_id in MODULE.REPORT_METHOD_IDS:
            index = text.find(f"--method-id {method_id}", previous + 1)
            self.assertGreater(index, previous)
            self.assertIn(MODULE.destination_prefix(method_id), text)
            previous = index
        for index, method_id in enumerate(MODULE.REPORT_METHOD_IDS, 1):
            self.assertIn(
                f"- `{method_id}`: 3 files → private receipt SHA-256 "
                f"`{index:064x}` -> `{MODULE.destination_prefix(method_id)}`",
                text,
            )

    def test_renderer_hands_forbidden_tokens_file_to_public_scan(self) -> None:
        text = render(forbidden_tokens_file=Path("/fast/forbidden_tokens.json"))

        self.assertEqual(text.count("--forbidden-tokens-file /fast/forbidden_tokens.json"), 20)
        for block in text.split("```bash\n")[1:21]:
            command = block.split("\n```", 1)[0]
            self.assertEqual(command.count("--forbidden-tokens-file"), 1)

    def test_publish_command_has_exact_dry_and_apply_argv(self) -> None:
        receipt = Path("/receipts/deterministic_full_wgs.json")
        dry_output = Path("/receipts/deterministic_full_wgs.public.dry.json")
        apply_output = Path("/receipts/deterministic_full_wgs.public.json")
        scripts = Path("/repo/scripts")

        dry_command = MODULE.publish_command(
            scripts,
            receipt,
            "a" * 64,
            "deterministic_full_wgs",
            dry_output,
            apply=False,
        )
        apply_command = MODULE.publish_command(
            scripts,
            receipt,
            "a" * 64,
            "deterministic_full_wgs",
            apply_output,
            apply=True,
            dry_run_receipt=dry_output,
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
                dry_output,
                "--region",
                PUBLISH.REGION,
                "--private-publication-receipt-sha256",
                "a" * 64,
            ],
        )
        self.assertEqual(
            apply_command,
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
                apply_output,
                "--region",
                PUBLISH.REGION,
                "--private-publication-receipt-sha256",
                "a" * 64,
                "--dry-run-receipt",
                dry_output,
                "--apply",
            ],
        )

        with_file_command = MODULE.publish_command(
            scripts,
            receipt,
            "a" * 64,
            "deterministic_full_wgs",
            dry_output,
            apply=False,
            forbidden_tokens_file=Path("/fast/forbidden_tokens.json"),
        )
        self.assertEqual(
            with_file_command[-2:],
            ["--forbidden-tokens-file", Path("/fast/forbidden_tokens.json")],
        )

    def test_renderer_binds_every_apply_to_its_public_dry_run_receipt(self) -> None:
        text = render()

        for method_id in MODULE.REPORT_METHOD_IDS:
            dry_receipt = (
                f"/repo/.codex-tmp/hrd-reports/publication/"
                f"terminal.{method_id}.public.dry.json"
            )
            apply_receipt = (
                f"/repo/.codex-tmp/hrd-reports/publication/"
                f"terminal.{method_id}.public.json"
            )
            dry_index = text.index(f"--receipt-output {dry_receipt}")
            apply_index = text.index(f"--receipt-output {apply_receipt}")
            dry_ref_index = text.index(f"--dry-run-receipt {dry_receipt}")
            self.assertLess(dry_index, apply_index)
            self.assertLess(apply_index, dry_ref_index)

    def test_renderer_rebuilds_and_publishes_public_index(self) -> None:
        receipts = [
            Path(f"/receipts/{method_id}.json")
            for method_id in MODULE.REPORT_METHOD_IDS
        ]
        text = render(receipts)

        self.assertIn("/repo/scripts/build_public_results_index.py", text)
        self.assertEqual(text.count("/repo/scripts/publish_public_results_index.py"), 2)
        index_section = text.split("## 2. Rebuild and publish the public index", 1)[1]
        self.assertEqual(index_section.count("--reviewed-public-receipt "), 30)
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
                    *[
                        token
                        for method_id in MODULE.REPORT_METHOD_IDS
                        for token in (
                            "--reviewed-public-receipt",
                            Path(
                                "/repo/.codex-tmp/hrd-reports/publication/"
                                f"unit.{method_id}.public.json"
                            ),
                        )
                    ],
                ],
                [
                    "python3",
                    Path("/repo/scripts/publish_public_results_index.py"),
                    "--index",
                    index,
                    *[
                        token
                        for method_id in MODULE.REPORT_METHOD_IDS
                        for token in (
                            "--reviewed-public-receipt",
                            Path(
                                "/repo/.codex-tmp/hrd-reports/publication/"
                                f"unit.{method_id}.public.json"
                            ),
                        )
                    ],
                    "--receipt-output",
                    Path("/repo/.codex-tmp/public-index/public-index.unit.dry.json"),
                ],
                [
                    "python3",
                    Path("/repo/scripts/publish_public_results_index.py"),
                    "--index",
                    index,
                    *[
                        token
                        for method_id in MODULE.REPORT_METHOD_IDS
                        for token in (
                            "--reviewed-public-receipt",
                            Path(
                                "/repo/.codex-tmp/hrd-reports/publication/"
                                f"unit.{method_id}.public.json"
                            ),
                        )
                    ],
                    "--receipt-output",
                    Path("/repo/.codex-tmp/public-index/public-index.unit.json"),
                    "--dry-run-receipt",
                    Path("/repo/.codex-tmp/public-index/public-index.unit.dry.json"),
                    "--apply",
                ],
            ],
        )

    def test_public_index_receipts_are_shared_by_index_commands_and_absent_gate(
        self,
    ) -> None:
        expected = MODULE.public_index_receipt_paths(Path("/repo"), "unit")
        commands = MODULE.index_commands(Path("/repo"), "unit")
        receipt_outputs = [
            command[command.index("--receipt-output") + 1]
            for command in commands
            if "--receipt-output" in command
        ]

        self.assertEqual(
            expected,
            (
                Path("/repo/.codex-tmp/public-index/public-index.unit.dry.json"),
                Path("/repo/.codex-tmp/public-index/public-index.unit.json"),
            ),
        )
        self.assertEqual(receipt_outputs, list(expected))
        self.assertEqual(
            MODULE.required_absent(Path("/repo"), "unit")[-3:],
            (Path("/repo/.codex-tmp/public-index/objects.json"), *expected),
        )

    def test_private_receipt_gate_accepts_current_checked_in_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = write_receipts(root)

            summaries = MODULE.validate_private_report_receipts(receipts)

            self.assertEqual(
                [summary["method_id"] for summary in summaries],
                list(MODULE.REPORT_METHOD_IDS),
            )
            self.assertEqual(
                summaries[-1]["destination_prefix"],
                MODULE.destination_prefix("comparative_hrd_synthesis"),
            )
            self.assertEqual(summaries[0]["receipt_sha256"], sha256(receipts[0]))

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

    def test_private_receipt_gate_rejects_receipts_below_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = write_receipts(root)
            real_parent = root / "real-receipts"
            (root / "receipts").rename(real_parent)
            (root / "receipts").symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.validate_private_report_receipts(receipts)

    def test_sha256_rejects_symlinked_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_input = root / "real-receipt.json"
            linked_input = root / "receipt.json"
            real_input.write_text("{}\n", encoding="utf-8")
            linked_input.symlink_to(real_input)

            with self.assertRaisesRegex(
                ValueError,
                "receipt.json SHA-256 input is missing or a symlink",
            ):
                MODULE.sha256(linked_input)

    def test_receipt_gate_pins_every_public_publish_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipts = write_receipts(Path(temporary))
            summaries = MODULE.validate_private_report_receipts(receipts)

            text = MODULE.render(
                Path("/repo"),
                receipts,
                "terminal",
                receipt_summaries=summaries,
            )

            self.assertEqual(text.count("--private-publication-receipt-sha256 "), 20)
            for summary in summaries:
                self.assertEqual(
                    text.count(
                        "--private-publication-receipt-sha256 "
                        f"{summary['receipt_sha256']}"
                    ),
                    2,
                )

    def test_render_refuses_missing_receipt_summaries(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires ten"):
            MODULE.render(
                Path("/repo"),
                [
                    Path(f"/receipts/{method_id}.json")
                    for method_id in MODULE.REPORT_METHOD_IDS
                ],
                "terminal",
            )

    def test_render_refuses_unbound_receipt_paths(self) -> None:
        receipts = [
            Path(f"/receipts/{method_id}.json")
            for method_id in MODULE.REPORT_METHOD_IDS
        ]
        summaries = receipt_summaries(receipts)

        with self.assertRaisesRegex(ValueError, "path is not bound"):
            MODULE.render(
                Path("/repo"),
                [receipts[1], receipts[0], *receipts[2:]],
                "terminal",
                receipt_summaries=summaries,
            )

    def test_render_refuses_malformed_receipt_summaries(self) -> None:
        receipts = [
            Path(f"/receipts/{method_id}.json")
            for method_id in MODULE.REPORT_METHOD_IDS
        ]

        for field, value, message in (
            ("legacy_source_manifest", "0" * 64, "summary envelope is not exact"),
            ("destination_prefix", "s3://wrong/", "destination is malformed"),
            ("receipt_sha256", "not-a-sha", "SHA-256 is malformed"),
            ("receipt_sha256", int("1" * 64), "SHA-256 is malformed"),
            ("object_count", 0, "object count is malformed"),
            ("object_count", True, "object count is malformed"),
        ):
            with self.subTest(field=field, value=value):
                summaries = [dict(summary) for summary in receipt_summaries(receipts)]
                summaries[0][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    MODULE.render(
                        Path("/repo"),
                        receipts,
                        "terminal",
                        receipt_summaries=tuple(summaries),
                    )

    def test_required_existing_points_at_checked_in_scripts(self) -> None:
        prerequisites = {
            path.as_posix() for path in MODULE.required_existing(Path("/repo"))
        }

        self.assertEqual(
            prerequisites,
            {
                "/repo/scripts/hrd_report_inventory.py",
                "/repo/scripts/ai_model_catalog.py",
                "/repo/scripts/build_ai_review_bundle.py",
                "/repo/scripts/runbook_io.py",
                "/repo/scripts/forbidden_text.py",
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
                "/repo/.codex-tmp/public-index/objects.json",
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
        summaries = receipt_summaries()

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
