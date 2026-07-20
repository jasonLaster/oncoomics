#!/usr/bin/env python3
from __future__ import annotations

import ast
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import generate_comparative_hrd_synthesis as GENERATE  # noqa: E402
import publish_private_report as PUBLISH_PRIVATE  # noqa: E402
from hrd_report_inventory import (  # noqa: E402
    HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID,
    HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS,
    INVENTORY_ID,
    REQUIRED_METHOD_IDS,
    inventory_payload,
    inventory_sha256,
)

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


def synthesis_report_manifest(report: Path, agreement: Path) -> Dict[str, Any]:
    agreement_sha256 = sha256(agreement)
    return {
        "schema_version": 1,
        "report_kind": "comparative_synthesis",
        "method_id": "comparative_hrd_synthesis",
        "generated_at": "2026-07-18T00:00:00+00:00",
        "subject_alias": "subject01",
        "evidence_status": "partial_evidence",
        "interpretation_status": "no_call",
        "authorized_hrd_state": "no_call",
        "classification_authorized": False,
        "classification_authorization": "none",
        "classification_qc_status": "not_applicable",
        "report_sha256": sha256(report),
        "agreement_disagreement_sha256": agreement_sha256,
        "support_sha256": {
            "agreement_disagreement.csv": agreement_sha256,
        },
        "source_sha256": {
            key: hashlib.sha256(key.encode()).hexdigest()
            for key in GENERATE.expected_synthesis_source_hash_keys()
        },
        "review_summary": {
            "evidence_scope": (
                "offline comparative synthesis of deterministic, statistical, "
                "and independently validated AI evidence"
            ),
            "process": {
                **GENERATE.REQUIRED_SYNTHESIS_PROCESS,
                "method_inventory": inventory_payload(),
                "method_inventory_sha256": inventory_sha256(),
            },
            "readiness": {
                "evidence_status": "partial_evidence",
                "authorized_hrd_state": "no_call",
                "classification_authorization": "none",
            },
            "methods": [
                {
                    "evidence_id": "E{0:03d}".format(index),
                    "method_id": method_id,
                    "report_kind": "statistical_method",
                    "evidence_status": "partial_evidence",
                    "authorized_hrd_state": "no_call",
                }
                for index, method_id in enumerate(REQUIRED_METHOD_IDS, 1)
            ],
            "reviewers": [
                {
                    "reviewer_id": "A",
                    "model": {
                        "catalog_verified_at": "2026-07-17T00:00:00+00:00",
                        "latest_available_attested": True,
                        "provider": "synthetic-provider-a",
                        "model_id": "latest-model-a",
                    },
                    "claim_count": len(REQUIRED_METHOD_IDS),
                    "disagreement_claim_count": 0,
                },
                {
                    "reviewer_id": "B",
                    "model": {
                        "catalog_verified_at": "2026-07-17T00:00:00+00:00",
                        "latest_available_attested": True,
                        "provider": "synthetic-provider-b",
                        "model_id": "latest-model-b",
                    },
                    "claim_count": len(REQUIRED_METHOD_IDS),
                    "disagreement_claim_count": 0,
                },
            ],
            "agreement_status_counts": {"concordant": len(REQUIRED_METHOD_IDS)},
            "structured_disagreements": [],
            "limitations": ["synthetic limitation"],
            "unresolved_observations": ["synthetic unresolved observation"],
            "authorized_conclusion": "no_call",
        },
    }


def write_synthesis_manifest(path: Path, report: Path, agreement: Path) -> Dict[str, Any]:
    manifest = synthesis_report_manifest(report, agreement)
    manifest["source_sha256"]["generator"] = sha256(GENERATOR)
    manifest["source_sha256"]["agreement_disagreement.csv"] = sha256(agreement)
    write_json(path, manifest)
    return manifest


def write_synthesis_agreement(path: Path) -> None:
    rows = []
    for index, method_id in enumerate(REQUIRED_METHOD_IDS, 1):
        rows.append(
            {
                "comparison_id": "X{0:03d}".format(index),
                "evidence_id": "E{0:03d}".format(index),
                "method_id": method_id,
                "report_kind": "statistical_method",
                "source_evidence_status": "partial_evidence",
                "source_authorized_hrd_state": "no_call",
                "reviewer_a_claim_ids": "C{0:03d}".format(index),
                "reviewer_b_claim_ids": "C{0:03d}".format(index),
                "reviewer_a_proposed_states": "no_call",
                "reviewer_b_proposed_states": "no_call",
                "reviewer_a_dispositions": "aligned",
                "reviewer_b_dispositions": "aligned",
                "reviewer_a_disagreement_statuses": "none",
                "reviewer_b_disagreement_statuses": "none",
                "agreement_status": "concordant",
                "structured_disagreement_types": "none",
                "resolution_needed": "not_specified",
            }
        )
    GENERATE.write_agreement(path, rows)


