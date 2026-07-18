from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
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

SPEC = importlib.util.spec_from_file_location(
    "render_ai_synthesis_runbook", SCRIPT_DIR / "render_ai_synthesis_runbook.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checksum_from_digest(value: str) -> str:
    return base64.b64encode(bytes.fromhex(value)).decode("ascii")


def write_manifest_files(root: Path, payload: bytes = b"{}\n") -> dict[str, Path]:
    paths = MODULE.report_manifest_paths(root)
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return paths


def write_receipts(root: Path, manifest_paths: dict[str, Path]) -> list[Path]:
    receipts: list[Path] = []
    receipt_root = root / "receipts"
    receipt_root.mkdir(exist_ok=True)
    for method_id in MODULE.REQUIRED_METHOD_IDS:
        expected = tuple(sorted(PUBLISH.METHOD_CONTRACTS[method_id]["files"]))
        prefix = (
            f"s3://{PUBLISH.PRIVATE_BUCKET}/runs/{MODULE.SUBJECT_ALIAS}/"
            f"{MODULE.RUN_ID}/reports/{method_id}/revisions/{'a' * 64}/"
        )
        key_prefix = prefix.removeprefix(f"s3://{PUBLISH.PRIVATE_BUCKET}/")
        rows = []
        for index, relative in enumerate(expected, 1):
            sha256 = (
                digest(manifest_paths[method_id].read_bytes())
                if relative == "report_manifest.json"
                else f"{index:064x}"
            )
            key = key_prefix + relative
            rows.append(
                {
                    "relative_path": relative,
                    "bucket": PUBLISH.PRIVATE_BUCKET,
                    "key": key,
                    "uri": f"s3://{PUBLISH.PRIVATE_BUCKET}/{key}",
                    "version_id": f"version-{index}",
                    "bytes": index + 100,
                    "sha256": sha256,
                    "checksum_sha256": checksum_from_digest(sha256),
                    "checksum_type": "FULL_OBJECT",
                    "server_side_encryption": "aws:kms",
                    "kms_key_id": PUBLISH.PRIVATE_KMS_KEY_ARN,
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
            "kms_key_arn": PUBLISH.PRIVATE_KMS_KEY_ARN,
            "expected_files": list(expected),
            "object_count": len(expected),
            "passed_count": len(expected),
            "objects": rows,
        }
        path = receipt_root / f"{method_id}.json"
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        receipts.append(path)
    return receipts


class RenderAiSynthesisRunbookTests(unittest.TestCase):
    def test_renderer_prepares_ai_review_run_atomically(self) -> None:
        text = MODULE.render(Path("/repo"), "unit")

        self.assertIn("/repo/scripts/prepare_ai_review_run.py", text)
        self.assertNotIn("build_ai_review_bundle.py", text)
        self.assertNotIn("stage_ai_review_inputs.py", text)

        previous = -1
        for index, (method_id, argument) in enumerate(MODULE.METHOD_ARGUMENTS):
            flag = "--" + argument.replace("_", "-")
            self.assertEqual(method_id, MODULE.REQUIRED_METHOD_IDS[index])
            self.assertEqual(text.count(flag), 1)
            index = text.find(flag, previous + 1)
            self.assertGreater(index, previous)
            previous = index

        self.assertIn(
            "/repo/.codex-tmp/hrd-reports/ai-review/"
            f"{MODULE.RUN_ID}/reviewer-inputs/reviewer-a-input/review_bundle.json",
            text,
        )
        self.assertIn(
            "/repo/.codex-tmp/hrd-reports/ai-review/"
            f"{MODULE.RUN_ID}/reviewer-inputs/reviewer-b-input/reviewer-b.prompt.md",
            text,
        )

    def test_renderer_validates_and_publishes_checked_in_outputs(self) -> None:
        text = MODULE.render(Path("/repo"), "terminal")

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
        self.assertEqual(text.count("--packet-dir "), 3)
        self.assertNotIn("--source-dir", text)
        self.assertNotIn("--expected-file", text)
        self.assertNotIn("--receipt-upload-output", text)

    def test_ai_private_receipt_table_drives_publish_and_handoff(self) -> None:
        root = Path("/repo")
        text = MODULE.render(Path("/repo"), "terminal")
        receipt_paths = MODULE.ai_private_receipt_paths(root, "terminal")

        self.assertEqual(
            tuple(method_id for method_id, _ in MODULE.AI_PRIVATE_RECEIPT_STEMS),
            (*MODULE.AI_REVIEW_METHOD_IDS, *MODULE.COMPARATIVE_METHOD_IDS),
        )
        self.assertEqual(
            MODULE.ai_private_receipt_outputs(root, "terminal"),
            tuple(
                (MODULE.AI_PRIVATE_RECEIPT_STEMS[index][0], receipt_path)
                for index, receipt_path in enumerate(receipt_paths)
            ),
        )
        self.assertEqual(
            MODULE.required_absent(root, "terminal")[3:6],
            receipt_paths,
        )
        for receipt_path in receipt_paths:
            self.assertIn(f"--receipt-output {receipt_path}", text)
            self.assertIn(f"--private-publication-receipt {receipt_path}", text)

    def test_reviewed_publication_receipts_reuse_source_and_ai_helpers(self) -> None:
        root = Path("/repo")

        self.assertEqual(
            MODULE.reviewed_publication_receipt_paths(root, "terminal"),
            (
                *(
                    RUNBOOK_IO.source_private_receipt_path(
                        root, "terminal", method_id
                    )
                    for method_id in MODULE.REQUIRED_METHOD_IDS
                ),
                *MODULE.ai_private_receipt_paths(root, "terminal"),
            ),
        )

    def test_required_existing_points_at_checked_in_scripts(self) -> None:
        prerequisites = {
            path.as_posix() for path in MODULE.required_existing(Path("/repo"))
        }

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
        outputs = {
            path.as_posix()
            for path in MODULE.required_absent(Path("/repo"), "unit")
        }

        for path in (
            "/repo/.codex-tmp/hrd-reports/ai-review/model-catalog-receipts/"
            f"{MODULE.RUN_ID}/{MODULE.MODEL_CATALOG_RECEIPT}",
            "/repo/.codex-tmp/hrd-reports/ai-review/"
            f"{MODULE.RUN_ID}",
            "/repo/.codex-tmp/hrd-reports/synthesis/"
            f"{MODULE.RUN_ID}",
            "/repo/.codex-tmp/hrd-reports/ai-review/"
            f"{MODULE.RUN_ID}/publication-receipts/"
            "unit.ai-reviewer-a.private.json",
            "/repo/.codex-tmp/hrd-reports/ai-review/"
            f"{MODULE.RUN_ID}/publication-receipts/"
            "unit.comparative-synthesis.private.json",
            "/repo/.codex-tmp/hrd-reports/publication/"
            "unit.deterministic_full_wgs.public.dry.json",
            "/repo/.codex-tmp/hrd-reports/publication/"
            "unit.comparative_hrd_synthesis.public.json",
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

            stale = (
                root
                / ".codex-tmp/hrd-reports/ai-review"
                / MODULE.RUN_ID
            )
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
            manifests = write_manifest_files(root, b"manifest\n")
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
                MODULE.validate_private_report_receipts(
                    [receipts[1], receipts[0], *receipts[2:]], manifests
                )
            with self.assertRaisesRegex(ValueError, "exactly seven"):
                MODULE.validate_private_report_receipts(receipts[:-1], manifests)

            manifests[MODULE.REQUIRED_METHOD_IDS[0]].write_bytes(b"stale\n")
            with self.assertRaisesRegex(ValueError, "receipt-bound"):
                MODULE.validate_private_report_receipts(receipts, manifests)

    def test_private_freeze_gate_rejects_non_exact_private_receipts(self) -> None:
        cases = {
            "wrong_run": lambda receipt: receipt.update({"run_id": "other-run"}),
            "wrong_kms": lambda receipt: receipt.update({"kms_key_arn": "wrong"}),
            "wrong_prefix": lambda receipt: receipt.update(
                {
                    "destination_prefix": (
                        f"s3://{PUBLISH.PRIVATE_BUCKET}/runs/"
                        f"{MODULE.SUBJECT_ALIAS}/{MODULE.RUN_ID}/reports/other_method/"
                    )
                }
            ),
            "null_version": lambda receipt: receipt["objects"][0].update(
                {"version_id": "null"}
            ),
            "failed_check": lambda receipt: receipt["objects"][0]["checks"].update(
                {"kms": False}
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifests = write_manifest_files(root, b"manifest\n")
                receipts = write_receipts(root, manifests)
                receipt = json.loads(receipts[0].read_text())
                mutate(receipt)
                receipts[0].write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n"
                )

                with self.assertRaises(ValueError):
                    MODULE.validate_private_report_receipts(receipts, manifests)

    def test_report_manifest_paths_match_current_blocked_generator_dirs(self) -> None:
        root = Path("/repo")
        paths = MODULE.report_manifest_paths(root)

        for method in BLOCKED_GENERATOR.METHODS:
            self.assertEqual(
                paths[method["method_id"]],
                root
                / ".codex-tmp/hrd-reports/blocked-crosschecks"
                / method["directory"]
                / "report_manifest.json",
            )
        self.assertEqual(tuple(paths), MODULE.REQUIRED_METHOD_IDS)

    def test_renderer_hands_ten_private_receipts_to_public_renderer(self) -> None:
        text = MODULE.render(Path("/repo"), "terminal")

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
        for receipt_path in MODULE.reviewed_publication_receipt_paths(
            Path("/repo"), "terminal"
        ):
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
                "/repo/.codex-tmp/hrd-reports/ai-review/"
                f"{MODULE.RUN_ID}/publication-receipts/"
                f"{receipt}",
                text,
            )

    def test_reviewed_publication_runbook_command_has_exact_output_argv(self) -> None:
        output = Path("/repo/.codex-tmp/hrd-reports/publication/runbook.md")
        command = MODULE.reviewed_publication_runbook_command(
            Path("/repo/scripts"),
            Path("/repo"),
            output,
            [Path("/receipts/a.json"), Path("/receipts/b.json")],
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
            Path(
                "/repo/.codex-tmp/hrd-reports/ai-review/"
                f"{MODULE.RUN_ID}/bundle"
            ),
            Path(
                "/repo/.codex-tmp/hrd-reports/ai-review/"
                f"{MODULE.RUN_ID}/reviewer-a"
            ),
            Path(
                "/repo/.codex-tmp/hrd-reports/ai-review/"
                f"{MODULE.RUN_ID}/reviewer-b"
            ),
            Path("/repo/.codex-tmp/hrd-reports/synthesis" f"/{MODULE.RUN_ID}"),
        )

        self.assertEqual(
            command,
            [
                "python3",
                Path("/repo/scripts/generate_comparative_hrd_synthesis.py"),
                "--source-manifest",
                Path(
                    "/repo/.codex-tmp/hrd-reports/deterministic-full/"
                    "report/report_manifest.json"
                ),
                "--source-manifest",
                Path(
                    "/repo/results/rosalind_hrd/diana_wgs/"
                    f"{MODULE.RUN_ID}/report_manifest.json"
                ),
                "--source-manifest",
                Path(
                    "/repo/.codex-tmp/hrd-reports/crosschecks/"
                    "sequenza_scarhrd/report_manifest.json"
                ),
                "--source-manifest",
                Path(
                    "/repo/.codex-tmp/hrd-reports/crosschecks/"
                    "sigprofiler_sbs3/report_manifest.json"
                ),
                "--source-manifest",
                Path(
                    "/repo/.codex-tmp/hrd-reports/blocked-crosschecks/"
                    "facets_scarhrd_blocked/report_manifest.json"
                ),
                "--source-manifest",
                Path(
                    "/repo/.codex-tmp/hrd-reports/blocked-crosschecks/"
                    "oncoanalyser_chord_blocked/report_manifest.json"
                ),
                "--source-manifest",
                Path(
                    "/repo/.codex-tmp/hrd-reports/blocked-crosschecks/"
                    "hrdetect_blocked/report_manifest.json"
                ),
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
                Path(
                    "/repo/.codex-tmp/hrd-reports/ai-review/"
                    f"{MODULE.RUN_ID}/bundle/review_bundle.json"
                ),
                "--bundle-manifest",
                Path(
                    "/repo/.codex-tmp/hrd-reports/ai-review/"
                    f"{MODULE.RUN_ID}/bundle/bundle_manifest.json"
                ),
                "--reviewer-a-dir",
                Path(
                    "/repo/.codex-tmp/hrd-reports/ai-review/"
                    f"{MODULE.RUN_ID}/reviewer-a"
                ),
                "--reviewer-b-dir",
                Path(
                    "/repo/.codex-tmp/hrd-reports/ai-review/"
                    f"{MODULE.RUN_ID}/reviewer-b"
                ),
                "--output-dir",
                Path("/repo/.codex-tmp/hrd-reports/synthesis" f"/{MODULE.RUN_ID}"),
            ],
        )

    def test_renderer_materializes_pinned_model_catalog_receipt(self) -> None:
        text = MODULE.render(Path("/repo"), "terminal")
        catalog = (
            "/repo/.codex-tmp/hrd-reports/ai-review/model-catalog-receipts/"
            f"{MODULE.RUN_ID}/"
            "model-catalog-receipt.20260717T115311Z.json"
        )

        self.assertIn("/repo/scripts/write_ai_model_catalog_receipt.py", text)
        self.assertIn(f"--output {catalog}", text)
        self.assertIn(f"--model-catalog-receipt {catalog}", text)
        self.assertIn("--attest-models-latest", text)
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
        catalog = (
            root
            / ".codex-tmp/hrd-reports/ai-review/model-catalog-receipts"
            / MODULE.RUN_ID
            / MODULE.MODEL_CATALOG_RECEIPT
        )
        run_root = (
            root
            / ".codex-tmp/hrd-reports/ai-review"
            / MODULE.RUN_ID
        )

        self.assertEqual(MODULE.model_catalog_receipt_path(root), catalog)
        self.assertFalse(
            catalog.is_relative_to(run_root)
        )

    def test_runbook_can_include_private_receipt_gate(self) -> None:
        summaries = (
            {
                "method_id": "deterministic_full_wgs",
                "receipt": "receipt.json",
                "destination_prefix": "s3://private/",
                "report_manifest_version_id": "version-1",
                "report_manifest_sha256": "a" * 64,
                "object_count": 5,
            },
        )

        text = MODULE.render(
            Path("/repo"),
            "unit",
            receipt_summaries=summaries,
        )

        self.assertIn("## 0. Private publication receipt gate", text)
        self.assertIn("VersionId `version-1`", text)

    def test_renderer_has_no_template_placeholders(self) -> None:
        text = MODULE.render(Path("/repo"), "unit")

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
