from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import re
import shlex
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import generate_blocked_hrd_crosscheck_reports as BLOCKED_GENERATOR  # noqa: E402
import publish_reviewed_public_report as PUBLISH  # noqa: E402
import render_reviewed_publication_runbook as REVIEWED_PUBLIC  # noqa: E402
import runbook_io as RUNBOOK_IO  # noqa: E402

SPEC = importlib.util.spec_from_file_location("render_ai_synthesis_runbook", SCRIPT_DIR / "render_ai_synthesis_runbook.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checksum_from_digest(value: str) -> str:
    return base64.b64encode(bytes.fromhex(value)).decode("ascii")


def write_manifest_files(root: Path) -> dict[str, Path]:
    paths = MODULE.report_manifest_paths(root)
    for method_id, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        report = path.parent / "report.md"
        report.write_text(f"# {method_id}\n\nAuthorized HRD state: `no_call`\n")
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "method_id": method_id,
                    "report_sha256": digest(report.read_bytes()),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    return paths


def write_receipts(root: Path, manifest_paths: dict[str, Path]) -> list[Path]:
    receipts: list[Path] = []
    receipt_root = root / "receipts"
    receipt_root.mkdir(exist_ok=True)
    for method_id in MODULE.REQUIRED_METHOD_IDS:
        expected = tuple(sorted(PUBLISH.METHOD_CONTRACTS[method_id]["files"]))
        rows = []
        for index, relative in enumerate(expected, 1):
            sha256 = digest(manifest_paths[method_id].read_bytes()) if relative == "report_manifest.json" else f"{index:064x}"
            rows.append(
                {
                    "relative_path": relative,
                    "version_id": f"version-{index}",
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
        prefix = f"s3://{PUBLISH.PRIVATE_BUCKET}/runs/{MODULE.SUBJECT_ALIAS}/{MODULE.RUN_ID}/reports/{method_id}/revisions/{revision}/"
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
            "subject_alias": MODULE.SUBJECT_ALIAS,
            "run_id": MODULE.RUN_ID,
            "method_id": method_id,
            "packet_revision": revision,
            "source_packet_dir": str(
                (root / "packets" / method_id).resolve()
            ),
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


def receipt_summaries() -> tuple[dict[str, str | int], ...]:
    return tuple(
        {
            "method_id": method_id,
            "receipt": f"{method_id}.private.json",
            "destination_prefix": (
                f"s3://{PUBLISH.PRIVATE_BUCKET}/runs/{MODULE.SUBJECT_ALIAS}/"
                f"{MODULE.RUN_ID}/reports/{method_id}/"
                f"revisions/{index:064x}/"
            ),
            "report_manifest_version_id": f"version-{index}",
            "report_manifest_sha256": f"{index:064x}",
            "object_count": 5,
        }
        for index, method_id in enumerate(MODULE.REQUIRED_METHOD_IDS, 1)
    )


def render(root: Path = Path("/repo"), receipt_stem: str = "terminal") -> str:
    return MODULE.render(
        root,
        receipt_stem,
        receipt_summaries=receipt_summaries(),
    )


def rendered_commands(text: str) -> list[list[str]]:
    return [shlex.split(source) for source in re.findall(r"```bash\n(.*?)\n```", text, re.DOTALL)]


class RenderAiSynthesisRunbookTests(unittest.TestCase):
    def test_renderer_prepares_ai_review_run_atomically(self) -> None:
        text = render(receipt_stem="unit")

        self.assertIn("/repo/scripts/prepare_ai_review_run.py", text)
        self.assertIn(
            "--inventory-id diana_wgs_hrd_report_set_v1",
            text,
        )
        self.assertEqual(text.count("--inventory-id "), 1)
        self.assertNotIn("build_ai_review_bundle.py", text)
        self.assertNotIn("stage_ai_review_inputs.py", text)

        previous = -1
        for index, (method_id, argument) in enumerate(
            zip(MODULE.REQUIRED_METHOD_IDS, MODULE.MANIFEST_ARGUMENTS)
        ):
            flag = "--" + argument.replace("_", "-")
            self.assertEqual(method_id, MODULE.REQUIRED_METHOD_IDS[index])
            self.assertEqual(text.count(flag), 1)
            index = text.find(flag, previous + 1)
            self.assertGreater(index, previous)
            previous = index

        self.assertIn(
            f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/reviewer-inputs/reviewer-a-input/review_bundle.json",
            text,
        )
        self.assertIn(
            f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/reviewer-inputs/reviewer-b-input/reviewer-b.prompt.md",
            text,
        )
        for method_id, path in MODULE.report_manifest_paths(Path("/repo")).items():
            self.assertIn(
                f"- `{method_id}`: `{path}` -> `report_manifest.json`",
                text,
            )

    def test_renderer_validates_and_publishes_checked_in_outputs(self) -> None:
        text = render()

        self.assertEqual(text.count("--source-manifest "), 21)
        self.assertEqual(text.count("--require-method "), 7)
        self.assertLess(
            text.index("generate_comparative_hrd_synthesis.py"),
            text.index("finalize_ai_review.py"),
        )
        for method_id in (
            "ai_review_reviewer_a",
            "ai_review_reviewer_b",
            "comparative_hrd_synthesis",
        ):
            self.assertIn(f"--method-id {method_id}", text)
        self.assertEqual(text.count("--packet-dir "), 6)
        self.assertNotIn("--source-dir", text)
        self.assertNotIn("--expected-file", text)
        self.assertNotIn("--receipt-upload-output", text)

    def test_ai_private_receipt_table_drives_publish_and_handoff(self) -> None:
        root = Path("/repo")
        text = render()
        receipt_paths = MODULE.ai_private_receipt_paths(root, "terminal")
        commands = rendered_commands(text)
        publish_commands = [
            command
            for command in commands
            if command[:2] == ["python3", "/repo/scripts/publish_private_report.py"]
            and command[command.index("--method-id") + 1] in (*MODULE.AI_REVIEW_METHOD_IDS, *MODULE.COMPARATIVE_METHOD_IDS)
        ]

        self.assertEqual(
            tuple(method_id for method_id, _ in MODULE.AI_PRIVATE_RECEIPT_STEMS),
            (*MODULE.AI_REVIEW_METHOD_IDS, *MODULE.COMPARATIVE_METHOD_IDS),
        )
        self.assertEqual(
            MODULE.ai_private_receipt_outputs(root, "terminal"),
            tuple((MODULE.AI_PRIVATE_RECEIPT_STEMS[index][0], receipt_path) for index, receipt_path in enumerate(receipt_paths)),
        )
        self.assertEqual(
            MODULE.required_absent(root, "terminal")[3:6],
            MODULE.ai_private_receipt_paths(root, "terminal", ".dry"),
        )
        self.assertEqual(
            MODULE.required_absent(root, "terminal")[6:9],
            receipt_paths,
        )
        self.assertEqual(
            tuple(
                Path(command[command.index("--receipt-output") + 1])
                for command in publish_commands
                if "--apply" in command
            ),
            receipt_paths,
        )
        for receipt_path in receipt_paths:
            self.assertIn(f"--private-publication-receipt {receipt_path}", text)
            self.assertNotIn(f"{receipt_path}.private.json", text)

    def test_ai_private_apply_commands_require_matching_dry_receipts(self) -> None:
        root = Path("/repo")
        text = render()

        for method_id, apply_receipt in MODULE.ai_private_receipt_outputs(
            root,
            "terminal",
        ):
            dry_receipt = dict(
                MODULE.ai_private_receipt_outputs(root, "terminal", ".dry")
            )[method_id]
            dry_index = text.index(f"--receipt-output {dry_receipt}")
            apply_index = text.index(f"--receipt-output {apply_receipt}")
            dry_ref_index = text.index(f"--dry-run-receipt {dry_receipt}")
            self.assertLess(dry_index, apply_index)
            self.assertLess(apply_index, dry_ref_index)

        with self.assertRaisesRegex(ValueError, "requires a dry-run receipt"):
            MODULE.publish_command(
                Path("/repo/scripts"),
                Path("/repo/reviewer-a"),
                "ai_review_reviewer_a",
                root / "ai-reviewer-a.private.json",
                apply=True,
            )
        with self.assertRaisesRegex(ValueError, "only valid with --apply"):
            MODULE.publish_command(
                Path("/repo/scripts"),
                Path("/repo/reviewer-a"),
                "ai_review_reviewer_a",
                root / "ai-reviewer-a.private.dry.json",
                apply=False,
                dry_run_receipt=root / "ai-reviewer-a.private.dry.json",
            )

    def test_ai_private_publish_checklists_are_concrete(self) -> None:
        root = Path("/repo")
        text = render()
        report_root = f"{root}/.codex-tmp/hrd-reports"
        packet_dirs = {
            MODULE.AI_REVIEW_METHOD_IDS[0]: (
                f"{report_root}/ai-review/{MODULE.RUN_ID}/reviewer-a"
            ),
            MODULE.AI_REVIEW_METHOD_IDS[1]: (
                f"{report_root}/ai-review/{MODULE.RUN_ID}/reviewer-b"
            ),
            MODULE.COMPARATIVE_METHOD_IDS[0]: (
                f"{report_root}/synthesis/{MODULE.RUN_ID}"
            ),
        }

        for method_id, apply_receipt in MODULE.ai_private_receipt_outputs(
            root,
            "terminal",
        ):
            dry_receipt = dict(
                MODULE.ai_private_receipt_outputs(root, "terminal", ".dry")
            )[method_id]
            review = text.index(
                f"Review `{dry_receipt}` before private AI report apply:"
            )
            apply = text.index(f"--receipt-output {apply_receipt}", review)
            checklist = text[review:apply]

            self.assertIn(f"`method_id` is `{method_id}`", checklist)
            self.assertIn(
                f"`source_packet_dir` is `{packet_dirs[method_id]}`",
                checklist,
            )
            self.assertIn("`expected_files`", checklist)
            self.assertIn("no extra files", checklist)
            self.assertIn("`forbidden_token_count`", checklist)
            self.assertIn("`forbidden_token_sha256`", checklist)
            self.assertIn("`checks.packet_inventory_exact`", checklist)
            self.assertIn("`checks.packet_manifest_no_call_boundary`", checklist)
            self.assertIn("`checks.packet_report_kind_exact`", checklist)
            self.assertIn("`checks.packet_forbidden_token_scan`", checklist)
            self.assertIn(f"`{apply_receipt}` does not already exist", checklist)
            self.assertIn("no version history", checklist)
            self.assertIn("`checks.dry_run_receipt`", checklist)
            self.assertIn("`checks.destination_initially_empty`", checklist)
            self.assertIn("`checks.destination_sse_kms`", checklist)
            self.assertIn("`checks.destination_full_object_sha256`", checklist)
            self.assertIn("`checks.destination_non_null_versions`", checklist)
            self.assertIn(
                "`checks.destination_exact_one_version_no_delete_history`",
                checklist,
            )
            self.assertIn("`--apply` command", checklist)

    def test_reviewer_output_checklists_are_concrete(self) -> None:
        text = render()
        review_root = (
            f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}"
        )

        for reviewer, suffix in (("A", "a"), ("B", "b")):
            input_dir = f"{review_root}/reviewer-inputs/reviewer-{suffix}-input"
            review_dir = f"{review_root}/reviewer-{suffix}"
            review = text.index(
                f"Review Reviewer {reviewer} output in `{review_dir}` "
                "before validation:"
            )
            validate = text.index(
                f"--reviewer {reviewer} --review-dir {review_dir}",
                review,
            )
            checklist = text[review:validate]

            self.assertIn(f"`{input_dir}/review_bundle.json`", checklist)
            self.assertIn(f"`{input_dir}/reviewer-{suffix}.prompt.md`", checklist)
            self.assertIn("did not receive the other reviewer's", checklist)
            self.assertIn("`report.md`, `claims.csv`, and `review_manifest.json`", checklist)
            self.assertIn("catalog-pinned model", checklist)
            self.assertIn("unique invocation", checklist)
            self.assertIn("independence attestation", checklist)
            self.assertIn("allowed states", checklist)
            self.assertIn("authorized ceiling", checklist)
            self.assertIn("no raw-data paths", checklist)
            self.assertIn("private identifiers", checklist)
            self.assertIn("`validate_ai_review.py`", checklist)

    def test_renderer_hands_forbidden_tokens_file_to_ai_chain(self) -> None:
        text = MODULE.render(
            Path("/repo"),
            "terminal",
            receipt_summaries=receipt_summaries(),
            forbidden_tokens_file=Path("/fast/forbidden_tokens.json"),
        )
        commands = rendered_commands(text)
        prepare_commands = [command for command in commands if command[:2] == ["python3", "/repo/scripts/prepare_ai_review_run.py"]]
        validate_commands = [command for command in commands if command[:2] == ["python3", "/repo/scripts/validate_ai_review.py"]]
        publish_commands = [
            command
            for command in commands
            if command[:2] == ["python3", "/repo/scripts/publish_private_report.py"]
            and command[command.index("--method-id") + 1] in (*MODULE.AI_REVIEW_METHOD_IDS, *MODULE.COMPARATIVE_METHOD_IDS)
        ]

        self.assertEqual(len(prepare_commands), 1)
        self.assertEqual(len(validate_commands), 2)
        self.assertEqual(len(publish_commands), 6)
        self.assertEqual(
            text.count("--forbidden-tokens-file /fast/forbidden_tokens.json"),
            10,
        )
        for command in (*prepare_commands, *validate_commands, *publish_commands):
            self.assertEqual(command.count("--forbidden-tokens-file"), 1)
            self.assertEqual(
                command[command.index("--forbidden-tokens-file") + 1],
                "/fast/forbidden_tokens.json",
            )
        self.assertNotIn("Unit-Run-Private-Token", text)
        reviewed_public_commands = [
            command
            for command in commands
            if "/repo/scripts/render_reviewed_publication_runbook.py" in command
        ]
        self.assertEqual(len(reviewed_public_commands), 1)
        self.assertEqual(
            reviewed_public_commands[0].count("--forbidden-tokens-file"),
            1,
        )
        self.assertEqual(
            reviewed_public_commands[0][
                reviewed_public_commands[0].index("--forbidden-tokens-file") + 1
            ],
            "/fast/forbidden_tokens.json",
        )

    def test_reviewed_publication_receipts_reuse_source_and_ai_helpers(self) -> None:
        root = Path("/repo")

        self.assertEqual(
            MODULE.reviewed_publication_receipt_paths(root, "terminal"),
            (
                *(RUNBOOK_IO.source_private_receipt_path(root, "terminal", method_id) for method_id in MODULE.REQUIRED_METHOD_IDS),
                *MODULE.ai_private_receipt_paths(root, "terminal"),
            ),
        )

    def test_required_existing_points_at_checked_in_scripts(self) -> None:
        prerequisites = {path.as_posix() for path in MODULE.required_existing(Path("/repo"))}

        for expected in (
            "/repo/scripts/write_ai_model_catalog_receipt.py",
            "/repo/scripts/hrd_report_inventory.py",
            "/repo/scripts/ai_model_catalog.py",
            "/repo/scripts/forbidden_text.py",
            "/repo/scripts/prepare_ai_review_run.py",
            "/repo/scripts/build_ai_review_bundle.py",
            "/repo/scripts/stage_ai_review_inputs.py",
            "/repo/scripts/validate_ai_review.py",
            "/repo/scripts/finalize_ai_review.py",
            "/repo/scripts/generate_comparative_hrd_synthesis.py",
            "/repo/scripts/publish_private_report.py",
            "/repo/scripts/render_reviewed_publication_runbook.py",
            "/repo/scripts/runbook_io.py",
            "/repo/scripts/publish_reviewed_public_report.py",
            "/repo/scripts/build_public_results_index.py",
            "/repo/scripts/publish_public_results_index.py",
        ):
            self.assertIn(expected, prerequisites)
        for stale in (
            ".codex-tmp/hrd-reports/method_inventory.py",
            ".codex-tmp/hrd-reports/ai-review/stage_reviewer_inputs.py",
            ".codex-tmp/hrd-reports/ai-review/build_review_bundle.py",
        ):
            self.assertNotIn("/repo/" + stale, prerequisites)

    def test_required_absent_includes_child_create_only_outputs(self) -> None:
        outputs = {path.as_posix() for path in MODULE.required_absent(Path("/repo"), "unit")}

        for path in (
            f"/repo/.codex-tmp/hrd-reports/ai-review/model-catalog-receipts/{MODULE.RUN_ID}/{MODULE.MODEL_CATALOG_RECEIPT}",
            f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}",
            f"/repo/.codex-tmp/hrd-reports/synthesis/{MODULE.RUN_ID}",
            f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/publication-receipts/unit.ai-reviewer-a.private.json",
            f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/publication-receipts/unit.comparative-synthesis.private.json",
            "/repo/.codex-tmp/hrd-reports/publication/unit.deterministic_full_wgs.public.dry.json",
            "/repo/.codex-tmp/hrd-reports/publication/unit.comparative_hrd_synthesis.public.json",
            "/repo/.codex-tmp/public-index/public-index.unit.json",
        ):
            self.assertIn(path, outputs)

    def test_required_absent_reuses_reviewed_public_renderer_contract(self) -> None:
        required_absent = MODULE.required_absent(Path("/repo"), "unit")
        reviewed_public = REVIEWED_PUBLIC.required_absent(Path("/repo"), "unit")

        start = required_absent.index(reviewed_public[0])
        self.assertEqual(
            required_absent[start : start + len(reviewed_public)],
            reviewed_public,
        )

    def test_main_rejects_preexisting_child_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path in MODULE.required_existing(root):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")

            stale = root / ".codex-tmp/hrd-reports/ai-review" / MODULE.RUN_ID
            stale.mkdir(parents=True)
            output = root / "ai-review.md"
            argv = [
                "render_ai_synthesis_runbook.py",
                "--output",
                str(output),
                "--root",
                str(root),
            ]
            for method_id in MODULE.REQUIRED_METHOD_IDS:
                argv.extend(
                    [
                        "--private-publication-receipt",
                        str(root / f"{method_id}.json"),
                    ]
                )

            with (
                patch.object(sys, "argv", argv),
                self.assertRaisesRegex(SystemExit, "create-only outputs"),
            ):
                MODULE.main()

            self.assertFalse(output.exists())

    def test_private_freeze_gate_accepts_current_checked_in_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifests = write_manifest_files(root)
            receipts = write_receipts(root, manifests)

            summaries = MODULE.validate_private_report_receipts(receipts, manifests)

            self.assertEqual(
                [summary["method_id"] for summary in summaries],
                list(MODULE.REQUIRED_METHOD_IDS),
            )
            self.assertEqual(
                summaries[0]["report_manifest_sha256"],
                digest(manifests[MODULE.REQUIRED_METHOD_IDS[0]].read_bytes()),
            )

            with self.assertRaisesRegex(ValueError, "canonical"):
                MODULE.validate_private_report_receipts([receipts[1], receipts[0], *receipts[2:]], manifests)
            with self.assertRaisesRegex(ValueError, "exactly seven"):
                MODULE.validate_private_report_receipts(receipts[:-1], manifests)

            method_id = MODULE.REQUIRED_METHOD_IDS[0]
            stale_report = manifests[method_id].parent / "report.md"
            stale_report.write_text("# stale but still locally report-bound\n")
            manifests[method_id].write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "method_id": method_id,
                        "report_sha256": digest(stale_report.read_bytes()),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            with self.assertRaisesRegex(ValueError, "receipt-bound"):
                MODULE.validate_private_report_receipts(receipts, manifests)

            write_manifest_files(root)
            receipts = write_receipts(root, manifests)
            (manifests[MODULE.REQUIRED_METHOD_IDS[0]].parent / "report.md").write_text("# stale\n")
            with self.assertRaisesRegex(ValueError, "report-bound"):
                MODULE.validate_private_report_receipts(receipts, manifests)

    def test_private_freeze_gate_carries_stable_receipt_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifests = write_manifest_files(root)
            receipts = write_receipts(root, manifests)
            receipt = receipts[0]
            original = json.loads(receipt.read_text(encoding="utf-8"))
            original_version = next(
                row["version_id"]
                for row in original["objects"]
                if row["relative_path"] == "report_manifest.json"
            )
            real_load = MODULE.load_json_object_with_sha256

            def load_then_mutate_receipt(path: Path, label: str) -> tuple[dict, str]:
                payload, digest = real_load(path, label)
                if path == receipt and label == "private publication receipt":
                    mutated = json.loads(path.read_text(encoding="utf-8"))
                    for row in mutated["objects"]:
                        if row["relative_path"] == "report_manifest.json":
                            row["version_id"] = "tampered-version"
                    path.write_text(
                        json.dumps(mutated, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                return payload, digest

            with patch.object(
                MODULE,
                "load_json_object_with_sha256",
                side_effect=load_then_mutate_receipt,
            ):
                summaries = MODULE.validate_private_report_receipts(receipts, manifests)

            current = json.loads(receipt.read_text(encoding="utf-8"))
            current_version = next(
                row["version_id"]
                for row in current["objects"]
                if row["relative_path"] == "report_manifest.json"
            )
            self.assertEqual(
                summaries[0]["report_manifest_version_id"],
                original_version,
            )
            self.assertNotEqual(current_version, original_version)

    def test_private_freeze_gate_rejects_receipts_below_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifests = write_manifest_files(root)
            receipts = write_receipts(root, manifests)
            real_parent = root / "real-receipts"
            (root / "receipts").rename(real_parent)
            (root / "receipts").symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.validate_private_report_receipts(receipts, manifests)

    def test_private_freeze_gate_rejects_local_manifest_below_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifests = write_manifest_files(root)
            receipts = write_receipts(root, manifests)
            method_id = MODULE.REQUIRED_METHOD_IDS[0]

            real_parent = root / "real-reports"
            real_packet = real_parent / "existing"
            real_packet.mkdir(parents=True)
            linked_parent = root / "linked-reports"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            for filename in ("report.md", "report_manifest.json"):
                source = manifests[method_id].parent / filename
                (real_packet / filename).write_bytes(source.read_bytes())
            manifests[method_id] = linked_parent / "existing" / "report_manifest.json"

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.validate_private_report_receipts(receipts, manifests)

    def test_private_freeze_gate_rejects_non_exact_private_receipts(self) -> None:
        cases = {
            "wrong_run": lambda receipt: receipt.update({"run_id": "other-run"}),
            "wrong_kms": lambda receipt: receipt.update({"kms_key_arn": "wrong"}),
            "wrong_prefix": lambda receipt: receipt.update(
                {"destination_prefix": (f"s3://{PUBLISH.PRIVATE_BUCKET}/runs/{MODULE.SUBJECT_ALIAS}/{MODULE.RUN_ID}/reports/other_method/")}
            ),
            "null_version": lambda receipt: receipt["objects"][0].update({"version_id": "null"}),
            "failed_check": lambda receipt: receipt["objects"][0]["checks"].update({"kms": False}),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifests = write_manifest_files(root)
                receipts = write_receipts(root, manifests)
                receipt = json.loads(receipts[0].read_text())
                mutate(receipt)
                receipts[0].write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

                with self.assertRaises(ValueError):
                    MODULE.validate_private_report_receipts(receipts, manifests)

    def test_private_receipt_summary_uses_validated_destination_prefix(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            method_id = MODULE.REQUIRED_METHOD_IDS[0]
            manifest_dir = root / "reports" / method_id
            manifest_dir.mkdir(parents=True)
            report_path = manifest_dir / "report.md"
            report_path.write_text("# exact private report\n", encoding="utf-8")
            manifest_path = manifest_dir / "report_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "method_id": method_id,
                        "report_sha256": digest(report_path.read_bytes()),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            manifest_sha256 = digest(manifest_path.read_bytes())
            receipt_path = root / "receipts" / f"{method_id}.json"
            receipt_path.parent.mkdir()
            validated_prefix = (
                f"s3://{PUBLISH.PRIVATE_BUCKET}/runs/{MODULE.SUBJECT_ALIAS}/"
                f"{MODULE.RUN_ID}/reports/{method_id}/revisions/{'1' * 64}/"
            )
            private_receipt = {"destination_prefix": validated_prefix}
            rows = [
                {
                    "relative_path": "report_manifest.json",
                    "version_id": "validated-version",
                    "sha256": manifest_sha256,
                }
            ]

            def load_json_object_with_sha256(
                path: Path,
                label: str,
            ) -> tuple[dict[str, str], str]:
                if path == receipt_path:
                    raise AssertionError("private receipt was reread")
                self.assertEqual(path, manifest_path)
                return (
                    json.loads(path.read_text(encoding="utf-8")),
                    digest(path.read_bytes()),
                )

            with (
                patch.object(
                    MODULE,
                    "validate_private_receipt_payload",
                    return_value=(("report_manifest.json",), rows),
                ),
                patch.object(
                    MODULE,
                    "load_json_object_with_sha256",
                    side_effect=load_json_object_with_sha256,
                ),
            ):
                summary = MODULE.validate_private_report_receipt(
                    receipt_path,
                    private_receipt,
                    method_id,
                    manifest_path,
                )

            self.assertEqual(summary["destination_prefix"], validated_prefix)
            self.assertEqual(
                summary["report_manifest_version_id"],
                "validated-version",
            )
            self.assertEqual(summary["report_manifest_sha256"], manifest_sha256)

    def test_sha256_path_rejects_symlinked_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_input = root / "real.json"
            linked_input = root / "linked.json"
            real_input.write_text("{}\n", encoding="utf-8")
            linked_input.symlink_to(real_input)

            with self.assertRaisesRegex(
                ValueError,
                "linked.json SHA-256 input is missing or a symlink",
            ):
                MODULE.sha256_path(linked_input)

    def test_sha256_path_rejects_mid_read_rewrites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hash_input = root / "report.md"
            hash_input.write_text("# trusted report\n", encoding="utf-8")

            original_read_bytes = Path.read_bytes
            mutated = False

            def mutate_after_first_read(path: Path) -> bytes:
                nonlocal mutated
                data = original_read_bytes(path)
                if path == hash_input and not mutated:
                    mutated = True
                    path.write_text("# tampered report\n", encoding="utf-8")
                return data

            with (
                patch.object(Path, "read_bytes", mutate_after_first_read),
                self.assertRaisesRegex(
                    ValueError,
                    "report.md SHA-256 input changed during read",
                ),
            ):
                MODULE.sha256_path(hash_input)

    def test_report_manifest_paths_match_current_blocked_generator_dirs(self) -> None:
        root = Path("/repo")
        paths = MODULE.report_manifest_paths(root)

        for method in BLOCKED_GENERATOR.METHODS:
            self.assertEqual(
                paths[method["method_id"]],
                root / ".codex-tmp/hrd-reports/blocked-crosschecks" / method["directory"] / "report_manifest.json",
            )
        self.assertEqual(tuple(paths), MODULE.REQUIRED_METHOD_IDS)

    def test_report_manifest_paths_accept_phase3_fast_packet_overrides(self) -> None:
        root = Path("/repo")
        paths = MODULE.report_manifest_paths(
            root,
            sigprofiler_report_dir=Path("/fast/sigprofiler"),
            sequenza_report_dir=Path("/fast/sequenza"),
            deterministic_report_dir=Path("/fast/deterministic_report"),
            rosalind_report_dir=Path("/fast/rosalind_hrd/diana_wgs"),
            blocked_crosscheck_root=Path("/fast/blocked_crosschecks"),
        )
        text = MODULE.render(
            root,
            "terminal",
            sigprofiler_report_dir=Path("/fast/sigprofiler"),
            sequenza_report_dir=Path("/fast/sequenza"),
            receipt_summaries=receipt_summaries(),
            deterministic_report_dir=Path("/fast/deterministic_report"),
            rosalind_report_dir=Path("/fast/rosalind_hrd/diana_wgs"),
            blocked_crosscheck_root=Path("/fast/blocked_crosschecks"),
        )

        self.assertEqual(tuple(paths), MODULE.REQUIRED_METHOD_IDS)
        self.assertEqual(
            paths["deterministic_full_wgs"],
            Path("/fast/deterministic_report/report_manifest.json"),
        )
        self.assertEqual(
            paths["rosalind_diana_wgs"],
            Path("/fast/rosalind_hrd/diana_wgs/report_manifest.json"),
        )
        self.assertEqual(
            paths["facets_scarhrd_blocked"],
            Path("/fast/blocked_crosschecks/facets_scarhrd_blocked/report_manifest.json"),
        )
        for manifest_path in paths.values():
            self.assertIn(str(manifest_path), text)

    def test_renderer_hands_ten_private_receipts_to_public_renderer(self) -> None:
        text = render()

        self.assertIn("/repo/scripts/render_reviewed_publication_runbook.py", text)
        self.assertIn(
            "REVIEWED_PUBLIC_RUNBOOK=/repo/.codex-tmp/hrd-reports/publication/"
            "terminal.reviewed-public-runbook.$(date -u +%Y%m%dT%H%M%SZ).md",
            text,
        )
        self.assertIn('--output "$REVIEWED_PUBLIC_RUNBOOK" --root /repo', text)
        self.assertNotIn("terminal.reviewed-public-runbook.md\n", text)
        self.assertEqual(text.count("--private-publication-receipt "), 10)

        previous = -1
        for receipt_path in MODULE.reviewed_publication_receipt_paths(Path("/repo"), "terminal"):
            index = text.find(
                f"--private-publication-receipt {receipt_path}",
                previous + 1,
            )
            self.assertGreater(index, previous)
            previous = index

        for receipt in (
            "terminal.ai-reviewer-a.private.json",
            "terminal.ai-reviewer-b.private.json",
            "terminal.comparative-synthesis.private.json",
        ):
            self.assertIn(
                f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/publication-receipts/{receipt}",
                text,
            )

    def test_reviewed_publication_runbook_command_has_exact_output_argv(self) -> None:
        output = Path("/repo/.codex-tmp/hrd-reports/publication/runbook.md")
        command = MODULE.reviewed_publication_runbook_command(
            Path("/repo/scripts"),
            Path("/repo"),
            output,
            [Path("/receipts/a.json"), Path("/receipts/b.json")],
            "rerun",
            forbidden_tokens_file=Path("/fast/forbidden_tokens.json"),
        )

        self.assertEqual(
            command,
            [
                "python3",
                Path("/repo/scripts/render_reviewed_publication_runbook.py"),
                "--output",
                output,
                "--root",
                Path("/repo"),
                "--receipt-stem",
                "rerun",
                "--forbidden-tokens-file",
                Path("/fast/forbidden_tokens.json"),
                "--private-publication-receipt",
                Path("/receipts/a.json"),
                "--private-publication-receipt",
                Path("/receipts/b.json"),
            ],
        )

    def test_comparative_synthesis_command_has_exact_run_scoped_argv(self) -> None:
        command = MODULE.comparative_synthesis_command(
            Path("/repo/scripts"),
            MODULE.report_manifest_paths(Path("/repo")),
            Path(f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/bundle"),
            Path(f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/reviewer-a"),
            Path(f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/reviewer-b"),
            Path(f"/repo/.codex-tmp/hrd-reports/synthesis/{MODULE.RUN_ID}"),
        )

        self.assertEqual(
            command,
            [
                "python3",
                Path("/repo/scripts/generate_comparative_hrd_synthesis.py"),
                "--source-manifest",
                Path("/repo/.codex-tmp/hrd-reports/deterministic-full/report/report_manifest.json"),
                "--source-manifest",
                Path(f"/repo/results/rosalind_hrd/diana_wgs/{MODULE.RUN_ID}/report_manifest.json"),
                "--source-manifest",
                Path("/repo/.codex-tmp/hrd-reports/crosschecks/sequenza_scarhrd/report_manifest.json"),
                "--source-manifest",
                Path("/repo/.codex-tmp/hrd-reports/crosschecks/sigprofiler_sbs3/report_manifest.json"),
                "--source-manifest",
                Path("/repo/.codex-tmp/hrd-reports/blocked-crosschecks/facets_scarhrd_blocked/report_manifest.json"),
                "--source-manifest",
                Path("/repo/.codex-tmp/hrd-reports/blocked-crosschecks/oncoanalyser_chord_blocked/report_manifest.json"),
                "--source-manifest",
                Path("/repo/.codex-tmp/hrd-reports/blocked-crosschecks/hrdetect_blocked/report_manifest.json"),
                "--require-method",
                "deterministic_full_wgs",
                "--require-method",
                "rosalind_diana_wgs",
                "--require-method",
                "sequenza_scarhrd",
                "--require-method",
                "sigprofiler_sbs3",
                "--require-method",
                "facets_scarhrd_blocked",
                "--require-method",
                "oncoanalyser_chord_blocked",
                "--require-method",
                "hrdetect_blocked",
                "--review-bundle",
                Path(f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/bundle/review_bundle.json"),
                "--bundle-manifest",
                Path(f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/bundle/bundle_manifest.json"),
                "--reviewer-a-dir",
                Path(f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/reviewer-a"),
                "--reviewer-b-dir",
                Path(f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}/reviewer-b"),
                "--output-dir",
                Path(f"/repo/.codex-tmp/hrd-reports/synthesis/{MODULE.RUN_ID}"),
            ],
        )

    def test_renderer_materializes_pinned_model_catalog_receipt(self) -> None:
        text = render()
        catalog = (
            f"/repo/.codex-tmp/hrd-reports/ai-review/model-catalog-receipts/{MODULE.RUN_ID}/model-catalog-receipt.20260717T115311Z.json"
        )

        self.assertIn("/repo/scripts/write_ai_model_catalog_receipt.py", text)
        self.assertIn(f"--output {catalog}", text)
        self.assertIn(f"--model-catalog-receipt {catalog}", text)
        self.assertIn("--attest-models-latest", text)
        self.assertIn(f"Reviewer A model: `{MODULE.REVIEWER_A[0]}/{MODULE.REVIEWER_A[1]}`", text)
        self.assertIn(f"Reviewer B model: `{MODULE.REVIEWER_B[0]}/{MODULE.REVIEWER_B[1]}`", text)
        self.assertLess(
            text.index(f"Reviewer A model: `{MODULE.REVIEWER_A[0]}/{MODULE.REVIEWER_A[1]}`"),
            text.index("write_ai_model_catalog_receipt.py"),
        )
        self.assertLess(
            text.index(f"Reviewer B model: `{MODULE.REVIEWER_B[0]}/{MODULE.REVIEWER_B[1]}`"),
            text.index("write_ai_model_catalog_receipt.py"),
        )
        self.assertLess(
            text.index("write_ai_model_catalog_receipt.py"),
            text.index("prepare_ai_review_run.py"),
        )
        self.assertNotIn(
            "/repo/.codex-tmp/hrd-reports/ai-review/publication-receipts/",
            text,
        )

    def test_model_catalog_receipt_stays_outside_prepare_output_dir(self) -> None:
        root = Path("/repo")
        catalog = root / ".codex-tmp/hrd-reports/ai-review/model-catalog-receipts" / MODULE.RUN_ID / MODULE.MODEL_CATALOG_RECEIPT
        run_root = root / ".codex-tmp/hrd-reports/ai-review" / MODULE.RUN_ID

        self.assertEqual(MODULE.model_catalog_receipt_path(root), catalog)
        self.assertFalse(catalog.is_relative_to(run_root))

    def test_runbook_can_include_private_receipt_gate(self) -> None:
        summaries = receipt_summaries()

        text = MODULE.render(
            Path("/repo"),
            "unit",
            receipt_summaries=summaries,
        )

        self.assertIn("## 0. Private publication receipt gate", text)
        self.assertIn("VersionId `version-1`", text)

    def test_receipt_summaries_pin_prepare_source_manifest_sha256(self) -> None:
        summaries = tuple(
            dict(
                summary,
                report_manifest_sha256=f"{index + 1:064x}",
            )
            for index, summary in enumerate(receipt_summaries())
        )

        text = MODULE.render(
            Path("/repo"),
            "unit",
            receipt_summaries=summaries,
        )

        self.assertEqual(text.count("--expected-source-manifest-sha256 "), 7)
        previous = -1
        for summary in summaries:
            flag = f"--expected-source-manifest-sha256 {summary['method_id']}={summary['report_manifest_sha256']}"
            index = text.find(flag, previous + 1)
            self.assertGreater(index, previous)
            previous = index

    def test_render_refuses_missing_receipt_summaries(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires seven"):
            MODULE.render(Path("/repo"), "unit")

    def test_render_refuses_malformed_receipt_summaries(self) -> None:
        for field, value, message in (
            ("legacy_receipt_sha256", "0" * 64, "summary envelope is not exact"),
            ("destination_prefix", "s3://wrong/", "destination is malformed"),
            (
                "report_manifest_version_id",
                "null",
                "VersionId is malformed",
            ),
            (
                "report_manifest_version_id",
                True,
                "VersionId is malformed",
            ),
            (
                "report_manifest_sha256",
                "not-a-sha",
                "SHA-256 is malformed",
            ),
            (
                "report_manifest_sha256",
                int("1" * 64),
                "SHA-256 is malformed",
            ),
            ("receipt", True, "private receipt path is malformed"),
            ("receipt", " receipt.json", "private receipt path is malformed"),
            ("receipt", "receipt.json\n", "private receipt path is malformed"),
            ("object_count", 0, "object count is malformed"),
            ("object_count", True, "object count is malformed"),
        ):
            with self.subTest(field=field, value=value):
                summaries = [dict(summary) for summary in receipt_summaries()]
                summaries[0][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    MODULE.render(
                        Path("/repo"),
                        "unit",
                        receipt_summaries=tuple(summaries),
                    )

    def test_renderer_has_no_template_placeholders(self) -> None:
        text = render(receipt_stem="unit")

        for placeholder in (
            "PRIVATE" + "_",
            "REPLACE" + "_WITH",
            "EXACT" + "_",
            "ISO" + "_8601",
            "ISO" + "-8601",
        ):
            self.assertNotIn(placeholder, text)

    def test_write_once_is_mode_0600_and_refuses_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runbook.md"
            MODULE.write_once(output, "one\n")

            self.assertEqual(output.read_text(), "one\n")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.write_once(output, "two\n")


if __name__ == "__main__":
    unittest.main()