class SynthesisFixture:
    def __init__(
        self,
        root: Path,
        *,
        inventory_id: str = INVENTORY_ID,
        methods: Optional[List[str]] = None,
        subject_alias: str = "subject01",
    ):
        self.root = root
        self.inventory_id = inventory_id
        self.subject_alias = subject_alias
        self.bundle_dir = root / "bundle"
        self.output_dir = root / "synthesis"
        self.review_a = root / "review-a"
        self.review_b = root / "review-b"
        self.methods = list(methods or REQUIRED_METHOD_IDS)
        self.source_manifests: List[Path] = []
        for index, method_id in enumerate(self.methods):
            blocked = index >= 4
            self._write_source(
                f"method-{index + 1:02d}",
                {
                    "schema_version": 1,
                    "report_kind": (
                        "deterministic_baseline"
                        if index == 0
                        else "rosalind_hrd_reviewer_packet"
                    ),
                    "method_id": method_id,
                    "evidence_status": "blocked" if blocked else "partial_evidence",
                    "authorized_hrd_state": "no_call",
                    "classification_authorized": False,
                    "classification_qc_status": "not_applicable",
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
        support = directory / "support.json"
        write_json(
            support,
            {
                "source_name": name,
                "source_kind": payload["report_kind"],
            },
        )
        payload["report_sha256"] = sha256(report)
        payload["source_sha256"] = {"safe_summary": hashlib.sha256(name.encode()).hexdigest()}
        payload["support_sha256"] = {"support.json": sha256(support)}
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
            "subject_alias": self.subject_alias,
            "authorized_hrd_state": "no_call",
            "required_method_ids": self.methods,
            "method_inventory": inventory_payload(self.inventory_id),
            "method_inventory_sha256": inventory_sha256(self.inventory_id),
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
                "subject_alias": self.subject_alias,
                "authorized_hrd_state": "no_call",
                "required_method_ids": self.methods,
                "method_inventory": inventory_payload(self.inventory_id),
                "method_inventory_sha256": inventory_sha256(self.inventory_id),
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
            f"Subject alias: `{self.subject_alias}`\n\n"
            f"## Findings\n\nSynthetic reviewer {reviewer} retained no_call.\n",
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
            "subject_alias": self.subject_alias,
            "model": bundle["model_execution_contracts"][reviewer],
            "invocation": {
                "invocation_id": "synthetic-invocation-" + reviewer.lower(),
                "interface": "offline-test-fixture",
                "started_at": "2026-07-17T00:00:00+00:00",
                "completed_at": "2026-07-17T00:00:01+00:00",
            },
            "prompt_sha256": bundle_manifest["prompt_sha256"][reviewer],
            "input_bundle_sha256": bundle_manifest["review_bundle_sha256"],
            "method_inventory_sha256": inventory_sha256(self.inventory_id),
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
                "subject_alias": self.subject_alias,
                "model": bundle["model_execution_contracts"][reviewer],
                "authorized_hrd_state": "no_call",
                "required_method_ids": self.methods,
                "method_inventory": inventory_payload(self.inventory_id),
                "method_inventory_sha256": inventory_sha256(self.inventory_id),
                "model_catalog_receipt_sha256": "c" * 64,
                "claim_count": 7,
                "covered_evidence_ids": [f"E{index:03d}" for index in range(1, 8)],
                "disagreement_claim_count": 3,
                "bundle_manifest_sha256": sha256(
                    self.bundle_dir / "bundle_manifest.json"
                ),
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
        review_bundle: Optional[Path] = None,
        bundle_manifest: Optional[Path] = None,
        reviewer_a_dir: Optional[Path] = None,
        reviewer_b_dir: Optional[Path] = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(GENERATOR)]
        for source in source_manifests if source_manifests is not None else self.source_manifests:
            command.extend(["--source-manifest", str(source)])
        for method in methods if methods is not None else self.methods:
            command.extend(["--require-method", method])
        command.extend(
            [
                "--review-bundle",
                str(review_bundle or self.bundle_dir / "review_bundle.json"),
                "--bundle-manifest",
                str(bundle_manifest or self.bundle_dir / "bundle_manifest.json"),
                "--reviewer-a-dir",
                str(reviewer_a_dir or self.review_a),
                "--reviewer-b-dir",
                str(reviewer_b_dir or self.review_b),
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

    def refresh_input_manifest_hash(self, evidence_id: str, source_manifest: Path) -> None:
        manifest_path = self.bundle_dir / "bundle_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["input_manifest_sha256"][evidence_id] = sha256(source_manifest)
        write_json(manifest_path, manifest)

    def mutate_bundle_models(self, mutate) -> None:
        bundle_path = self.bundle_dir / "review_bundle.json"
        manifest_path = self.bundle_dir / "bundle_manifest.json"
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mutate(bundle["model_execution_contracts"])
        manifest["model_execution_contracts"] = bundle["model_execution_contracts"]
        write_json(bundle_path, bundle)
        manifest["review_bundle_sha256"] = sha256(bundle_path)
        write_json(manifest_path, manifest)


def run_synthesis_main(fixture: SynthesisFixture) -> None:
    argv = [str(GENERATOR)]
    for source_manifest in fixture.source_manifests:
        argv.extend(["--source-manifest", str(source_manifest)])
    for method_id in fixture.methods:
        argv.extend(["--require-method", method_id])
    argv.extend(
        [
            "--review-bundle",
            str(fixture.bundle_dir / "review_bundle.json"),
            "--bundle-manifest",
            str(fixture.bundle_dir / "bundle_manifest.json"),
            "--reviewer-a-dir",
            str(fixture.review_a),
            "--reviewer-b-dir",
            str(fixture.review_b),
            "--output-dir",
            str(fixture.output_dir),
        ]
    )
    with mock.patch.object(sys, "argv", argv):
        GENERATE.main()


class GenerateSynthesisTests(unittest.TestCase):
    def test_rejects_non_lowercase_ai_bundle_manifest_hashes(self) -> None:
        cases = (
            ("review_bundle", ("review_bundle_sha256",), "AI bundle"),
            (
                "source_manifest",
                ("input_manifest_sha256", "E001"),
                "E001 source manifest",
            ),
            ("reviewer_prompt", ("prompt_sha256", "A"), "reviewer A prompt"),
        )

        for name, path, message in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-uppercase-hash-"
            ) as temporary:
                fixture = SynthesisFixture(Path(temporary))
                manifest_path = fixture.bundle_dir / "bundle_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                target = manifest
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = target[path[-1]].upper()
                write_json(manifest_path, manifest)

                result = fixture.run()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("malformed SHA-256 for " + message, result.stderr)
                self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_rejects_inexact_ai_bundle_envelopes_before_rendering(self) -> None:
        cases = (
            (
                "review_bundle.json",
                lambda fixture: fixture.bundle_dir / "review_bundle.json",
                lambda fixture: fixture.refresh_bundle_hash(),
                "AI review bundle envelope is not exact",
            ),
            (
                "bundle_manifest.json",
                lambda fixture: fixture.bundle_dir / "bundle_manifest.json",
                lambda fixture: None,
                "AI review bundle manifest envelope is not exact",
            ),
        )
        for filename, resolve_path, rebind, message in cases:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-exact-bundle-"
            ) as temporary:
                fixture = SynthesisFixture(Path(temporary))
                path = resolve_path(fixture)
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["legacy_note"] = "accepted"
                write_json(path, payload)
                rebind(fixture)

                result = fixture.run()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)
                self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_synthesis_packet_install_is_create_only_and_fsynced(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")

            with mock.patch.object(
                GENERATE.os,
                "fsync",
                wraps=GENERATE.os.fsync,
            ) as fsync:
                GENERATE.copy_create_only(source, destination)

            self.assertEqual(destination.read_bytes(), b"one\n")
            self.assertEqual(fsync.call_count, 2)

            source.write_bytes(b"two\n")
            with self.assertRaisesRegex(
                ValueError,
                "synthesis output packet already exists",
            ):
                GENERATE.copy_create_only(source, destination)

            self.assertEqual(destination.read_bytes(), b"one\n")

    def test_synthesis_packet_copy_rejects_symlinked_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            root = Path(temporary)
            real_source = root / "real-source.txt"
            source = root / "source.txt"
            destination = root / "report.md"
            real_source.write_bytes(b"one\n")
            source.symlink_to(real_source)

            with self.assertRaisesRegex(ValueError, "staged synthesis packet"):
                GENERATE.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_synthesis_packet_copy_rejects_symlinked_destination_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            real_parent = root / "attacker"
            linked_parent = root / "linked-parent"
            source.write_bytes(b"one\n")
            real_parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                GENERATE.copy_create_only(
                    source,
                    linked_parent / "synthesis" / "report.md",
                )

            self.assertFalse((real_parent / "synthesis" / "report.md").exists())

    def test_synthesis_packet_copy_revalidates_copied_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")
            real_fsync_directory = GENERATE.fsync_directory

            def tamper_after_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                destination.write_bytes(b"tampered\n")

            with (
                mock.patch.object(
                    GENERATE,
                    "fsync_directory",
                    side_effect=tamper_after_directory_fsync,
                ),
                self.assertRaisesRegex(ValueError, "changed during copy"),
            ):
                GENERATE.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_synthesis_staged_file_write_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            root = Path(temporary)
            output = root / "report.md"
            real_fsync_directory = GENERATE.fsync_directory

            def tamper_after_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_bytes(b"tampered\n")

            with (
                mock.patch.object(
                    GENERATE,
                    "fsync_directory",
                    side_effect=tamper_after_directory_fsync,
                ),
                self.assertRaisesRegex(ValueError, "changed during write"),
            ):
                GENERATE.write_staged_text(output, "# report\n")

            self.assertFalse(output.exists())

    def test_synthesis_rejects_stale_staged_report_manifest_binding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            write_synthesis_manifest(staging / "report_manifest.json", report, agreement)

            report.write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis manifest is stale for report.md",
            ):
                GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_rejects_stale_staged_agreement_manifest_binding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            write_synthesis_manifest(staging / "report_manifest.json", report, agreement)

            agreement.write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis manifest is stale for agreement_disagreement.csv",
            ):
                GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_rejects_non_string_staged_packet_hashes(self) -> None:
        hash64 = "1" * 64
        numeric_hash = int(hash64)
        cases = (
            (
                "report",
                lambda payload: payload.__setitem__("report_sha256", numeric_hash),
                "comparative synthesis report.md",
            ),
            (
                "agreement",
                lambda payload: payload.__setitem__(
                    "agreement_disagreement_sha256",
                    numeric_hash,
                ),
                "comparative synthesis agreement_disagreement.csv",
            ),
            (
                "support agreement",
                lambda payload: payload["support_sha256"].__setitem__(
                    "agreement_disagreement.csv",
                    numeric_hash,
                ),
                "comparative synthesis support agreement_disagreement.csv",
            ),
        )

        for label, mutate, message in cases:
            with self.subTest(label), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-"
            ) as temporary:
                staging = Path(temporary)
                report = staging / "report.md"
                agreement = staging / "agreement_disagreement.csv"
                manifest = staging / "report_manifest.json"
                GENERATE.write_staged_text(report, "# Report\n")
                write_synthesis_agreement(agreement)
                payload = write_synthesis_manifest(manifest, report, agreement)
                payload["source_sha256"]["agreement_disagreement.csv"] = hash64
                payload["source_sha256"]["generator"] = hash64
                mutate(payload)
                write_json(manifest, payload)

                with (
                    mock.patch.object(GENERATE, "sha256", return_value=hash64),
                    self.assertRaisesRegex(
                        ValueError,
                        "malformed SHA-256 for " + message,
                    ),
                ):
                    GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_rejects_non_exact_report_manifest_envelope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            payload = write_synthesis_manifest(manifest, report, agreement)
            payload["legacy_note"] = "accepted"
            write_json(manifest, payload)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis manifest envelope is not exact",
            ):
                GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_rejects_incomplete_source_hash_inventory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            payload = write_synthesis_manifest(manifest, report, agreement)
            del payload["source_sha256"]["reviewer_B_claims.csv"]
            write_json(manifest, payload)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis source hashes are not exact",
            ):
                GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_rejects_stale_agreement_source_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            payload = write_synthesis_manifest(manifest, report, agreement)
            payload["source_sha256"]["agreement_disagreement.csv"] = "0" * 64
            write_json(manifest, payload)

            with self.assertRaisesRegex(
                ValueError,
                "source hash is stale for agreement_disagreement.csv",
            ):
                GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_rejects_stale_expected_external_source_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            payload = write_synthesis_manifest(manifest, report, agreement)
            expected_source_hashes = dict(payload["source_sha256"])
            payload["source_sha256"]["review_bundle.json"] = "0" * 64
            write_json(manifest, payload)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis source hashes are stale",
            ):
                GENERATE.require_synthesis_report_manifest(
                    staging,
                    expected_source_hashes=expected_source_hashes,
                )

    def test_synthesis_rejects_stale_readiness_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            payload = write_synthesis_manifest(manifest, report, agreement)
            payload["review_summary"]["readiness"]["authorized_hrd_state"] = "positive"
            write_json(manifest, payload)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis readiness summary is stale",
            ):
                GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_rejects_stale_method_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            payload = write_synthesis_manifest(manifest, report, agreement)
            payload["review_summary"]["methods"][0]["evidence_status"] = "ready"
            write_json(manifest, payload)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis method summary is not exact",
            ):
                GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_rejects_rekeyed_agreement_method_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            rows = GENERATE.read_agreement(agreement)
            rows[1]["evidence_id"] = "E001"
            agreement.unlink()
            GENERATE.write_agreement(agreement, rows)
            write_synthesis_manifest(manifest, report, agreement)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis agreement rows are not exact",
            ):
                GENERATE.require_synthesis_report_manifest(staging)

    def test_reviewer_claims_must_preserve_exact_fields(self) -> None:
        cases = (
            (
                lambda row: row.__setitem__("proposed_hrd_state", " no_call"),
                "claims.csv contains a non-exact field: proposed_hrd_state",
            ),
            (
                lambda row: row.__setitem__("evidence_ids", "E001; E002"),
                "claim C001 evidence_ids is not exact",
            ),
        )
        for mutate, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-claims-",
            ) as temporary:
                fixture = SynthesisFixture(Path(temporary))
                bundle = json.loads(
                    (fixture.bundle_dir / "review_bundle.json").read_text(
                        encoding="utf-8",
                    ),
                )
                evidence_by_id = {
                    row["evidence_id"]: row for row in bundle["evidence_sources"]
                }
                claims = fixture.review_a / "claims.csv"
                with claims.open(newline="", encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
                mutate(rows[0])
                with claims.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=CLAIMS_FIELDS,
                        lineterminator="\n",
                    )
                    writer.writeheader()
                    writer.writerows(rows)

                with self.assertRaisesRegex(ValueError, message):
                    GENERATE.read_claims(claims, evidence_by_id, "no_call")

    def test_synthesis_agreement_must_preserve_exact_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-agreement-") as temporary:
            agreement = Path(temporary) / "agreement_disagreement.csv"
            write_synthesis_agreement(agreement)
            rows = GENERATE.read_agreement(agreement)
            rows[0]["resolution_needed"] = "not_specified\nhidden"
            agreement.unlink()
            GENERATE.write_agreement(agreement, rows)

            with self.assertRaisesRegex(
                ValueError,
                "agreement_disagreement.csv contains a non-exact field: resolution_needed",
            ):
                GENERATE.read_agreement(agreement)

    def test_synthesis_rejects_stale_agreement_count_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            payload = write_synthesis_manifest(manifest, report, agreement)
            payload["review_summary"]["agreement_status_counts"] = {
                "partial_agreement": len(REQUIRED_METHOD_IDS),
            }
            write_json(manifest, payload)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis agreement counts are stale",
            ):
                GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_rejects_boolean_count_summaries(self) -> None:
        cases = (
            (
                lambda summary: summary["reviewers"][0].__setitem__(
                    "claim_count", True
                ),
                "comparative synthesis reviewer summary is not exact",
            ),
            (
                lambda summary: summary["reviewers"][0].__setitem__(
                    "disagreement_claim_count", False
                ),
                "comparative synthesis reviewer summary is not exact",
            ),
            (
                lambda summary: summary["agreement_status_counts"].__setitem__(
                    "concordant", True
                ),
                "comparative synthesis agreement counts are not exact",
            ),
        )

        for mutate, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-"
            ) as temporary:
                staging = Path(temporary)
                report = staging / "report.md"
                agreement = staging / "agreement_disagreement.csv"
                manifest = staging / "report_manifest.json"
                GENERATE.write_staged_text(report, "# Report\n")
                write_synthesis_agreement(agreement)
                payload = write_synthesis_manifest(manifest, report, agreement)
                mutate(payload["review_summary"])
                write_json(manifest, payload)

                with self.assertRaisesRegex(ValueError, message):
                    GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_rejects_stale_structured_disagreement_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            payload = write_synthesis_manifest(manifest, report, agreement)
            payload["review_summary"]["structured_disagreements"] = [
                {
                    "evidence_id": "E001",
                    "method_id": REQUIRED_METHOD_IDS[0],
                    "agreement_status": "concordant",
                    "types": ["source_partial_evidence"],
                    "resolution_needed": "not_specified",
                }
            ]
            write_json(manifest, payload)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis structured disagreements are stale",
            ):
                GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_rejects_inexact_staged_inventory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            staging = Path(temporary)
            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            write_synthesis_manifest(manifest, report, agreement)
            (staging / "unexpected.tmp").write_text(
                "unbound synthesis scratch\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis inventory is not exact",
            ):
                GENERATE.require_synthesis_report_manifest(staging)

    def test_synthesis_install_failure_removes_only_installed_packet_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-install-") as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "synthesis"
            staging.mkdir()
            output.mkdir()
            staged_paths = []
            for name in (
                "report.md",
                "agreement_disagreement.csv",
                "report_manifest.json",
            ):
                path = staging / name
                path.write_text(f"{name}\n", encoding="utf-8")
                staged_paths.append(path)

            real_copy = GENERATE.copy_create_only

            def fail_with_unexpected_child(source: Path, destination: Path) -> None:
                real_copy(source, destination)
                if destination.name == "agreement_disagreement.csv":
                    (destination.parent / "unexpected.tmp").write_text(
                        "stray partial file\n",
                        encoding="utf-8",
                    )
                    raise ValueError("synthetic install failure")

            with (
                mock.patch.object(
                    GENERATE,
                    "copy_create_only",
                    side_effect=fail_with_unexpected_child,
                ),
                self.assertRaisesRegex(ValueError, "synthetic install failure"),
            ):
                GENERATE.install_packet_create_only(staged_paths, output)

            self.assertTrue(output.is_dir())
            for name in GENERATE.OUTPUT_FILES:
                self.assertFalse((output / name).exists())
            self.assertEqual(
                (output / "unexpected.tmp").read_text(encoding="utf-8"),
                "stray partial file\n",
            )

    def test_synthesis_packet_install_removes_partial_after_file_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")

            with (
                mock.patch.object(
                    GENERATE.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                GENERATE.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_synthesis_packet_install_removes_partial_after_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")

            with (
                mock.patch.object(
                    GENERATE.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                GENERATE.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_synthesis_install_removes_installed_files_after_final_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-install-") as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "synthesis"
            staging.mkdir()
            output.mkdir()
            staged_paths = []
            for name in (
                "report.md",
                "agreement_disagreement.csv",
                "report_manifest.json",
            ):
                path = staging / name
                path.write_text(f"{name}\n", encoding="utf-8")
                staged_paths.append(path)

            with (
                mock.patch.object(
                    GENERATE,
                    "fsync_directory",
                    side_effect=(
                        None,
                        None,
                        None,
                        OSError("synthetic synthesis directory fsync failure"),
                    ),
                ),
                self.assertRaisesRegex(
                    OSError,
                    "synthetic synthesis directory fsync failure",
                ),
            ):
                GENERATE.install_packet_create_only(staged_paths, output)

            self.assertTrue(output.is_dir())
            self.assertEqual([], list(output.iterdir()))

    def test_synthesis_install_removes_installed_files_after_stale_installed_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-install-") as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "synthesis"
            staging.mkdir()
            output.mkdir()

            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            payload = write_synthesis_manifest(manifest, report, agreement)
            payload["agreement_disagreement_sha256"] = "0" * 64
            payload["support_sha256"]["agreement_disagreement.csv"] = "0" * 64
            write_json(manifest, payload)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis manifest is stale for "
                "agreement_disagreement.csv",
            ):
                GENERATE.install_packet_create_only(
                    (report, agreement, manifest),
                    output,
                )

            self.assertTrue(output.is_dir())
            self.assertEqual([], list(output.iterdir()))

    def test_synthesis_install_rechecks_installed_files_after_final_directory_fsync(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-install-") as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "synthesis"
            staging.mkdir()
            output.mkdir()
            staged_paths = []
            for name in (
                "report.md",
                "agreement_disagreement.csv",
                "report_manifest.json",
            ):
                path = staging / name
                path.write_text(f"{name}\n", encoding="utf-8")
                staged_paths.append(path)

            real_fsync_directory = GENERATE.fsync_directory

            def tamper_after_output_fsync(path: Path) -> None:
                real_fsync_directory(path)
                if path == output:
                    (output / "agreement_disagreement.csv").write_text(
                        "tampered after final output fsync\n",
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    GENERATE,
                    "fsync_directory",
                    side_effect=tamper_after_output_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "synthesis output packet changed during install: "
                    "agreement_disagreement.csv",
                ),
            ):
                GENERATE.install_packet_create_only(staged_paths, output)

            self.assertTrue(output.is_dir())
            self.assertEqual([], list(output.iterdir()))

    def test_synthesis_install_removes_installed_files_after_inexact_final_inventory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-install-") as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "synthesis"
            staging.mkdir()
            output.mkdir()

            report = staging / "report.md"
            agreement = staging / "agreement_disagreement.csv"
            manifest = staging / "report_manifest.json"
            GENERATE.write_staged_text(report, "# Report\n")
            write_synthesis_agreement(agreement)
            write_synthesis_manifest(manifest, report, agreement)
            real_fsync_directory = GENERATE.fsync_directory

            def create_unexpected_file_after_final_fsync(path: Path) -> None:
                real_fsync_directory(path)
                if path == output:
                    (output / "unexpected.tmp").write_text(
                        "unbound final synthesis file\n",
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    GENERATE,
                    "fsync_directory",
                    side_effect=create_unexpected_file_after_final_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "comparative synthesis inventory is not exact",
                ),
            ):
                GENERATE.install_packet_create_only(
                    (report, agreement, manifest),
                    output,
                )

            self.assertTrue(output.is_dir())
            for name in GENERATE.OUTPUT_FILES:
                self.assertFalse((output / name).exists())
            self.assertEqual(
                (output / "unexpected.tmp").read_text(encoding="utf-8"),
                "unbound final synthesis file\n",
            )

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
            self.assertIn(
                "Pinned latest-model contract: `synthetic-provider-a/latest-model-a`, "
                "catalog-verified at `2026-07-17T00:00:00+00:00`.",
                report,
            )
            self.assertIn(
                "Pinned latest-model contract: `synthetic-provider-b/latest-model-b`, "
                "catalog-verified at `2026-07-17T00:00:00+00:00`.",
                report,
            )
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

    def test_synthesis_source_hashes_stay_bound_to_verified_bundle_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            bundle_manifest_path = fixture.bundle_dir / "bundle_manifest.json"
            verified_hash = sha256(bundle_manifest_path)
            real_verify_sources = GENERATE.verify_sources

            def tamper_after_bundle_verification(*args, **kwargs):
                rows, hashes = real_verify_sources(*args, **kwargs)
                manifest = json.loads(
                    bundle_manifest_path.read_text(encoding="utf-8")
                )
                manifest["generated_at"] = "2026-07-18T00:00:00+00:00"
                write_json(bundle_manifest_path, manifest)
                return rows, hashes

            with mock.patch.object(
                GENERATE,
                "verify_sources",
                side_effect=tamper_after_bundle_verification,
            ):
                run_synthesis_main(fixture)

            manifest = json.loads(
                (fixture.output_dir / "report_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["source_sha256"]["bundle_manifest.json"],
                verified_hash,
            )
            self.assertNotEqual(
                manifest["source_sha256"]["bundle_manifest.json"],
                sha256(bundle_manifest_path),
            )

    def test_synthesis_source_hashes_use_parsed_bundle_digest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            bundle_path = fixture.bundle_dir / "review_bundle.json"
            verified_hash = sha256(bundle_path)
            tampered_hash = ""
            real_load = GENERATE.load_object_with_sha256

            def tamper_after_bundle_parse(path: Path, label: str):
                nonlocal tampered_hash
                value, digest = real_load(path, label)
                if label == "review_bundle.json" and not tampered_hash:
                    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
                    bundle["generated_at"] = "2026-07-18T00:00:00+00:00"
                    write_json(bundle_path, bundle)
                    tampered_hash = sha256(bundle_path)
                return value, digest

            with mock.patch.object(
                GENERATE,
                "load_object_with_sha256",
                side_effect=tamper_after_bundle_parse,
            ):
                run_synthesis_main(fixture)

            manifest = json.loads(
                (fixture.output_dir / "report_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["source_sha256"]["review_bundle.json"],
                verified_hash,
            )
            self.assertNotEqual(tampered_hash, verified_hash)

    def test_synthesis_source_hashes_use_parsed_bundle_manifest_digest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            bundle_manifest_path = fixture.bundle_dir / "bundle_manifest.json"
            verified_hash = sha256(bundle_manifest_path)
            tampered_hash = ""
            real_load = GENERATE.load_object_with_sha256

            def tamper_after_bundle_manifest_parse(path: Path, label: str):
                nonlocal tampered_hash
                value, digest = real_load(path, label)
                if label == "bundle_manifest.json" and not tampered_hash:
                    manifest = json.loads(
                        bundle_manifest_path.read_text(encoding="utf-8")
                    )
                    manifest["generated_at"] = "2026-07-18T00:00:00+00:00"
                    write_json(bundle_manifest_path, manifest)
                    tampered_hash = sha256(bundle_manifest_path)
                return value, digest

            with mock.patch.object(
                GENERATE,
                "load_object_with_sha256",
                side_effect=tamper_after_bundle_manifest_parse,
            ):
                run_synthesis_main(fixture)

            manifest = json.loads(
                (fixture.output_dir / "report_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["source_sha256"]["bundle_manifest.json"],
                verified_hash,
            )
            self.assertNotEqual(tampered_hash, verified_hash)

    def test_synthesis_source_hashes_stay_bound_to_verified_source_manifests(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            source_manifest_path = fixture.source_manifests[0]
            verified_hash = sha256(source_manifest_path)
            real_verify_review = GENERATE.verify_review
            tampered = False

            def tamper_after_source_verification(*args, **kwargs):
                nonlocal tampered
                if not tampered:
                    manifest = json.loads(
                        source_manifest_path.read_text(encoding="utf-8")
                    )
                    manifest["review_summary"]["limitations"].append(
                        "Late unverified source mutation."
                    )
                    write_json(source_manifest_path, manifest)
                    tampered = True
                return real_verify_review(*args, **kwargs)

            with mock.patch.object(
                GENERATE,
                "verify_review",
                side_effect=tamper_after_source_verification,
            ):
                run_synthesis_main(fixture)

            manifest = json.loads(
                (fixture.output_dir / "report_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["source_sha256"]["E001_report_manifest.json"],
                verified_hash,
            )
            self.assertNotEqual(
                manifest["source_sha256"]["E001_report_manifest.json"],
                sha256(source_manifest_path),
            )

    def test_synthesis_source_hashes_use_parsed_source_manifest_digest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            source_manifest_path = fixture.source_manifests[0]
            verified_hash = sha256(source_manifest_path)
            tampered_hash = ""
            real_load = GENERATE.load_object_with_sha256

            def tamper_after_source_parse(path: Path, label: str):
                nonlocal tampered_hash
                value, digest = real_load(path, label)
                if label == "E001 report_manifest.json" and not tampered_hash:
                    source = json.loads(source_manifest_path.read_text(encoding="utf-8"))
                    source["review_summary"]["limitations"].append(
                        "Late unverified source mutation."
                    )
                    write_json(source_manifest_path, source)
                    tampered_hash = sha256(source_manifest_path)
                return value, digest

            with mock.patch.object(
                GENERATE,
                "load_object_with_sha256",
                side_effect=tamper_after_source_parse,
            ):
                run_synthesis_main(fixture)

            manifest = json.loads(
                (fixture.output_dir / "report_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["source_sha256"]["E001_report_manifest.json"],
                verified_hash,
            )
            self.assertNotEqual(tampered_hash, verified_hash)

    def test_synthesis_manifest_rejects_inexact_support_inventory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            result = fixture.run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            manifest_path = fixture.output_dir / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["support_sha256"]["unexpected.json"] = "a" * 64
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis manifest support hashes are not exact",
            ):
                GENERATE.require_synthesis_report_manifest(fixture.output_dir)

    def test_synthesis_manifest_rejects_incomplete_reviewer_model_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            result = fixture.run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest_path = fixture.output_dir / "report_manifest.json"

            for label, mutate_model in (
                (
                    "coerced provider",
                    lambda model: model.__setitem__("provider", 123),
                ),
                (
                    "padded model",
                    lambda model: model.__setitem__("model_id", " latest-model-a\n"),
                ),
                (
                    "missing catalog timestamp",
                    lambda model: model.pop("catalog_verified_at"),
                ),
                (
                    "non-attested model",
                    lambda model: model.__setitem__("latest_available_attested", False),
                ),
                (
                    "malformed catalog timestamp",
                    lambda model: model.__setitem__("catalog_verified_at", "not-iso8601"),
                ),
            ):
                with self.subTest(label):
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    mutate_model(manifest["review_summary"]["reviewers"][0]["model"])
                    write_json(manifest_path, manifest)

                    with self.assertRaisesRegex(
                        ValueError,
                        "comparative synthesis reviewer A model summary is not exact",
                    ):
                        GENERATE.require_synthesis_report_manifest(
                            fixture.output_dir
                        )

    def test_synthesis_manifest_rejects_extra_reviewer_summary_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            result = fixture.run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            manifest_path = fixture.output_dir / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["review_summary"]["reviewers"][0]["unbound_note"] = (
                "late reviewer annotation"
            )
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis reviewer summary is not exact",
            ):
                GENERATE.require_synthesis_report_manifest(fixture.output_dir)

    def test_synthesis_manifest_rejects_extra_review_summary_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            result = fixture.run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            manifest_path = fixture.output_dir / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["review_summary"]["unbound_note"] = "late synthesis annotation"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                ValueError,
                "comparative synthesis review summary is missing",
            ):
                GENERATE.require_synthesis_report_manifest(fixture.output_dir)

    def test_synthesis_manifest_preserves_reviewer_model_contracts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            result = fixture.run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            manifest = json.loads(
                (fixture.output_dir / "report_manifest.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(
                [
                    row["model"]
                    for row in manifest["review_summary"]["reviewers"]
                ],
                [
                    {
                        "catalog_verified_at": "2026-07-17T00:00:00+00:00",
                        "latest_available_attested": True,
                        "model_id": "latest-model-a",
                        "provider": "synthetic-provider-a",
                    },
                    {
                        "catalog_verified_at": "2026-07-17T00:00:00+00:00",
                        "latest_available_attested": True,
                        "model_id": "latest-model-b",
                        "provider": "synthetic-provider-b",
                    },
                ],
            )

    def test_bundle_rejects_reviewer_model_summary_drift(self) -> None:
        for label, mutate_models, message in (
            (
                "missing catalog timestamp",
                lambda models: models["A"].pop("catalog_verified_at"),
                "comparative synthesis reviewer A model summary is not exact",
            ),
            (
                "non-attested model",
                lambda models: models["A"].__setitem__(
                    "latest_available_attested", False
                ),
                "comparative synthesis reviewer A model summary is not exact",
            ),
            (
                "split catalog timestamp",
                lambda models: models["B"].__setitem__(
                    "catalog_verified_at", "2026-07-18T00:00:00+00:00"
                ),
                "reviewer model catalog timestamps differ",
            ),
            (
                "duplicate reviewer model",
                lambda models: models.__setitem__("B", dict(models["A"])),
                "reviewers must use distinct models",
            ),
        ):
            with self.subTest(label), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-"
            ) as temporary:
                fixture = SynthesisFixture(Path(temporary))
                fixture.mutate_bundle_models(mutate_models)

                with self.assertRaisesRegex(ValueError, message):
                    GENERATE.verify_bundle(
                        fixture.bundle_dir / "review_bundle.json",
                        fixture.bundle_dir / "bundle_manifest.json",
                        tuple(fixture.methods),
                    )

    def test_synthesis_manifest_rejects_reviewer_model_summary_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            result = fixture.run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest_path = fixture.output_dir / "report_manifest.json"

            for label, mutate_summary in (
                (
                    "duplicate reviewer model",
                    lambda summary: summary["reviewers"][1].__setitem__(
                        "model", dict(summary["reviewers"][0]["model"])
                    ),
                ),
                (
                    "split catalog timestamp",
                    lambda summary: summary["reviewers"][1]["model"].__setitem__(
                        "catalog_verified_at", "2026-07-18T00:00:00+00:00"
                    ),
                ),
            ):
                with self.subTest(label):
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    mutate_summary(manifest["review_summary"])
                    write_json(manifest_path, manifest)

                    with self.assertRaisesRegex(
                        ValueError,
                        "comparative synthesis reviewer summary is not exact",
                    ):
                        GENERATE.require_synthesis_report_manifest(
                            fixture.output_dir
                        )

    def test_hcc1395_inventory_generates_hcc_bound_synthesis(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-hcc-") as temporary:
            fixture = SynthesisFixture(
                Path(temporary),
                inventory_id=HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID,
                methods=list(HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS),
                subject_alias="subject99",
            )

            result = fixture.run()

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = (fixture.output_dir / "report.md").read_text(encoding="utf-8")
            manifest = json.loads((fixture.output_dir / "report_manifest.json").read_text())
            self.assertEqual(
                manifest["review_summary"]["process"]["method_inventory"],
                inventory_payload(HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID),
            )
            self.assertEqual(
                [row["method_id"] for row in manifest["review_summary"]["methods"]],
                list(HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS),
            )
            self.assertNotIn("rosalind_diana_wgs", report)
            self.assertNotIn("subject01", report)

    def test_existing_packet_files_fail_create_only_and_remain_unchanged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            original_hashes = {
                filename: sha256(fixture.output_dir / filename)
                for filename in PUBLISH_PRIVATE.METHOD_CONTRACTS[
                    "comparative_hrd_synthesis"
                ]["files"]
            }

            result = fixture.run(fixture.source_manifests[:1], fixture.methods[:1])

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "synthesis output already contains packet files",
                result.stdout + result.stderr,
            )
            self.assertEqual(
                {
                    filename: sha256(fixture.output_dir / filename)
                    for filename in original_hashes
                },
                original_hashes,
            )

    def test_preexisting_report_fails_create_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            fixture.output_dir.mkdir()
            stale_report = fixture.output_dir / "report.md"
            stale_report.write_text("stale synthesis report\n", encoding="utf-8")

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "synthesis output already contains packet files: report.md",
                result.stdout + result.stderr,
            )
            self.assertEqual(
                stale_report.read_text(encoding="utf-8"),
                "stale synthesis report\n",
            )

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

    def test_symlinked_output_dir_fails_before_writing_packet(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-output-") as temporary:
            root = Path(temporary)
            fixture = SynthesisFixture(root)
            real_output = root / "synthesis-real"
            real_output.mkdir()
            fixture.output_dir.symlink_to(real_output, target_is_directory=True)

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "synthesis output may not be a symlink",
                result.stdout + result.stderr,
            )
            self.assertFalse((real_output / "report_manifest.json").exists())

    def test_output_below_symlinked_parent_fails_before_writing_packet(self) -> None:
        self.assertFalse(GENERATE.is_platform_root_alias(Path("linked-parent")))

        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-output-"
            ) as temporary:
                root = Path(temporary)
                fixture = SynthesisFixture(root)
                real_parent = root / "synthesis-real-parent"
                if nested == "existing":
                    (real_parent / nested).mkdir(parents=True)
                else:
                    real_parent.mkdir()
                linked_parent = root / "synthesis-linked-parent"
                linked_parent.symlink_to(real_parent, target_is_directory=True)
                fixture.output_dir = linked_parent / nested / "nested-synthesis"

                result = fixture.run()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "synthesis output parent may not be a symlink",
                    result.stdout + result.stderr,
                )
                self.assertFalse((real_parent / nested / "nested-synthesis").exists())

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

    def test_changed_source_support_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            fixture.source_manifests[0].with_name("support.json").write_text(
                '{"changed": true}\n',
                encoding="utf-8",
            )

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                f"support hash mismatch for {fixture.methods[0]}: support.json",
                result.stdout + result.stderr,
            )
            self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_malformed_source_artifact_hash_ids_fail_closed(self) -> None:
        for malformed in (
            "",
            " safe_summary",
            "safe summary",
            "safe/summary",
            "safe|summary",
            "true",
            "false",
            "null",
            7,
            True,
        ):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-source-hash-"
            ) as temporary:
                fixture = SynthesisFixture(Path(temporary))
                source_path = fixture.source_manifests[0]
                source = json.loads(source_path.read_text(encoding="utf-8"))
                source["source_sha256"] = {
                    malformed: next(iter(source["source_sha256"].values()))
                }
                write_json(source_path, source)
                fixture.refresh_input_manifest_hash("E001", source_path)

                result = fixture.run()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"malformed source-artifact ID for {fixture.methods[0]}",
                    result.stdout + result.stderr,
                )
                self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_duplicate_source_artifact_hash_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="hrd-synthesis-source-hash-"
        ) as temporary:
            fixture = SynthesisFixture(Path(temporary))
            source_path = fixture.source_manifests[0]
            source = json.loads(source_path.read_text(encoding="utf-8"))
            digest = next(iter(source["source_sha256"].values()))
            source["source_sha256"] = {}
            payload = (
                json.dumps(source, indent=2, sort_keys=True)
                .replace(
                    '  "source_sha256": {},',
                    (
                        '  "source_sha256": {\n'
                        f'    "safe_summary": "{digest}",\n'
                        f'    "safe_summary": "{digest}"\n'
                        "  },"
                    ),
                )
                + "\n"
            )
            source_path.write_text(payload, encoding="utf-8")
            fixture.refresh_input_manifest_hash("E001", source_path)

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "duplicate JSON object name in E001 report_manifest.json: safe_summary",
                result.stdout + result.stderr,
            )
            self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_unbound_source_support_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            write_json(fixture.source_manifests[0].with_name("unbound.json"), {"unbound": True})

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                f"support inventory is not exact for {fixture.methods[0]}",
                result.stdout + result.stderr,
            )
            self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_symlinked_source_support_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            support = fixture.source_manifests[0].with_name("support.json")
            copy = Path(temporary) / "linked-support.json"
            copy.write_bytes(support.read_bytes())
            support.unlink()
            support.symlink_to(copy)

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                f"support hash mismatch for {fixture.methods[0]}: support.json",
                result.stdout + result.stderr,
            )
            self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_synthesis_sha256_rejects_symlinked_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-hash-") as temporary:
            root = Path(temporary)
            real_input = root / "real.json"
            linked_input = root / "linked.json"
            real_input.write_text("{}\n", encoding="utf-8")
            linked_input.symlink_to(real_input)

            with self.assertRaisesRegex(
                ValueError,
                "missing or unsafe linked.json SHA-256 input",
            ):
                GENERATE.sha256(linked_input)

    def test_synthesis_sha256_rejects_hash_input_that_changes_during_read(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="hrd-synthesis-stable-hash-"
        ) as temporary:
            input_path = Path(temporary) / "input.json"
            input_path.write_text('{"status": "ready"}\n', encoding="utf-8")
            real_read_bytes = Path.read_bytes
            calls = 0

            def mutating_read_bytes(path: Path) -> bytes:
                nonlocal calls
                data = real_read_bytes(path)
                calls += 1
                if calls == 1:
                    input_path.write_text('{"status": "mutated"}\n', encoding="utf-8")
                return data

            with mock.patch.object(Path, "read_bytes", mutating_read_bytes):
                with self.assertRaisesRegex(ValueError, "changed during read"):
                    GENERATE.sha256(input_path)

    def test_synthesis_json_rejects_input_that_changes_during_read(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="hrd-synthesis-stable-json-"
        ) as temporary:
            input_path = Path(temporary) / "input.json"
            input_path.write_text('{"status": "ready"}\n', encoding="utf-8")
            real_read_bytes = Path.read_bytes
            calls = 0

            def mutating_read_bytes(path: Path) -> bytes:
                nonlocal calls
                data = real_read_bytes(path)
                calls += 1
                if calls == 1:
                    input_path.write_text('{"status": "mutated"}\n', encoding="utf-8")
                return data

            with mock.patch.object(Path, "read_bytes", mutating_read_bytes):
                with self.assertRaisesRegex(ValueError, "changed during read"):
                    GENERATE.load_object(input_path, "input")

    def test_changed_ai_output_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            with (fixture.review_a / "report.md").open("a", encoding="utf-8") as handle:
                handle.write("altered after validation\n")
            result = fixture.run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("output differs", result.stdout + result.stderr)

    def test_stale_reviewer_bundle_manifest_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-stale-bundle-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            manifest_path = fixture.bundle_dir / "bundle_manifest.json"
            bundle_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            bundle_manifest["generated_at"] = "2026-07-18T00:00:00+00:00"
            write_json(manifest_path, bundle_manifest)

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "reviewer A bundle manifest changed after validation",
                result.stdout + result.stderr,
            )
            self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_synthesis_parses_reviewer_claims_from_hash_bound_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-stable-claims-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            bundle, bundle_manifest, bundle_hash, _, inventory_id = GENERATE.verify_bundle(
                fixture.bundle_dir / "review_bundle.json",
                fixture.bundle_dir / "bundle_manifest.json",
                fixture.methods,
            )
            claims_path = fixture.review_a / "claims.csv"
            real_stable_text = GENERATE.read_stable_text_with_sha256

            def mutate_claims_after_read(path: Path, label: str) -> tuple[str, str]:
                text, digest = real_stable_text(path, label)
                if path == claims_path:
                    claims_path.write_text("tampered\n", encoding="utf-8")
                return text, digest

            with mock.patch.object(
                GENERATE,
                "read_stable_text_with_sha256",
                side_effect=mutate_claims_after_read,
            ):
                review = GENERATE.verify_review(
                    fixture.review_a,
                    "A",
                    bundle,
                    bundle_manifest,
                    bundle_hash,
                    sha256(fixture.bundle_dir / "bundle_manifest.json"),
                    inventory_id,
                )

            self.assertEqual(len(fixture.methods), len(review["claims"]))

    def test_boolean_reviewer_validation_counts_fail_closed(self) -> None:
        cases = (
            ("claim_count", True, "claim count changed"),
            (
                "disagreement_claim_count",
                False,
                "disagreement count changed",
            ),
        )

        for field, value, message in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-validation-count-"
            ) as temporary:
                fixture = SynthesisFixture(Path(temporary))
                validation_path = fixture.review_a / "validation.json"
                validation = json.loads(
                    validation_path.read_text(encoding="utf-8")
                )
                validation[field] = value
                write_json(validation_path, validation)

                result = fixture.run()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)

    def test_rejects_non_integer_ai_bundle_schemas(self) -> None:
        cases = (
            "review_bundle.json",
            "bundle_manifest.json",
        )
        for filename in cases:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-bundle-schema-"
            ) as temporary:
                fixture = SynthesisFixture(Path(temporary))
                path = fixture.bundle_dir / filename
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["schema_version"] = 2.0
                write_json(path, payload)

                result = fixture.run()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unsupported AI bundle schema", result.stdout + result.stderr)
                self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_rejects_non_integer_reviewer_schemas(self) -> None:
        cases = (
            (
                "review_manifest.json",
                "unsupported review-manifest schema",
            ),
            (
                "validation.json",
                "reviewer A is not validated",
            ),
        )
        for filename, message in cases:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-review-schema-"
            ) as temporary:
                fixture = SynthesisFixture(Path(temporary))
                path = fixture.review_a / filename
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["schema_version"] = 2.0
                write_json(path, payload)

                result = fixture.run()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)
                self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_rejects_non_exact_reviewer_envelopes(self) -> None:
        cases = (
            (
                "validation extra field",
                "validation.json",
                lambda payload: payload.__setitem__("unexpected", True),
                "reviewer A validation envelope is not exact",
            ),
            (
                "manifest extra field",
                "review_manifest.json",
                lambda payload: payload.__setitem__("unexpected", True),
                "reviewer A manifest envelope is not exact",
            ),
            (
                "invocation extra field",
                "review_manifest.json",
                lambda payload: payload["invocation"].__setitem__(
                    "unexpected",
                    "leaked context",
                ),
                "reviewer A invocation metadata is incomplete",
            ),
            (
                "boolean invocation ID",
                "review_manifest.json",
                lambda payload: payload["invocation"].__setitem__(
                    "invocation_id",
                    True,
                ),
                "reviewer A invocation metadata is incomplete",
            ),
            (
                "padded invocation interface",
                "review_manifest.json",
                lambda payload: payload["invocation"].__setitem__(
                    "interface",
                    "offline-test-fixture\n",
                ),
                "reviewer A invocation metadata is incomplete",
            ),
        )
        for label, filename, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-review-envelope-"
            ) as temporary:
                fixture = SynthesisFixture(Path(temporary))
                path = fixture.review_a / filename
                payload = json.loads(path.read_text(encoding="utf-8"))
                mutate(payload)
                write_json(path, payload)
                if filename == "review_manifest.json" and "invocation" in label:
                    validation_path = fixture.review_a / "validation.json"
                    validation = json.loads(
                        validation_path.read_text(encoding="utf-8")
                    )
                    validation["review_manifest_sha256"] = sha256(path)
                    write_json(validation_path, validation)

                result = fixture.run()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)
                self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_rejects_non_integer_source_schema(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="hrd-synthesis-source-schema-"
        ) as temporary:
            fixture = SynthesisFixture(Path(temporary))
            source_path = fixture.source_manifests[0]
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            payload["schema_version"] = 1.0
            write_json(source_path, payload)

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported source report schema", result.stdout + result.stderr)
            self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_schema_version_checks_avoid_raw_comparisons(self) -> None:
        module = ast.parse(GENERATOR.read_text(encoding="utf-8"))
        raw_schema_version_comparisons = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Compare)
            and "schema_version" in ast.unparse(node)
        ]

        self.assertEqual(raw_schema_version_comparisons, [])

    def test_rejects_symlinked_cli_inputs_without_final_output(self) -> None:
        cases = (
            (
                lambda fixture, root: {
                    "review_bundle": (
                        root / "review-bundle-link.json"
                    ).symlink_to(fixture.bundle_dir / "review_bundle.json")
                    or root / "review-bundle-link.json",
                },
                "review_bundle.json",
            ),
            (
                lambda fixture, root: {
                    "bundle_manifest": (
                        root / "bundle-manifest-link.json"
                    ).symlink_to(fixture.bundle_dir / "bundle_manifest.json")
                    or root / "bundle-manifest-link.json",
                },
                "bundle_manifest.json",
            ),
            (
                lambda fixture, root: {
                    "source_manifests": [
                        (root / "source-manifest-link.json").symlink_to(
                            fixture.source_manifests[0]
                        )
                        or root / "source-manifest-link.json",
                        *fixture.source_manifests[1:],
                    ],
                },
                "E001 report_manifest.json",
            ),
            (
                lambda fixture, root: {
                    "reviewer_a_dir": (
                        root / "review-a-link"
                    ).symlink_to(fixture.review_a, target_is_directory=True)
                    or root / "review-a-link",
                },
                "reviewer A directory",
            ),
        )
        for build_kwargs, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-symlink-"
            ) as temporary:
                root = Path(temporary)
                fixture = SynthesisFixture(root)

                result = fixture.run(**build_kwargs(fixture, root))

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)
                self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_rejects_cli_inputs_below_symlinked_parent_without_final_output(self) -> None:
        cases = (
            (
                lambda fixture, linked_parent: {
                    "review_bundle": linked_parent / "review_bundle.json",
                },
                lambda fixture, real_parent: shutil.copy2(
                    fixture.bundle_dir / "review_bundle.json",
                    real_parent / "review_bundle.json",
                ),
                "review_bundle.json parent may not be a symlink",
            ),
            (
                lambda fixture, linked_parent: {
                    "bundle_manifest": linked_parent / "bundle_manifest.json",
                },
                lambda fixture, real_parent: shutil.copy2(
                    fixture.bundle_dir / "bundle_manifest.json",
                    real_parent / "bundle_manifest.json",
                ),
                "bundle_manifest.json parent may not be a symlink",
            ),
            (
                lambda fixture, linked_parent: {
                    "source_manifests": [
                        linked_parent / "report_manifest.json",
                        *fixture.source_manifests[1:],
                    ],
                },
                lambda fixture, real_parent: shutil.copy2(
                    fixture.source_manifests[0],
                    real_parent / "report_manifest.json",
                ),
                "E001 report_manifest.json parent may not be a symlink",
            ),
            (
                lambda fixture, linked_parent: {
                    "reviewer_a_dir": linked_parent / "review-a",
                },
                lambda fixture, real_parent: shutil.copytree(
                    fixture.review_a,
                    real_parent / "review-a",
                ),
                "reviewer A parent may not be a symlink",
            ),
        )
        for build_kwargs, prepare_real, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory(
                prefix="hrd-synthesis-parent-symlink-"
            ) as temporary:
                root = Path(temporary)
                fixture = SynthesisFixture(root)
                real_parent = root / "real-parent"
                linked_parent = root / "linked-parent"
                real_parent.mkdir()
                prepare_real(fixture, real_parent)
                linked_parent.symlink_to(real_parent, target_is_directory=True)

                result = fixture.run(**build_kwargs(fixture, linked_parent))

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)
                self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

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

    def test_rejects_stale_reviewer_validation_inventory_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hrd-synthesis-inventory-") as temporary:
            fixture = SynthesisFixture(Path(temporary))
            validation_path = fixture.review_a / "validation.json"
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            validation["method_inventory"] = {
                "inventory_id": "stale-reviewer-inventory",
                "ordered_method_ids": ["deterministic_full_wgs"],
            }
            write_json(validation_path, validation)

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "reviewer A validation method inventory",
                result.stdout + result.stderr,
            )

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

    def test_no_call_classification_authorization_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="hrd-synthesis-authorization-"
        ) as temporary:
            fixture = SynthesisFixture(Path(temporary))
            source_path = fixture.source_manifests[0]
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["classification_authorized"] = True
            write_json(source_path, source)

            bundle_path = fixture.bundle_dir / "review_bundle.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["evidence_sources"][0]["classification_authorized"] = True
            write_json(bundle_path, bundle)
            bundle_hash = sha256(bundle_path)

            bundle_manifest_path = fixture.bundle_dir / "bundle_manifest.json"
            bundle_manifest = json.loads(
                bundle_manifest_path.read_text(encoding="utf-8")
            )
            bundle_manifest["input_manifest_sha256"]["E001"] = sha256(source_path)
            bundle_manifest["review_bundle_sha256"] = bundle_hash
            write_json(bundle_manifest_path, bundle_manifest)

            for review_dir in (fixture.review_a, fixture.review_b):
                review_manifest_path = review_dir / "review_manifest.json"
                review_manifest = json.loads(
                    review_manifest_path.read_text(encoding="utf-8")
                )
                review_manifest["input_bundle_sha256"] = bundle_hash
                review_manifest["input_artifact_sha256"][
                    "review_bundle.json"
                ] = bundle_hash
                write_json(review_manifest_path, review_manifest)

                validation_path = review_dir / "validation.json"
                validation = json.loads(validation_path.read_text(encoding="utf-8"))
                validation["review_bundle_sha256"] = bundle_hash
                validation["review_manifest_sha256"] = sha256(review_manifest_path)
                write_json(validation_path, validation)

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no_call deterministic evidence", result.stdout + result.stderr)
            self.assertFalse((fixture.output_dir / "report_manifest.json").exists())

    def test_no_call_classification_qc_passed_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="hrd-synthesis-authorization-"
        ) as temporary:
            fixture = SynthesisFixture(Path(temporary))
            source_path = fixture.source_manifests[0]
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["classification_qc_status"] = "passed"
            write_json(source_path, source)

            bundle_path = fixture.bundle_dir / "review_bundle.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["evidence_sources"][0]["classification_qc_status"] = "passed"
            write_json(bundle_path, bundle)
            bundle_hash = sha256(bundle_path)

            bundle_manifest_path = fixture.bundle_dir / "bundle_manifest.json"
            bundle_manifest = json.loads(
                bundle_manifest_path.read_text(encoding="utf-8")
            )
            bundle_manifest["input_manifest_sha256"]["E001"] = sha256(source_path)
            bundle_manifest["review_bundle_sha256"] = bundle_hash
            write_json(bundle_manifest_path, bundle_manifest)

            for review_dir in (fixture.review_a, fixture.review_b):
                review_manifest_path = review_dir / "review_manifest.json"
                review_manifest = json.loads(
                    review_manifest_path.read_text(encoding="utf-8")
                )
                review_manifest["input_bundle_sha256"] = bundle_hash
                review_manifest["input_artifact_sha256"][
                    "review_bundle.json"
                ] = bundle_hash
                write_json(review_manifest_path, review_manifest)

                validation_path = review_dir / "validation.json"
                validation = json.loads(validation_path.read_text(encoding="utf-8"))
                validation["review_bundle_sha256"] = bundle_hash
                validation["review_manifest_sha256"] = sha256(review_manifest_path)
                write_json(validation_path, validation)

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "mark classification QC as applicable",
                result.stdout + result.stderr,
            )
            self.assertFalse((fixture.output_dir / "report_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
