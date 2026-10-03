"""Separate method qualification from individual case review. Missing evidence fails closed."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .scrna_intake import local_file
from .scrna_io import sha256_file, validate_artifact_index
from .scrna_private import digest_json

REQUIRED_REPORTS = {"matched_external_validation", "compartment_loss", "ambient", "doublets", "annotation"}
REQUIRED_CASE_REVIEWS = {"identity", "capture_metadata", "qc_losses", "ambient", "annotation_uncertainty"}
COUNT_AUDIT_CHECKS = {"source_to_all_cells_exact", "retained_counts_exact", "all_vendor_barcodes_preserved", "retained_selection_exact",
                      "qc_csv_matches_checkpoint", "core_failures_excluded", "doublets_excluded", "candidate_correction_monotone",
                      "malignancy_not_assessed", "summary_matches_barcodes"}
PATIENT_REQUIRED_GATES = {"input_cells_match", "retention", "cluster_count", "finite_embedding", "seed_stability", "raw_counts_preserved", "doublets_called"}


def verify_patient_run(run: Path) -> tuple[dict, dict, dict]:
    manifest = json.loads((run / "run_manifest.json").read_text())
    index = json.loads((run / "artifact_index.json").read_text())
    validate_artifact_index(index)
    if manifest.get("status") != "complete" or manifest.get("evidence_lane") not in {"patient_research", "public_control"} or sha256_file(run / "artifact_index.json") != manifest.get("artifact_index_sha256"):
        raise ValueError("Private run controls are incomplete/inconsistent")
    names = set()
    for item in index:
        path = local_file(run, item["path"])
        if path.stat().st_size != item["size_bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError("Private artifact integrity failure")
        names.add(item["path"])
    if not {"input_contract.json", "method_identity.json", "qc_summary.json", "intake_inspection.json", "source_hashes.json"} <= names:
        raise ValueError("Missing patient control artifacts")
    contract = json.loads((run / "input_contract.json").read_text())
    metrics = json.loads((run / "qc_summary.json").read_text())
    if set(metrics) != {c["capture_id"] for c in contract["captures"]}:
        raise ValueError("Incomplete capture QC")
    method = json.loads((run / "method_identity.json").read_text())
    digest = method.pop("method_sha256")
    if digest_json(method) != digest:
        raise ValueError("Method identity digest mismatch")
    for name, checksum in method["scientific_sources"].items():
        if sha256_file(local_file(run, "source/" + name)) != checksum:
            raise ValueError("Method source mismatch")
    method["method_sha256"] = digest
    if digest != manifest.get("method_sha256") or method["conda_explicit_sha256"] != sha256_file(run / "conda-explicit.txt"):
        raise ValueError("Method identity differs from run/environment controls")
    if method.get("runner_sha256") and method["runner_sha256"] != sha256_file(local_file(run, "source/modal_patient_runner.py")):
        raise ValueError("Method runner identity mismatch")
    if method.get("storage_source_sha256") and method["storage_source_sha256"] != sha256_file(local_file(run, "source/scrna_private.py")):
        raise ValueError("Method storage identity mismatch")
    if contract["evidence_lane"] != manifest["evidence_lane"]:
        raise ValueError("Input/run evidence lane mismatch")
    return contract, method, metrics


def assess_case(run: Path, certificate: Path | None = None, certificate_sha256: str = "",
                review: Path | None = None, audit: Path | None = None) -> dict:
    contract, method, metrics = verify_patient_run(run)
    blockers = []
    method_qualified = False
    if audit is None:
        blockers.append("Independent source-to-checkpoint count audit missing")
    else:
        receipt = json.loads(audit.read_text())
        manifest = json.loads((run / "run_manifest.json").read_text())
        if receipt.get("status") != "counts_integrity_pass" or receipt.get("artifact_index_sha256") != sha256_file(run / "artifact_index.json") or receipt.get("intake_id") != manifest.get("intake_id") or set(receipt.get("captures", {})) != set(metrics) or any(set(values) != COUNT_AUDIT_CHECKS or any(value is not True for value in values.values()) for values in receipt["captures"].values()):
            raise ValueError("Independent source count audit is incomplete/stale or failed")
    if certificate is None:
        blockers.append("No independently reviewed method qualification certificate")
    else:
        if not certificate_sha256 or sha256_file(certificate) != certificate_sha256:
            raise ValueError("Qualification certificate must match an independently approved SHA-256")
        packet = json.loads(certificate.read_text())
        before = len(blockers)
        if packet.get("status") != "reviewed" or not packet.get("reviewer") or packet.get("method_sha256") != method["method_sha256"] or packet.get("claim") != "postcount_qc_and_coarse_marker_hints":
            blockers.append("Qualification is not reviewed/bound to this method and narrow research claim")
        try:
            expires = datetime.fromisoformat(packet["expires_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
                blockers.append("Qualification expired or has no timezone")
        except (KeyError, ValueError):
            blockers.append("Qualification expiration missing/invalid")
        scope = packet.get("scope", {})
        if scope.get("species") != contract["species"] or scope.get("tissue") != contract["tissue"] or scope.get("material") != contract["material"]:
            blockers.append("Patient species/tissue/material outside qualified scope")
        for capture in contract["captures"]:
            if capture["chemistry"] not in scope.get("chemistries", []) or capture["reference"] not in scope.get("references", []) or capture["clinical_subtype"] not in scope.get("clinical_subtypes", []):
                blockers.append("Capture chemistry/reference/subtype outside qualified scope")
            if capture.get("reference_sha256", "unknown") == "unknown" or capture["reference_sha256"] not in scope.get("reference_sha256", []):
                blockers.append("Reference content fingerprint unresolved or outside qualified scope")
        reports = packet.get("reports", {})
        for name in REQUIRED_REPORTS:
            evidence = reports.get(name, {})
            if evidence.get("status") != "validated" or not evidence.get("reviewer") or not evidence.get("source"):
                blockers.append(f"Method evidence missing/unreviewed: {name}")
                continue
            source = local_file(certificate.parent, evidence["path"])
            if sha256_file(source) != evidence.get("sha256"):
                raise ValueError("Qualification evidence checksum mismatch")
        # Independent study/donor evaluation is method evidence; new patient runs need no published truth labels.
        external = reports.get("matched_external_validation", {})
        train, heldout = set(external.get("training_donors", [])), set(external.get("evaluation_donors", []))
        if len(heldout) < 3 or train & heldout or not external.get("evaluation_studies") or set(external.get("training_studies", [])) & set(external.get("evaluation_studies", [])):
            blockers.append("Method external evaluation is absent or overlaps training donors/studies")
        method_qualified = len(blockers) == before
    for capture, value in metrics.items():
        if next(item for item in contract["captures"] if item["capture_id"] == capture).get("count_origin"):
            blockers.append(f"Pipeline-generated upstream cell calling remains unqualified: {capture}")
        required = PATIENT_REQUIRED_GATES | ({"capture_metadata_resolved", "chemistry_metadata_resolved"} if contract["tissue"] == "breast tumor" else set())
        if not required <= set(value.get("gates", {})) or any(flag is not True for flag in value.get("gates", {}).values()):
            blockers.append(f"Patient QC screen needs review: {capture}")
        if value.get("ambient_rna_status") != "estimated_review_required":
            blockers.append(f"Ambient assessment absent/no-call: {capture}")
    if review is None:
        blockers.append("Patient identity, QC losses and annotation uncertainty await human review")
    else:
        packet = json.loads(review.read_text())
        if packet.get("artifact_index_sha256") != sha256_file(run / "artifact_index.json") or packet.get("method_sha256") != method["method_sha256"]:
            raise ValueError("Patient review is stale or bound to another method/run")
        if packet.get("status") != "reviewed" or not packet.get("reviewer") or any(packet.get("checks", {}).get(key) is not True for key in REQUIRED_CASE_REVIEWS):
            blockers.append("Patient review incomplete")
    return {"schema_version": 1, "decision": "reviewed_research" if not blockers else "provisional_hold",
            "method_qualified": method_qualified, "clinical_ready": False, "blockers": blockers,
            "claim": "postcount_qc_and_coarse_marker_hints", "method_sha256": method["method_sha256"],
            "artifact_index_sha256": sha256_file(run / "artifact_index.json"),
            "assessment_policy_sha256": sha256_file(Path(__file__)),
            "qualification_certificate_sha256": certificate_sha256 or None,
            "patient_review_sha256": sha256_file(review) if review else None,
            "source_audit_sha256": sha256_file(audit) if audit else None,
            "reviewer_authentication": "Operator must verify reviewer authority and approved certificate digest outside this tool"}
