from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SCRIPT = SCRIPT_DIR / "build_hcc1395_known_answer_stack.py"
SPEC = importlib.util.spec_from_file_location("build_hcc1395_known_answer_stack", SCRIPT)
assert SPEC and SPEC.loader
STACK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STACK)

ARTIFACT_ROOT = ROOT / "artifacts/phase3_wgs_selective5"


def write_catalog(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider_catalog": "synthetic-test-catalog",
                "catalog_source": "offline-known-answer-test",
                "catalog_verified_at": "2026-07-18T00:00:00+00:00",
                "models": [
                    {
                        "provider": "synthetic-provider-a",
                        "model_id": "synthetic-model-a-current",
                        "available": True,
                        "latest_available": True,
                    },
                    {
                        "provider": "synthetic-provider-b",
                        "model_id": "synthetic-model-b-current",
                        "available": True,
                        "latest_available": True,
                    },
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def write_duplicate_json_field(path: Path, key: str, stale_value: object) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(payload, indent=2, sort_keys=True)
    current = f'  "{key}": {json.dumps(payload[key], sort_keys=True)}'
    if text.count(current) != 1:
        raise AssertionError(f"expected exactly one top-level JSON field {key}")
    duplicate = f'  "{key}": {json.dumps(stale_value, sort_keys=True)},\n{current}'
    path.write_text(text.replace(current, duplicate, 1) + "\n", encoding="utf-8")


def args_for(root: Path, output: Path) -> argparse.Namespace:
    catalog = root / "model-catalog.json"
    write_catalog(catalog)
    return argparse.Namespace(
        artifact_root=ARTIFACT_ROOT,
        output_dir=output,
        run_id="hcc1395-known-answer-unit",
        generated_at="2026-07-18T00:00:00+00:00",
        model_catalog_receipt=catalog,
        model_catalog_verified_at="2026-07-18T00:00:00+00:00",
        reviewer_a_provider="synthetic-provider-a",
        reviewer_a_model_id="synthetic-model-a-current",
        reviewer_b_provider="synthetic-provider-b",
        reviewer_b_model_id="synthetic-model-b-current",
        subject_alias="subject99",
        forbidden_token=["DirectIdentifier"],
    )


class BuildHcc1395KnownAnswerStackTests(unittest.TestCase):
    def test_builds_exact_machine_readable_seven_method_stack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stack"
            manifest = STACK.build(args_for(root, output))

            self.assertEqual(manifest["status"], "passed")
            self.assertEqual(manifest["authorized_hrd_state"], "no_call")
            self.assertFalse(manifest["models_invoked"])
            self.assertEqual(
                tuple(manifest["source_reports"]),
                STACK.HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS,
            )

            source_manifests = {}
            for method_id, details in manifest["source_reports"].items():
                path = output / details["manifest"]
                self.assertTrue(path.is_file(), method_id)
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["method_id"], method_id)
                self.assertEqual(payload["authorized_hrd_state"], "no_call")
                self.assertFalse(payload["classification_authorized"])
                self.assertEqual(payload["classification_qc_status"], "not_applicable")
                source_manifests[method_id] = payload

            self.assertEqual(
                source_manifests["deterministic_full_wgs"]["report_kind"],
                "hcc1395_wgs_known_answer",
            )
            self.assertEqual(
                source_manifests["sigprofiler_sbs3"]["evidence_status"],
                "partial_evidence",
            )
            for method_id in (
                "sequenza_scarhrd",
                "facets_scarhrd_blocked",
                "oncoanalyser_chord_blocked",
                "hrdetect_blocked",
            ):
                self.assertEqual(source_manifests[method_id]["evidence_status"], "blocked")
                self.assertEqual(source_manifests[method_id]["execution_status"], "not_run")

            bundle = json.loads(
                (output / "ai-review/bundle/review_bundle.json").read_text(
                    encoding="utf-8"
                )
            )
            bundle_manifest = json.loads(
                (output / "ai-review/bundle/bundle_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            prepare_receipt = json.loads(
                (
                    output / "ai-review/prepare_ai_review_run_receipt.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(bundle["subject_alias"], "subject99")
            self.assertEqual(
                bundle["method_inventory"]["inventory_id"],
                STACK.HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID,
            )
            self.assertEqual(
                bundle["required_method_ids"],
                list(STACK.HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS),
            )
            serialized_bundle = json.dumps(bundle)
            self.assertNotIn("rosalind_diana_wgs", serialized_bundle)
            self.assertNotIn("subject01", serialized_bundle)
            self.assertEqual(len(bundle_manifest["forbidden_token_sha256"]), 1)
            self.assertEqual(
                prepare_receipt["method_inventory"]["inventory_id"],
                STACK.HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID,
            )
            for key in (
                "ai_review_bundle_manifest",
                "ai_review_prepare_receipt",
                "ai_review_stage_receipt",
            ):
                path = output / manifest[key]["path"]
                self.assertTrue(path.is_file(), key)
                self.assertEqual(manifest[key]["sha256"], STACK.sha256(path))
            self.assertEqual(
                sorted(
                    path.name
                    for path in (
                        output / "ai-review/reviewer-inputs/reviewer-a-input"
                    ).iterdir()
                ),
                ["review_bundle.json", "reviewer-a.prompt.md"],
            )
            self.assertEqual(
                sorted(
                    path.name
                    for path in (
                        output / "ai-review/reviewer-inputs/reviewer-b-input"
                    ).iterdir()
                ),
                ["review_bundle.json", "reviewer-b.prompt.md"],
            )

    def test_regenerates_current_gap_aware_rosalind_packet_outside_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stack"
            manifest = STACK.build(args_for(root, output))
            rosalind_manifest_path = (
                output
                / manifest["source_reports"]["rosalind_hcc1395_wgs"]["manifest"]
            )
            packet_dir = rosalind_manifest_path.parent
            rosalind_manifest = json.loads(
                rosalind_manifest_path.read_text(encoding="utf-8")
            )
            adapter_text = (packet_dir / "hrd_adapter_status.csv").read_text(
                encoding="utf-8"
            )

            self.assertNotIn("input_ready_threshold_met", adapter_text)
            self.assertIn("input_matrix_ready_assignment_not_run", adapter_text)
            gaps = rosalind_manifest["review_summary"]["interpretation_gaps"]
            self.assertEqual(len(gaps), 5)
            self.assertEqual(rosalind_manifest["review_summary"]["blockers"], [])
            self.assertFalse(str(rosalind_manifest_path).startswith(str(ROOT / "results")))

    def test_each_method_report_describes_process_result_and_no_call_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stack"
            manifest = STACK.build(args_for(root, output))

            for method_id in STACK.HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS[2:]:
                report = (
                    output
                    / manifest["source_reports"][method_id]["manifest"]
                ).parent / "report.md"
                text = report.read_text(encoding="utf-8")
                self.assertIn("## Process", text)
                self.assertIn("## Result", text)
                self.assertIn("## Authorized conclusion", text)
                self.assertIn("`no_call`", text)
                self.assertIn("not run", text.lower())

    def test_output_is_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stack"
            args = args_for(root, output)
            STACK.build(args)
            with self.assertRaisesRegex(FileExistsError, "output already exists"):
                STACK.build(args)

    def test_rejects_duplicate_model_catalog_json_without_installing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stack"
            args = args_for(root, output)
            write_duplicate_json_field(args.model_catalog_receipt, "schema_version", 0)

            with self.assertRaisesRegex(
                ValueError,
                "duplicate JSON object name in model catalog receipt: schema_version",
            ):
                STACK.build(args)

            self.assertFalse(output.exists())

    def test_sha256_requires_real_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "report_manifest.json"
            source.write_text("{}\n", encoding="utf-8")

            source_link = root / "report_manifest_link.json"
            source_link.symlink_to(source)
            with self.assertRaisesRegex(
                ValueError,
                "report_manifest_link\\.json SHA-256 input must be a real file",
            ):
                STACK.sha256(source_link)

            real_parent = root / "real-source"
            real_parent.mkdir()
            linked_parent = root / "linked-source"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            (real_parent / "report_manifest.json").write_text(
                "{}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "report_manifest\\.json SHA-256 input parent may not be a symlink",
            ):
                STACK.sha256(linked_parent / "report_manifest.json")

    def test_stack_manifest_rechecks_source_reports_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stack"
            real_write_json = STACK.write_json

            def tamper_after_stack_manifest(path: Path, value: object) -> None:
                real_write_json(path, value)
                if path.name == "stack_manifest.json":
                    manifest = (
                        path.parent
                        / "source-reports/deterministic_full_wgs/report_manifest.json"
                    )
                    payload = json.loads(manifest.read_text(encoding="utf-8"))
                    payload["tampered_after_stack_manifest"] = True
                    manifest.write_text(
                        json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    STACK,
                    "write_json",
                    side_effect=tamper_after_stack_manifest,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "HCC1395 stack manifest is stale for deterministic_full_wgs",
                ),
            ):
                STACK.build(args_for(root, output))

            self.assertFalse(output.exists())
            self.assertFalse(any(root.glob(".stack.*")))

    def test_stack_manifest_rejects_stale_crosscheck_upstream_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stack"
            real_run_ai_review_prepare = STACK.run_ai_review_prepare

            def stale_upstream_after_method_packet(
                manifests: list[Path],
                ai_review: Path,
                args: argparse.Namespace,
            ) -> None:
                sequenza_manifest = manifests[2]
                payload = json.loads(sequenza_manifest.read_text(encoding="utf-8"))
                payload["source_sha256"][
                    "deterministic_full_wgs_report_manifest"
                ] = "0" * 64
                sequenza_manifest.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                real_run_ai_review_prepare(manifests, ai_review, args)

            with (
                mock.patch.object(
                    STACK,
                    "run_ai_review_prepare",
                    side_effect=stale_upstream_after_method_packet,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "HCC1395 sequenza_scarhrd source hashes are stale",
                ),
            ):
                STACK.build(args_for(root, output))

            self.assertFalse(output.exists())
            self.assertFalse(any(root.glob(".stack.*")))

    def test_stack_manifest_rechecks_ai_receipts_after_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stack"
            real_fsync_directory = STACK.fsync_directory

            def tamper_after_install_fsync(path: Path) -> None:
                real_fsync_directory(path)
                if path == output.parent and output.exists():
                    receipt = (
                        output
                        / "ai-review/stage_ai_review_inputs_receipt.json"
                    )
                    receipt.write_text("{}\n", encoding="utf-8")

            with (
                mock.patch.object(
                    STACK,
                    "fsync_directory",
                    side_effect=tamper_after_install_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "HCC1395 stack manifest is stale for ai_review_stage_receipt",
                ),
            ):
                STACK.build(args_for(root, output))

            self.assertFalse(output.exists())

    def test_stack_manifest_rechecks_prepare_receipt_inner_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stack"
            real_run_ai_review_prepare = STACK.run_ai_review_prepare

            def stale_prepare_receipt(
                manifests: list[Path],
                ai_review: Path,
                args: argparse.Namespace,
            ) -> None:
                real_run_ai_review_prepare(manifests, ai_review, args)
                receipt = ai_review / "prepare_ai_review_run_receipt.json"
                payload = json.loads(receipt.read_text(encoding="utf-8"))
                payload["stage_receipt_sha256"] = "0" * 64
                receipt.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

            with (
                mock.patch.object(
                    STACK,
                    "run_ai_review_prepare",
                    side_effect=stale_prepare_receipt,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "prepared AI review run stage_receipt_sha256 is stale",
                ),
            ):
                STACK.build(args_for(root, output))

            self.assertFalse(output.exists())
            self.assertFalse(any(root.glob(".stack.*")))

    def test_stack_manifest_rejects_unbound_entries_after_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stack"
            real_fsync_directory = STACK.fsync_directory

            def add_unbound_entry_after_install_fsync(path: Path) -> None:
                real_fsync_directory(path)
                if path == output.parent and output.exists():
                    (output / "unbound.json").write_text(
                        "{}\n",
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    STACK,
                    "fsync_directory",
                    side_effect=add_unbound_entry_after_install_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "HCC1395 stack inventory is not exact",
                ),
            ):
                STACK.build(args_for(root, output))

            self.assertFalse(output.exists())

    def test_stack_manifest_rechecks_reviewer_inputs_after_stack_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stack"
            real_write_json = STACK.write_json

            def tamper_after_stack_manifest(path: Path, value: object) -> None:
                real_write_json(path, value)
                if path.name == "stack_manifest.json":
                    prompt = (
                        path.parent
                        / "ai-review"
                        / "reviewer-inputs"
                        / "reviewer-a-input"
                        / "reviewer-a.prompt.md"
                    )
                    prompt.write_text(
                        "tampered reviewer input\n",
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    STACK,
                    "write_json",
                    side_effect=tamper_after_stack_manifest,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "reviewer A reviewer-a.prompt.md SHA-256 mismatch",
                ),
            ):
                STACK.build(args_for(root, output))

            self.assertFalse(output.exists())
            self.assertFalse(any(root.glob(".stack.*")))


if __name__ == "__main__":
    unittest.main()
