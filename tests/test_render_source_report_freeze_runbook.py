from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
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
import runbook_io as RUNBOOK_IO  # noqa: E402
import validate_phase3_fast_report_packets as PHASE3_FAST_VALIDATOR  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "render_source_report_freeze_runbook",
    SCRIPT_DIR / "render_source_report_freeze_runbook.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_packet_dirs(paths: dict[str, Path]) -> None:
    for method_id, path in paths.items():
        if method_id in MODULE.BLOCKED_CROSSCHECK_METHOD_IDS:
            continue
        path.mkdir(parents=True)
        for relative in MODULE.METHOD_CONTRACTS[method_id]["files"]:
            if relative == "report_manifest.json":
                continue
            if relative.endswith(".json"):
                (path / relative).write_text('{"status":"partial_evidence"}\n', encoding="utf-8")
            elif relative.endswith(".csv"):
                (path / relative).write_text("field,value\nstate,no_call\n", encoding="utf-8")
            else:
                (path / relative).write_text(f"# {method_id}\n\nNo-call support packet.\n", encoding="utf-8")

        review_summary = {
            "overall": {
                "authorized_hrd_state": "no_call",
                "evidence_status": "partial_evidence",
            }
        }
        source_sha256 = {"fixture": "a" * 64}
        report_kind = MODULE.TERMINAL_SOURCE_REPORT_KINDS[method_id]
        route = None
        if method_id in MODULE.EXECUTABLE_CROSSCHECK_METHOD_IDS:
            source_sha256 = {
                "download_verification": "b" * 64,
                "source_report": "c" * 64,
                "source_report_manifest": "d" * 64,
            }
            report_kind = "executable_crosscheck_method"
            route = method_id
            (path / "method_spec.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "method_id": method_id,
                        "route": method_id,
                        "report_kind": report_kind,
                        "evidence_status": "partial_evidence",
                        "authorized_hrd_state": "no_call",
                        "classification_authorized": False,
                        "classification_qc_status": "not_applicable",
                        "source_object_count": 2,
                        "download_verification_sha256": source_sha256[
                            "download_verification"
                        ],
                        "source_report_sha256": source_sha256["source_report"],
                        "source_report_manifest_sha256": source_sha256[
                            "source_report_manifest"
                        ],
                        "source_review_summary": review_summary,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        support = {
            relative: hashlib.sha256((path / relative).read_bytes()).hexdigest()
            for relative in MODULE.METHOD_CONTRACTS[method_id]["files"]
            if relative not in {"report.md", "report_manifest.json"}
        }
        report = path / "report.md"
        manifest = {
            "schema_version": 1,
            "method_id": method_id,
            "report_kind": report_kind,
            "evidence_status": "blocked" if method_id.endswith("_blocked") else "partial_evidence",
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
            "support_sha256": support,
            "source_sha256": source_sha256,
            "review_summary": review_summary,
        }
        if route is not None:
            manifest["route"] = route
        if method_id in MODULE.BLOCKED_CROSSCHECK_METHOD_IDS:
            manifest.update(
                {
                    "alias_scope": ["subject01_tumor", "subject01_normal"],
                    "blockers": ["blocked unit route"],
                    "classification_authorization": "none",
                    "explicit_no_patient_result": (
                        "The method was not run and no patient result was "
                        "generated, inferred, or reported."
                    ),
                    "generated_at": "2026-07-17T00:00:00+00:00",
                    "intended_computation": ["blocked unit computation"],
                    "interpretation_status": "no_call",
                    "next_gate": "validate the executable route",
                    "patient_result": "none",
                    "prerequisites": ["validated runtime"],
                    "run_id": "unit",
                    "source_report_binding_scope": "not_bound",
                    "sources": [],
                }
            )
        (path / "report_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    bind_blocked_reports(paths)


def source_report_manifests(paths: dict[str, Path]) -> dict[str, str]:
    return {
        method_id: MODULE.sha256(paths[method_id] / "report_manifest.json")
        for method_id in MODULE.BLOCKED_SOURCE_METHOD_IDS
        if method_id in paths
    }


def bind_blocked_reports(paths: dict[str, Path]) -> None:
    if any(method_id not in paths for method_id in MODULE.BLOCKED_CROSSCHECK_METHOD_IDS):
        return

    manifests = source_report_manifests(paths)
    if set(manifests) != set(MODULE.BLOCKED_SOURCE_METHOD_IDS):
        return

    for method_id in MODULE.BLOCKED_CROSSCHECK_METHOD_IDS:
        shutil.rmtree(paths[method_id], ignore_errors=True)

    BLOCKED_GENERATOR.generate(
        paths["facets_scarhrd_blocked"].parent,
        generated_at="2026-07-17T00:00:00+00:00",
        run_id="unit",
        source_report_manifests=manifests,
    )


def write_phase3_fast_validation_receipt(
    paths: dict[str, Path],
    output: Path,
    forbidden_tokens: list[str] | None = None,
) -> None:
    fast_blocked_root = output.parent / "pre-route-blocked"
    BLOCKED_GENERATOR.generate(
        fast_blocked_root,
        generated_at="2026-07-17T00:00:00+00:00",
        source_report_manifests={
            method_id: MODULE.sha256(paths[method_id] / "report_manifest.json")
            for method_id in BLOCKED_GENERATOR.PRE_ROUTE_SOURCE_REPORT_METHOD_IDS
        },
        allow_pre_route_source_reports=True,
    )
    packet_dirs = {
        method_id: paths[method_id]
        for method_id in PHASE3_FAST_VALIDATOR.PHASE3_FAST_VALIDATED_METHOD_IDS
        if method_id not in MODULE.BLOCKED_CROSSCHECK_METHOD_IDS
    }
    packet_dirs.update(
        {
            method["method_id"]: fast_blocked_root / method["directory"]
            for method in BLOCKED_GENERATOR.METHODS
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            PHASE3_FAST_VALIDATOR.validate_packets(
                packet_dirs,
                json.dumps(forbidden_tokens or ["Unit-Run-Private-Token"]),
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def write_phase3_fast_forbidden_tokens(output: Path) -> None:
    output.write_text('["Unit-Run-Private-Token"]\n', encoding="utf-8")


class RenderSourceReportFreezeRunbookTests(unittest.TestCase):
    def test_renderer_freezes_seven_sources_in_canonical_order(self) -> None:
        text = MODULE.render(Path("/repo"), "terminal")

        self.assertEqual(text.count("/repo/scripts/publish_private_report.py"), 14)
        self.assertEqual(text.count("--packet-dir "), 14)
        self.assertEqual(text.count("--method-id "), 14)
        self.assertEqual(text.count("--receipt-output "), 14)
        previous = -1
        for method_id in MODULE.REQUIRED_METHOD_IDS:
            index = text.find(f"--method-id {method_id}", previous + 1)
            self.assertGreater(index, previous)
            self.assertIn(
                f"/repo/.codex-tmp/hrd-reports/deterministic-full/terminal.{method_id}.private.json",
                text,
            )
            self.assertIn(
                f"/repo/.codex-tmp/hrd-reports/deterministic-full/terminal.{method_id}.private.dry.json",
                text,
            )
            previous = index

    def test_renderer_hands_exact_receipts_to_promoted_ai_renderer(self) -> None:
        text = MODULE.render(Path("/repo"), "rerun")

        self.assertIn("/repo/scripts/render_ai_synthesis_runbook.py", text)
        self.assertIn(
            "AI_REVIEW_RUNBOOK=/repo/.codex-tmp/hrd-reports/ai-review/rerun.post-reports-runbook.$(date -u +%Y%m%dT%H%M%SZ).md",
            text,
        )
        self.assertIn('--output "$AI_REVIEW_RUNBOOK" --root /repo', text)
        self.assertIn("--receipt-stem rerun", text)
        self.assertNotIn("rerun.post-reports-runbook.md\n", text)
        self.assertEqual(text.count("--private-publication-receipt "), 7)
        previous = -1
        for method_id in MODULE.REQUIRED_METHOD_IDS:
            receipt = MODULE.receipt_path(Path("/repo"), "rerun", method_id)
            index = text.find(
                f"--private-publication-receipt {receipt}",
                previous + 1,
            )
            self.assertGreater(index, previous)
            previous = index
        for stale in MODULE.STALE_TOKENS:
            self.assertNotIn(stale, text)

    def test_ai_runbook_command_has_exact_output_argv(self) -> None:
        output = Path("/repo/.codex-tmp/hrd-reports/ai-review/runbook.md")
        command = MODULE.ai_runbook_command(
            Path("/repo/scripts"),
            Path("/repo"),
            output,
            [Path("/receipts/a.json"), Path("/receipts/b.json")],
            "rerun",
        )

        self.assertEqual(
            command,
            [
                "python3",
                Path("/repo/scripts/render_ai_synthesis_runbook.py"),
                "--output",
                output,
                "--root",
                Path("/repo"),
                "--receipt-stem",
                "rerun",
                "--private-publication-receipt",
                Path("/receipts/a.json"),
                "--private-publication-receipt",
                Path("/receipts/b.json"),
            ],
        )

    def test_publish_command_has_exact_dry_and_apply_argv(self) -> None:
        dry = Path("/receipts/deterministic.dry.json")
        dry_command = MODULE.publish_command(
            Path("/repo/scripts"),
            Path("/packets/deterministic"),
            "deterministic_full_wgs",
            dry,
            apply=False,
        )
        command = MODULE.publish_command(
            Path("/repo/scripts"),
            Path("/packets/deterministic"),
            "deterministic_full_wgs",
            Path("/receipts/deterministic.json"),
            apply=True,
            dry_run_receipt=dry,
        )

        self.assertEqual(
            dry_command,
            [
                "python3",
                Path("/repo/scripts/publish_private_report.py"),
                "--packet-dir",
                Path("/packets/deterministic"),
                "--method-id",
                "deterministic_full_wgs",
                "--receipt-output",
                dry,
                "--region",
                MODULE.REGION,
                *MODULE.forbidden_flags(),
            ],
        )
        self.assertEqual(
            command,
            [
                "python3",
                Path("/repo/scripts/publish_private_report.py"),
                "--packet-dir",
                Path("/packets/deterministic"),
                "--method-id",
                "deterministic_full_wgs",
                "--receipt-output",
                Path("/receipts/deterministic.json"),
                "--region",
                MODULE.REGION,
                *MODULE.forbidden_flags(),
                "--dry-run-receipt",
                dry,
                "--apply",
            ],
        )

        with self.assertRaisesRegex(ValueError, "requires a dry-run receipt"):
            MODULE.publish_command(
                Path("/repo/scripts"),
                Path("/packets/deterministic"),
                "deterministic_full_wgs",
                Path("/receipts/deterministic.json"),
                apply=True,
            )
        with self.assertRaisesRegex(ValueError, "only valid with --apply"):
            MODULE.publish_command(
                Path("/repo/scripts"),
                Path("/packets/deterministic"),
                "deterministic_full_wgs",
                dry,
                apply=False,
                dry_run_receipt=dry,
            )

    def test_source_private_freeze_checklists_are_concrete(self) -> None:
        root = Path("/repo")
        text = MODULE.render(root, "terminal")
        packet_dirs = MODULE.source_packet_dirs(root)

        for method_id in MODULE.REQUIRED_METHOD_IDS:
            dry_receipt = MODULE.dry_receipt_path(root, "terminal", method_id)
            apply_receipt = MODULE.receipt_path(root, "terminal", method_id)
            review = text.index(
                f"Review `{dry_receipt}` before source private-freeze apply:"
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

    def test_publish_command_reads_forbidden_tokens_file_by_path(self) -> None:
        command = MODULE.publish_command(
            Path("/repo/scripts"),
            Path("/packets/deterministic"),
            "deterministic_full_wgs",
            Path("/receipts/deterministic.json"),
            forbidden_tokens_file=Path("/run/forbidden_tokens.json"),
            apply=True,
            dry_run_receipt=Path("/receipts/deterministic.dry.json"),
        )

        self.assertIn("--forbidden-tokens-file", command)
        self.assertIn(Path("/run/forbidden_tokens.json"), command)
        self.assertNotIn("Unit-Run-Private-Token", " ".join(str(part) for part in command))

    def test_renderer_hands_forbidden_tokens_file_to_source_publishers_and_ai_runbook(self) -> None:
        text = MODULE.render(
            Path("/repo"),
            "terminal",
            phase3_fast_forbidden_tokens_file=Path("/fast/forbidden_tokens.json"),
        )

        self.assertEqual(text.count("--forbidden-tokens-file /fast/forbidden_tokens.json"), 15)

    def test_source_packet_dirs_match_required_methods(self) -> None:
        paths = MODULE.source_packet_dirs(Path("/repo"))

        self.assertEqual(tuple(paths), MODULE.REQUIRED_METHOD_IDS)
        self.assertEqual(
            paths["deterministic_full_wgs"].as_posix(),
            "/repo/.codex-tmp/hrd-reports/deterministic-full/report",
        )
        self.assertEqual(
            paths["rosalind_diana_wgs"].as_posix(),
            "/repo/results/rosalind_hrd/diana_wgs/diana-wgs-hrd-20260716T033101Z",
        )

    def test_renderer_accepts_phase3_fast_packet_overrides(self) -> None:
        paths = MODULE.source_packet_dirs(
            Path("/repo"),
            sigprofiler_report_dir=Path("/fast/sigprofiler"),
            sequenza_report_dir=Path("/fast/sequenza"),
            deterministic_report_dir=Path("/fast/deterministic_report"),
            rosalind_report_dir=Path("/fast/rosalind_hrd/diana_wgs"),
            blocked_crosscheck_root=Path("/fast/blocked_crosschecks"),
        )
        text = MODULE.render(
            Path("/repo"),
            "terminal",
            sigprofiler_report_dir=Path("/fast/sigprofiler"),
            sequenza_report_dir=Path("/fast/sequenza"),
            deterministic_report_dir=Path("/fast/deterministic_report"),
            rosalind_report_dir=Path("/fast/rosalind_hrd/diana_wgs"),
            blocked_crosscheck_root=Path("/fast/blocked_crosschecks"),
        )

        self.assertEqual(tuple(paths), MODULE.REQUIRED_METHOD_IDS)
        for packet_dir in paths.values():
            self.assertIn(f"--packet-dir {packet_dir}", text)
        self.assertIn("/fast/blocked_crosschecks/facets_scarhrd_blocked", text)
        self.assertIn("--deterministic-report-dir /fast/deterministic_report", text)
        self.assertIn("--rosalind-report-dir /fast/rosalind_hrd/diana_wgs", text)
        self.assertIn("--blocked-crosscheck-root /fast/blocked_crosschecks", text)
        self.assertIn("--sigprofiler-report-dir /fast/sigprofiler", text)
        self.assertIn("--sequenza-report-dir /fast/sequenza", text)

    def test_validate_packet_dirs_rejects_missing_or_reordered_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            MODULE.validate_packet_dirs(paths)

            reordered = dict(reversed(list(paths.items())))
            with self.assertRaisesRegex(ValueError, "pinned seven-method order"):
                MODULE.validate_packet_dirs(reordered)

            shutil.rmtree(next(iter(paths.values())))
            with self.assertRaisesRegex(ValueError, "missing"):
                MODULE.validate_packet_dirs(paths)

    def test_validate_packet_dirs_rejects_non_exact_packet_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)

            (paths["deterministic_full_wgs"] / "notes.md").write_text(
                "stale scratch\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "inventory is not exact"):
                MODULE.validate_packet_dirs(paths)

    def test_validate_packet_dirs_rejects_stale_report_manifest_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)

            (paths["deterministic_full_wgs"] / "report.md").write_text(
                "# Mutated deterministic report\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "deterministic_full_wgs packet directory is invalid: report manifest does not preserve the reviewed no-call contract",
            ):
                MODULE.validate_packet_dirs(paths)

    def test_validate_packet_dirs_rejects_stale_terminal_report_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)

            rosalind_manifest = paths["rosalind_diana_wgs"] / "report_manifest.json"
            manifest = json.loads(rosalind_manifest.read_text(encoding="utf-8"))
            manifest["report_kind"] = "generic_reviewed_report"
            rosalind_manifest.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            bind_blocked_reports(paths)

            with self.assertRaisesRegex(
                ValueError,
                "rosalind_diana_wgs report_kind must be "
                "rosalind_hrd_reviewer_packet",
            ):
                MODULE.validate_packet_dirs(paths)

    def test_validate_packet_dirs_accepts_matching_phase3_fast_validation_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            validation = root / "report_packet_validation.json"
            forbidden_tokens = root / "forbidden_tokens.json"
            write_phase3_fast_validation_receipt(paths, validation)
            write_phase3_fast_forbidden_tokens(forbidden_tokens)

            MODULE.validate_packet_dirs(
                paths,
                phase3_fast_report_packet_validation=validation,
                phase3_fast_forbidden_tokens_file=forbidden_tokens,
            )

    def test_validate_packet_dirs_requires_forbidden_tokens_file_with_phase3_fast_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            validation = root / "report_packet_validation.json"
            write_phase3_fast_validation_receipt(paths, validation)

            with self.assertRaisesRegex(ValueError, "requires the forbidden-token file"):
                MODULE.validate_packet_dirs(
                    paths,
                    phase3_fast_report_packet_validation=validation,
                )

    def test_validate_packet_dirs_accepts_run_forbidden_tokens_without_phase3_fast_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            forbidden_tokens = root / "forbidden_tokens.json"
            write_phase3_fast_forbidden_tokens(forbidden_tokens)

            MODULE.validate_packet_dirs(
                paths,
                phase3_fast_forbidden_tokens_file=forbidden_tokens,
            )

            sequenza = paths["sequenza_scarhrd"]
            (sequenza / "report.md").write_text(
                "No-call report with Unit-Run-Private-Token.\n",
                encoding="utf-8",
            )
            manifest_path = sequenza / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["report_sha256"] = hashlib.sha256(
                (sequenza / "report.md").read_bytes()
            ).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            bind_blocked_reports(paths)

            with self.assertRaisesRegex(ValueError, "forbidden identifier token"):
                MODULE.validate_packet_dirs(
                    paths,
                    phase3_fast_forbidden_tokens_file=forbidden_tokens,
                )

    def test_validate_packet_dirs_rejects_phase3_fast_tokens_below_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            validation = root / "report_packet_validation.json"
            real_parent = root / "real-tokens"
            linked_parent = root / "linked-tokens"
            real_parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            forbidden_tokens = linked_parent / "forbidden_tokens.json"

            write_phase3_fast_validation_receipt(paths, validation)
            write_phase3_fast_forbidden_tokens(real_parent / forbidden_tokens.name)

            self.assertTrue(forbidden_tokens.is_file())
            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.validate_packet_dirs(
                    paths,
                    phase3_fast_report_packet_validation=validation,
                    phase3_fast_forbidden_tokens_file=forbidden_tokens,
                )

    def test_validate_packet_dirs_rejects_phase3_fast_receipt_with_stale_forbidden_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            validation = root / "report_packet_validation.json"
            write_phase3_fast_validation_receipt(paths, validation)
            forbidden_tokens = root / "forbidden_tokens.json"
            forbidden_tokens.write_text('["Other-Private-Token"]\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "forbidden-token digest"):
                MODULE.validate_packet_dirs(
                    paths,
                    phase3_fast_report_packet_validation=validation,
                    phase3_fast_forbidden_tokens_file=forbidden_tokens,
                )

    def test_validate_packet_dirs_rescans_phase3_fast_packets_with_run_forbidden_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            (paths["deterministic_full_wgs"] / "report.md").write_text(
                "No-call report with Unit-Run-Private-Token.\n",
                encoding="utf-8",
            )
            manifest_path = paths["deterministic_full_wgs"] / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["report_sha256"] = hashlib.sha256((paths["deterministic_full_wgs"] / "report.md").read_bytes()).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            validation = root / "report_packet_validation.json"
            forbidden_tokens = root / "forbidden_tokens.json"
            write_phase3_fast_forbidden_tokens(forbidden_tokens)
            write_phase3_fast_validation_receipt(
                paths,
                validation,
                forbidden_tokens=["Other-Private-Token"],
            )
            wrong_token_receipt = json.loads(validation.read_text(encoding="utf-8"))
            wrong_token_receipt["forbidden_tokens_sha256"] = PHASE3_FAST_VALIDATOR.expected_forbidden_tokens_sha256(
                forbidden_tokens.read_text(encoding="utf-8"),
            )
            validation.write_text(
                json.dumps(wrong_token_receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "forbidden identifier token"):
                MODULE.validate_packet_dirs(
                    paths,
                    phase3_fast_report_packet_validation=validation,
                    phase3_fast_forbidden_tokens_file=forbidden_tokens,
                )

    def test_validate_packet_dirs_rescans_executable_crosschecks_with_run_forbidden_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            sequenza = paths["sequenza_scarhrd"]
            (sequenza / "report.md").write_text(
                "No-call executable cross-check report with Unit-Run-Private-Token.\n",
                encoding="utf-8",
            )
            manifest_path = sequenza / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["report_sha256"] = hashlib.sha256((sequenza / "report.md").read_bytes()).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            validation = root / "report_packet_validation.json"
            forbidden_tokens = root / "forbidden_tokens.json"
            write_phase3_fast_validation_receipt(paths, validation)
            write_phase3_fast_forbidden_tokens(forbidden_tokens)

            with self.assertRaisesRegex(ValueError, "forbidden identifier token"):
                MODULE.validate_packet_dirs(
                    paths,
                    phase3_fast_report_packet_validation=validation,
                    phase3_fast_forbidden_tokens_file=forbidden_tokens,
                )

    def test_validate_packet_dirs_rejects_stale_phase3_fast_validation_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            validation = root / "report_packet_validation.json"
            forbidden_tokens = root / "forbidden_tokens.json"
            write_phase3_fast_validation_receipt(paths, validation)
            write_phase3_fast_forbidden_tokens(forbidden_tokens)
            (paths["deterministic_full_wgs"] / "report.md").write_text(
                "# Mutated after Phase 3 fast validation\n",
                encoding="utf-8",
            )
            manifest_path = paths["deterministic_full_wgs"] / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["report_sha256"] = hashlib.sha256((paths["deterministic_full_wgs"] / "report.md").read_bytes()).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            bind_blocked_reports(paths)

            with self.assertRaisesRegex(ValueError, "does not match current packets"):
                MODULE.validate_packet_dirs(
                    paths,
                    phase3_fast_report_packet_validation=validation,
                    phase3_fast_forbidden_tokens_file=forbidden_tokens,
                )

    def test_validate_packet_dirs_rejects_stale_terminal_blocked_report_after_rehash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)

            report_path = paths["hrdetect_blocked"] / "report.md"
            report_path.write_text(
                report_path.read_text(encoding="utf-8")
                + "\nA late no-call HRDetect packet edit.\n",
                encoding="utf-8",
            )
            manifest_path = paths["hrdetect_blocked"] / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["report_sha256"] = hashlib.sha256(
                report_path.read_bytes()
            ).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "blocked cross-check report is stale"):
                MODULE.validate_packet_dirs(paths)

    def test_validate_packet_dirs_rejects_unbound_blocked_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            blocked_method_ids = set(MODULE.BLOCKED_CROSSCHECK_METHOD_IDS)
            source_paths = {
                method_id: path
                for method_id, path in paths.items()
                if method_id not in blocked_method_ids
            }
            write_packet_dirs(source_paths)
            BLOCKED_GENERATOR.generate(
                root / ".codex-tmp/hrd-reports/blocked-crosschecks",
                generated_at="2026-07-17T00:00:00+00:00",
                source_report_manifests=source_report_manifests(source_paths),
            )
            blocked_dir = (
                root
                / ".codex-tmp/hrd-reports/blocked-crosschecks"
                / "facets_scarhrd_blocked"
            )
            method_spec_path = blocked_dir / "method_spec.json"
            method_spec = json.loads(method_spec_path.read_text(encoding="utf-8"))
            method_spec["source_report_manifests"] = {}
            method_spec_path.write_text(
                json.dumps(method_spec, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_path = blocked_dir / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["review_summary"]["source_report_manifests"] = {}
            manifest["source_sha256"] = {
                "generator": manifest["source_sha256"]["generator"],
            }
            manifest["support_sha256"]["method_spec.json"] = MODULE.sha256(
                method_spec_path
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "not bound to current upstream report manifests",
            ):
                MODULE.validate_packet_dirs(paths)

    def test_validate_packet_dirs_rejects_extra_stale_blocked_report_hash_lines(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            blocked_dir = paths["hrdetect_blocked"]
            report_path = blocked_dir / "report.md"
            report_path.write_text(
                report_path.read_text(encoding="utf-8")
                + "- deterministic_full_wgs report_manifest_sha256: `"
                + ("0" * 64)
                + "`\n",
                encoding="utf-8",
            )
            manifest_path = blocked_dir / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["report_sha256"] = MODULE.sha256(report_path)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "not bound to current upstream report manifests",
            ):
                MODULE.validate_packet_dirs(paths)

    def test_validate_packet_dirs_rejects_extra_stale_blocked_source_hash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            blocked_dir = paths["hrdetect_blocked"]
            manifest_path = blocked_dir / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_sha256"]["stale_report_manifest"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "not bound to current upstream report manifests",
            ):
                MODULE.validate_packet_dirs(paths)

    def test_validate_packet_dirs_rejects_pre_route_blocked_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            blocked_method_ids = set(MODULE.BLOCKED_CROSSCHECK_METHOD_IDS)
            source_paths = {
                method_id: path
                for method_id, path in paths.items()
                if method_id not in blocked_method_ids
            }
            write_packet_dirs(source_paths)
            BLOCKED_GENERATOR.generate(
                root / ".codex-tmp/hrd-reports/blocked-crosschecks",
                generated_at="2026-07-17T00:00:00+00:00",
                source_report_manifests={
                    method_id: MODULE.sha256(
                        paths[method_id] / "report_manifest.json"
                    )
                    for method_id in BLOCKED_GENERATOR.PRE_ROUTE_SOURCE_REPORT_METHOD_IDS
                },
                allow_pre_route_source_reports=True,
            )

            with self.assertRaisesRegex(
                ValueError,
                "not bound to current upstream report manifests",
            ):
                MODULE.validate_packet_dirs(paths)

    def test_validate_packet_dirs_rejects_extra_stale_executable_source_hash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)

            manifest_path = paths["sequenza_scarhrd"] / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_sha256"]["stale_source_report"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            bind_blocked_reports(paths)

            with self.assertRaisesRegex(
                ValueError,
                "staged cross-check report manifest source hashes are not exact",
            ):
                MODULE.validate_packet_dirs(paths)

    def test_validate_packet_dirs_rejects_rebound_stale_executable_method_spec(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)

            packet_dir = paths["sigprofiler_sbs3"]
            method_spec_path = packet_dir / "method_spec.json"
            method_spec = json.loads(method_spec_path.read_text(encoding="utf-8"))
            method_spec["source_review_summary"] = {
                "stale": "review summary from another executable route"
            }
            method_spec_path.write_text(
                json.dumps(method_spec, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            manifest_path = packet_dir / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["support_sha256"]["method_spec.json"] = MODULE.sha256(
                method_spec_path
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            bind_blocked_reports(paths)

            with self.assertRaisesRegex(
                ValueError,
                "staged cross-check method spec differs from the manifest",
            ):
                MODULE.validate_packet_dirs(paths)

    def test_current_blocked_generator_satisfies_renderer_packet_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            blocked_root = root / ".codex-tmp/hrd-reports/blocked-crosschecks"
            paths = MODULE.source_packet_dirs(root)
            blocked_method_ids = {method["method_id"] for method in BLOCKED_GENERATOR.METHODS}
            source_paths = {method_id: path for method_id, path in paths.items() if method_id not in blocked_method_ids}
            write_packet_dirs(source_paths)
            BLOCKED_GENERATOR.generate(
                blocked_root,
                generated_at="2026-07-17T00:00:00+00:00",
                source_report_manifests=source_report_manifests(source_paths),
            )

            MODULE.validate_packet_dirs(paths)
            text = MODULE.render(root, "terminal")
            for method in BLOCKED_GENERATOR.METHODS:
                self.assertIn(
                    f"/blocked-crosschecks/{method['directory']} --method-id {method['method_id']}",
                    text,
                )
            self.assertNotIn("/blocked-crosschecks/facets-scarhrd ", text)
            self.assertNotIn("/blocked-crosschecks/oncoanalyser-chord ", text)
            self.assertNotIn("/blocked-crosschecks/hrdetect ", text)

    def test_required_existing_points_at_checked_in_scripts(self) -> None:
        prerequisites = {path.as_posix() for path in MODULE.required_existing(Path("/repo"))}

        self.assertEqual(
            {
                "/repo/scripts/hrd_report_inventory.py",
                "/repo/scripts/ai_model_catalog.py",
                "/repo/scripts/forbidden_text.py",
                "/repo/scripts/generate_blocked_hrd_crosscheck_reports.py",
                "/repo/scripts/publish_private_report.py",
                "/repo/scripts/stage_hrd_crosscheck_report.py",
                "/repo/scripts/validate_phase3_fast_report_packets.py",
                "/repo/scripts/render_ai_synthesis_runbook.py",
                "/repo/scripts/prepare_ai_review_run.py",
                "/repo/scripts/build_ai_review_bundle.py",
                "/repo/scripts/stage_ai_review_inputs.py",
                "/repo/scripts/validate_ai_review.py",
                "/repo/scripts/finalize_ai_review.py",
                "/repo/scripts/generate_comparative_hrd_synthesis.py",
                "/repo/scripts/render_reviewed_publication_runbook.py",
                "/repo/scripts/runbook_io.py",
                "/repo/scripts/publish_reviewed_public_report.py",
                "/repo/scripts/build_public_results_index.py",
                "/repo/scripts/publish_public_results_index.py",
                "/repo/scripts/write_ai_model_catalog_receipt.py",
            },
            prerequisites,
        )

    def test_required_absent_includes_source_private_receipts(self) -> None:
        outputs = {path.as_posix() for path in MODULE.required_absent(Path("/repo"), "unit")}

        for path in (
            *(f"/repo/.codex-tmp/hrd-reports/deterministic-full/unit.{method_id}.private.dry.json" for method_id in MODULE.REQUIRED_METHOD_IDS),
            *(f"/repo/.codex-tmp/hrd-reports/deterministic-full/unit.{method_id}.private.json" for method_id in MODULE.REQUIRED_METHOD_IDS),
            f"/repo/.codex-tmp/hrd-reports/ai-review/model-catalog-receipts/{MODULE.RUN_ID}/model-catalog-receipt.20260717T115311Z.json",
            f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}",
            "/repo/.codex-tmp/public-index/public-index.unit.dry.json",
        ):
            self.assertIn(path, outputs)

    def test_main_rejects_preexisting_source_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path in MODULE.required_existing(root):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            write_packet_dirs(MODULE.source_packet_dirs(root))

            stale = MODULE.receipt_path(
                root,
                "terminal",
                "sigprofiler_sbs3",
            )
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.symlink_to(root / "missing")
            output = root / "source-freeze.md"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "render_source_report_freeze_runbook.py",
                        "--output",
                        str(output),
                        "--root",
                        str(root),
                    ],
                ),
                self.assertRaisesRegex(SystemExit, "create-only outputs"),
            ):
                MODULE.main()

            self.assertFalse(output.exists())

    def test_write_once_is_mode_0600_and_refuses_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runbook.md"
            MODULE.write_once(output, "one\n")

            self.assertEqual(output.read_text(), "one\n")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.write_once(output, "two\n")

    def test_sha256_rejects_symlinked_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_input = root / "real-report-manifest.json"
            linked_input = root / "report_manifest.json"
            real_input.write_text("{}\n", encoding="utf-8")
            linked_input.symlink_to(real_input)

            with self.assertRaisesRegex(
                ValueError,
                "report_manifest.json SHA-256 input is missing or a symlink",
            ):
                MODULE.sha256(linked_input)

    def test_sha256_rejects_mid_read_rewrites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hash_input = root / "report_manifest.json"
            hash_input.write_text('{"stable": true}\n', encoding="utf-8")

            original_read_once = RUNBOOK_IO.read_real_input_file_once
            mutated = False

            def mutate_after_first_read(path: Path, label: str) -> bytes:
                nonlocal mutated
                data = original_read_once(path, label)
                if path == hash_input and not mutated:
                    mutated = True
                    path.write_text('{"stable": false}\n', encoding="utf-8")
                return data

            with (
                patch.object(
                    RUNBOOK_IO,
                    "read_real_input_file_once",
                    side_effect=mutate_after_first_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report_manifest.json SHA-256 input changed during read",
                ),
            ):
                MODULE.sha256(hash_input)

    def test_runbook_io_sha256_rejects_symlinked_hash_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_input = root / "real-runbook.md"
            linked_input = root / "runbook.md"
            real_input.write_text("real runbook\n", encoding="utf-8")
            linked_input.symlink_to(real_input)

            with self.assertRaisesRegex(
                ValueError,
                "runbook.md SHA-256 input is missing or a symlink",
            ):
                RUNBOOK_IO.sha256_file(linked_input)

    def test_runbook_io_sha256_rejects_symlinked_hash_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_output = root / "real-runbooks"
            linked_output = root / "linked-runbooks"
            real_output.mkdir()
            (real_output / "runbook.md").write_text(
                "real runbook\n",
                encoding="utf-8",
            )
            linked_output.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "runbook.md SHA-256 input parent may not be a symlink",
            ):
                RUNBOOK_IO.sha256_file(linked_output / "runbook.md")

    def test_write_once_rejects_hash_input_symlink_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "runbook.md"
            relocated = root / "relocated.md"
            original_is_file = Path.is_file
            swapped = False

            def swap_after_installed_output_file_check(path: Path) -> bool:
                nonlocal swapped
                if path == output and not swapped and output.exists():
                    swapped = True
                    relocated.write_text("one\n", encoding="utf-8")
                    relocated.chmod(0o600)
                    output.unlink()
                    output.symlink_to(relocated)
                    return True
                return original_is_file(path)

            with (
                patch.object(
                    Path,
                    "is_file",
                    swap_after_installed_output_file_check,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "runbook.md SHA-256 input is missing or a symlink",
                ),
            ):
                RUNBOOK_IO.write_once(output, "one\n")

            self.assertTrue(relocated.exists())
            self.assertFalse(output.exists())

    def test_write_once_rejects_existing_child_below_symlinked_parent(self) -> None:
        self.assertFalse(RUNBOOK_IO.is_platform_root_alias(Path("runbook-link")))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "runbook-real"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "runbook-link"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "output parent is a symlink"):
                MODULE.write_once(linked_parent / "existing" / "runbook.md", "one\n")

            self.assertFalse((real_parent / "existing" / "runbook.md").exists())

    def test_create_only_preflight_rejects_missing_child_below_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-outputs"
            real_parent.mkdir()
            linked_parent = root / "linked-outputs"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            output = linked_parent / "missing" / "receipt.json"

            self.assertEqual(
                RUNBOOK_IO.preexisting_create_only_paths([output]),
                (output,),
            )
            self.assertFalse((real_parent / "missing" / "receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
