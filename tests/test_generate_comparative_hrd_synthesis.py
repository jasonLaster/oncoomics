#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from hrd_report_inventory import (  # noqa: E402
    REQUIRED_METHOD_IDS,
    inventory_payload,
    inventory_sha256,
)
import publish_private_report as PUBLISH_PRIVATE  # noqa: E402

GENERATOR = SCRIPT_DIR / "generate_comparative_hrd_synthesis.py"
CLAIMS_FIELDS = [
    "claim_id",
    "claim",
    "evidence_ids",
    "source_methods",
    "evidence_states",
    "support_level",
    "caveat",
    "disposition",
    "proposed_hrd_state",
    "quantitative_fact_ids",
    "disagreement_status",
    "disagreement_evidence_ids",
    "resolution_needed",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class SynthesisFixture:
    def __init__(self, root: Path):
        self.root = root
        self.bundle_dir = root / "bundle"
        self.output_dir = root / "synthesis"
        self.review_a = root / "review-a"
        self.review_b = root / "review-b"
        self.methods = list(REQUIRED_METHOD_IDS)
        self.source_manifests: List[Path] = []
        for index, method_id in enumerate(self.methods):
            blocked = index >= 4
            self._write_source(
                f"method-{index + 1:02d}",
                {
                    "schema_version": 1,
                    "report_kind": "deterministic" if index == 0 else "statistical_method",
                    "method_id": method_id,
                    "evidence_status": "blocked" if blocked else "partial_evidence",
                    "interpretation_status": "no_call",
                    "authorized_hrd_state": "no_call",
                    "classification_authorized": False,
                    "classification_qc_status": "blocked" if blocked else "not_applicable",
                    "review_summary": {
                        "evidence_scope": f"synthetic evidence for method {index + 1}",
                        "readiness": {
                            "route": "blocked" if blocked else "partial_evidence",
                            "overall": "no_call",
                        },
                        "observations": {} if blocked else {"signal": "descriptive only"},
                        "limitations": [
                            "The model fit is unavailable."
                            if blocked
                            else "Allele-specific copy number may be unavailable."
                        ],
                    },
                },
            )
        self._write_bundle()
        self._write_review("A", self.review_a)
        self._write_review("B", self.review_b)

    def _write_source(self, name: str, payload: Dict[str, Any]) -> None:
        directory = self.root / name
        directory.mkdir(parents=True)
        report = directory / "report.md"
        report.write_text("# Safe synthetic report\n\nAlias-only evidence.\n", encoding="utf-8")
        payload["report_sha256"] = sha256(report)
        payload["source_sha256"] = {"safe_summary": hashlib.sha256(name.encode()).hexdigest()}
        manifest = directory / "report_manifest.json"
        write_json(manifest, payload)
        self.source_manifests.append(manifest)

    def _evidence_row(self, index: int, source_path: Path) -> Dict[str, Any]:
        source = json.loads(source_path.read_text(encoding="utf-8"))
        return {
            "evidence_id": "E{0:03d}".format(index),
            "method_id": source["method_id"],
            "report_kind": source["report_kind"],
            "evidence_status": source["evidence_status"],
            "authorized_hrd_state": source["authorized_hrd_state"],
            "classification_authorized": source["classification_authorized"] is True,
            "classification_qc_status": source["classification_qc_status"],
            "report_sha256": source["report_sha256"],
            "source_artifact_sha256": sorted(source["source_sha256"].values()),
            "review_summary": source["review_summary"],
        }

    def _write_bundle(self) -> None:
        self.bundle_dir.mkdir()
        models = {
            "A": {
                "provider": "synthetic-provider-a",
                "model_id": "latest-model-a",
                "catalog_verified_at": "2026-07-17T00:00:00+00:00",
                "latest_available_attested": True,
            },
            "B": {
                "provider": "synthetic-provider-b",
                "model_id": "latest-model-b",
                "catalog_verified_at": "2026-07-17T00:00:00+00:00",
                "latest_available_attested": True,
            },
        }
        bundle = {
            "schema_version": 2,
            "generated_at": "2026-07-17T00:00:00+00:00",
            "purpose": "deidentified_independent_narrative_crosscheck",
            "subject_alias": "subject01",
            "authorized_hrd_state": "no_call",
            "required_method_ids": self.methods,
            "method_inventory": inventory_payload(),
            "method_inventory_sha256": inventory_sha256(),
            "evidence_sources": [
                self._evidence_row(index, path) for index, path in enumerate(self.source_manifests, 1)
            ],
            "quantitative_facts": [],
            "model_execution_contracts": models,
            "model_catalog_receipt_sha256": "c" * 64,
            "policy": {
                "raw_inputs_prohibited": True,
                "external_research_prohibited": True,
                "reviewers_independent": True,
                "other_reviewer_outputs_prohibited": True,
                "numerical_results_immutable": True,
                "classification_may_not_exceed_authorized_state": True,
            },
        }
        bundle_path = self.bundle_dir / "review_bundle.json"
        write_json(bundle_path, bundle)
        bundle_hash = sha256(bundle_path)
        write_json(
            self.bundle_dir / "bundle_manifest.json",
            {
                "schema_version": 2,
                "generated_at": "2026-07-17T00:00:00+00:00",
                "subject_alias": "subject01",
                "authorized_hrd_state": "no_call",
                "required_method_ids": self.methods,
                "method_inventory": inventory_payload(),
                "method_inventory_sha256": inventory_sha256(),
                "input_manifest_sha256": {
                    "E{0:03d}".format(index): sha256(path)
                    for index, path in enumerate(self.source_manifests, 1)
                },
                "forbidden_token_sha256": ["f" * 64],
                "review_bundle_sha256": bundle_hash,
                "prompt_sha256": {"A": "a" * 64, "B": "b" * 64},
                "model_execution_contracts": models,
                "model_catalog_receipt_sha256": "c" * 64,
            },
        )

    def _claims(self, reviewer: str) -> List[Dict[str, str]]:
        adjective = "descriptive" if reviewer == "A" else "non-allele-specific"
        rows: List[Dict[str, str]] = []
        for index, method_id in enumerate(self.methods, 1):
            blocked = index >= 5
            rows.append(
                {
                    "claim_id": f"C{index:03d}",
                    "claim": (
                        "The coverage signal is {0}.".format(adjective)
                        if index == 1
                        else (
                            f"The {method_id} result remains descriptive for reviewer {reviewer}."
                            if not blocked
                            else f"The {method_id} route is unavailable for reviewer {reviewer}."
                        )
                    ),
                    "evidence_ids": f"E{index:03d}",
                    "source_methods": method_id,
                    "evidence_states": "blocked" if blocked else "partial_evidence",
                    "support_level": "absent" if blocked else "direct",
                    "caveat": (
                        "No completed statistical result is present."
                        if blocked
                        else "Allele-specific copy number may be unavailable."
                    ),
                    "disposition": "cannot_assess" if blocked else "supported",
                    "proposed_hrd_state": "no_call",
                    "quantitative_fact_ids": "none",
                    "disagreement_status": "missing_evidence" if blocked else "none",
                    "disagreement_evidence_ids": f"E{index:03d}" if blocked else "none",
                    "resolution_needed": (
                        "Complete and validate the statistical model fit."
                        if blocked
                        else "not_applicable"
                    ),
                }
            )
        return rows

    def _write_review(self, reviewer: str, directory: Path) -> None:
        directory.mkdir()
        report = directory / "report.md"
        report.write_text(
            "# Independent HRD evidence review\n\n"
            "Authorized HRD state: `no_call`\n\n"
            "Subject alias: `subject01`\n\n"
            "## Findings\n\nSynthetic reviewer {0} retained no_call.\n".format(reviewer),
            encoding="utf-8",
        )
        claims = directory / "claims.csv"
        with claims.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CLAIMS_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(self._claims(reviewer))
        bundle = json.loads((self.bundle_dir / "review_bundle.json").read_text(encoding="utf-8"))
        bundle_manifest = json.loads(
            (self.bundle_dir / "bundle_manifest.json").read_text(encoding="utf-8")
        )
        output_hashes = {"report.md": sha256(report), "claims.csv": sha256(claims)}
        review_manifest = {
            "schema_version": 2,
            "reviewer_id": reviewer,
            "subject_alias": "subject01",
            "model": bundle["model_execution_contracts"][reviewer],
            "invocation": {
                "invocation_id": "synthetic-invocation-" + reviewer.lower(),
                "interface": "offline-test-fixture",
                "started_at": "2026-07-17T00:00:00+00:00",
                "completed_at": "2026-07-17T00:00:01+00:00",
            },
            "prompt_sha256": bundle_manifest["prompt_sha256"][reviewer],
            "input_bundle_sha256": bundle_manifest["review_bundle_sha256"],
            "method_inventory_sha256": inventory_sha256(),
            "input_artifact_sha256": {
                "review_bundle.json": bundle_manifest["review_bundle_sha256"],
                "reviewer-{0}.prompt.md".format(reviewer.lower()): bundle_manifest["prompt_sha256"][
                    reviewer
                ],
            },
            "independence_attestation": {
                "other_reviewer_outputs_received": False,
                "other_reviewer_context_received": False,
                "external_research_used": False,
                "raw_inputs_received": False,
                "isolated_session": True,
                "input_directory_contained_only_declared_artifacts": True,
            },
            "output_sha256": output_hashes,
        }
        manifest_path = directory / "review_manifest.json"
        write_json(manifest_path, review_manifest)
        write_json(
            directory / "validation.json",
            {
                "schema_version": 2,
                "status": "passed",
                "reviewer_id": reviewer,
                "subject_alias": "subject01",
                "model": bundle["model_execution_contracts"][reviewer],
                "authorized_hrd_state": "no_call",
                "required_method_ids": self.methods,
                "method_inventory": inventory_payload(),
                "method_inventory_sha256": inventory_sha256(),
                "model_catalog_receipt_sha256": "c" * 64,
                "claim_count": 7,
                "covered_evidence_ids": [f"E{index:03d}" for index in range(1, 8)],
                "disagreement_claim_count": 3,
                "review_bundle_sha256": bundle_manifest["review_bundle_sha256"],
                "prompt_sha256": bundle_manifest["prompt_sha256"][reviewer],
                "report_sha256": output_hashes["report.md"],
                "claims_sha256": output_hashes["claims.csv"],
                "review_manifest_sha256": sha256(manifest_path),
                "forbidden_token_count": 1,
            },
        )

    def run(
        self,
        source_manifests: Optional[List[Path]] = None,
        methods: Optional[List[str]] = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(GENERATOR)]
        for source in source_manifests if source_manifests is not None else self.source_manifests:
            command.extend(["--source-manifest", str(source)])
        for method in methods if methods is not None else self.methods:
            command.extend(["--require-method", method])
        command.extend(
            [
                "--review-bundle",
                str(self.bundle_dir / "review_bundle.json"),
                "--bundle-manifest",
                str(self.bundle_dir / "bundle_manifest.json"),
                "--reviewer-a-dir",
                str(self.review_a),
                "--reviewer-b-dir",
                str(self.review_b),
                "--output-dir",
                str(self.output_dir),
            ]
        )
        return subprocess.run(command, text=True, capture_output=True)

    def refresh_bundle_hash(self) -> None:
        manifest_path = self.bundle_dir / "bundle_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["review_bundle_sha256"] = sha256(self.bundle_dir / "review_bundle.json")
        write_json(manifest_path, manifest)


class GenerateSynthesisTests(unittest.TestCase):
    def test_generates_descriptive_report_table_and_schema_one_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            result = fixture.run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = (fixture.output_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("## Process", report)
            self.assertIn("## Per-approach results", report)
            self.assertIn("## Deterministic, statistical, and AI agreement", report)
            self.assertIn("## Structured disagreements", report)
            self.assertIn("## Limitations", report)
            self.assertIn("## Unresolved observations", report)
            self.assertIn("## Authorized conclusion", report)
            self.assertIn("remains `no_call`", report)
            manifest = json.loads((fixture.output_dir / "report_manifest.json").read_text())
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["authorized_hrd_state"], "no_call")
            self.assertEqual(manifest["evidence_status"], "partial_evidence")
            self.assertFalse(manifest["classification_authorized"])
            self.assertEqual(
                [row["method_id"] for row in manifest["review_summary"]["methods"]], fixture.methods
            )
            rows = PUBLISH_PRIVATE.validate_packet_dir(
                fixture.output_dir,
                "comparative_hrd_synthesis",
                ("DirectIdentifier",),
            )
            self.assertEqual(
                [row["relative_path"] for row in rows],
                ["agreement_disagreement.csv", "report.md", "report_manifest.json"],
            )
            with (fixture.output_dir / "agreement_disagreement.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(
                [row["evidence_id"] for row in rows],
                [f"E{index:03d}" for index in range(1, 8)],
            )
            self.assertIn("source_not_comparable", rows[4]["structured_disagreement_types"])

    def test_missing_required_method_fails_and_removes_stale_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            result = fixture.run(fixture.source_manifests[:1], fixture.methods[:1])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("method inventory", result.stdout + result.stderr)
            self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_stale_extra_output_fails_before_removing_prior_packet(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            (fixture.output_dir / "unexpected.txt").write_text(
                "stale\n",
                encoding="utf-8",
            )

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "synthesis output contains unexpected existing files",
                result.stdout + result.stderr,
            )
            self.assertEqual(
                sorted(path.name for path in fixture.output_dir.iterdir()),
                [
                    "agreement_disagreement.csv",
                    "report.md",
                    "report_manifest.json",
                    "unexpected.txt",
                ],
            )

    def test_omitted_reordered_added_and_tampered_inventory_fail_closed(self) -> None:
        method_sets = (
            list(REQUIRED_METHOD_IDS[:-1]),
            [REQUIRED_METHOD_IDS[1], REQUIRED_METHOD_IDS[0], *REQUIRED_METHOD_IDS[2:]],
            [*REQUIRED_METHOD_IDS, "unexpected_method"],
        )
        for methods in method_sets:
            with self.subTest(methods=methods), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-inventory-"
            ) as temporary:
                fixture = SynthesisFixture(Path(temporary))
                result = fixture.run(methods=methods)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("pinned seven-method inventory", result.stdout + result.stderr)

        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-inventory-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            bundle_path = fixture.bundle_dir / "review_bundle.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["method_inventory"]["ordered_method_ids"][0:2] = reversed(
                bundle["method_inventory"]["ordered_method_ids"][0:2]
            )
            write_json(bundle_path, bundle)
            fixture.refresh_bundle_hash()
            result = fixture.run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pinned seven-method inventory", result.stdout + result.stderr)

    def test_changed_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            fixture.source_manifests[0].with_name("report.md").write_text("changed\n", encoding="utf-8")
            result = fixture.run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source report hash mismatch", result.stdout + result.stderr)
            self.assertFalse((fixture.output_dir / "report.md").exists())

    def test_changed_ai_output_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            with (fixture.review_a / "report.md").open("a", encoding="utf-8") as handle:
                handle.write("altered after validation\n")
            result = fixture.run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("output differs", result.stdout + result.stderr)

    def test_duplicate_model_and_invocation_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-model-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            bundle_path = fixture.bundle_dir / "review_bundle.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["model_execution_contracts"]["B"] = bundle["model_execution_contracts"]["A"]
            write_json(bundle_path, bundle)
            bundle_manifest_path = fixture.bundle_dir / "bundle_manifest.json"
            bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
            bundle_manifest["model_execution_contracts"] = bundle["model_execution_contracts"]
            bundle_manifest["review_bundle_sha256"] = sha256(bundle_path)
            write_json(bundle_manifest_path, bundle_manifest)
            result = fixture.run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("distinct models", result.stdout + result.stderr)

        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-invocation-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            a_manifest = json.loads((fixture.review_a / "review_manifest.json").read_text())
            b_manifest_path = fixture.review_b / "review_manifest.json"
            b_manifest = json.loads(b_manifest_path.read_text())
            b_manifest["invocation"]["invocation_id"] = a_manifest["invocation"]["invocation_id"]
            write_json(b_manifest_path, b_manifest)
            validation_path = fixture.review_b / "validation.json"
            validation = json.loads(validation_path.read_text())
            validation["review_manifest_sha256"] = sha256(b_manifest_path)
            write_json(validation_path, validation)
            result = fixture.run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate invocation ID", result.stdout + result.stderr)

    def test_unauthorized_positive_and_negative_synthesis_fail_closed(self) -> None:
        for unauthorized in ("positive", "negative"):
            with self.subTest(state=unauthorized), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-authorization-"
            ) as temporary:
                fixture = SynthesisFixture(Path(temporary))
                bundle_path = fixture.bundle_dir / "review_bundle.json"
                bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
                bundle["authorized_hrd_state"] = unauthorized
                write_json(bundle_path, bundle)
                bundle_manifest_path = fixture.bundle_dir / "bundle_manifest.json"
                bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
                bundle_manifest["authorized_hrd_state"] = unauthorized
                bundle_manifest["review_bundle_sha256"] = sha256(bundle_path)
                write_json(bundle_manifest_path, bundle_manifest)
                result = fixture.run()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("authorized ceiling", result.stdout + result.stderr)
                self.assertFalse((fixture.output_dir / "report_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
