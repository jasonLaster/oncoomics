"""Evidence-bound research cohort admission. Completion alone never authorizes use."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .scrna_io import safe_id, safe_key, sha256_file, validate_artifact_index, validate_config, verify_file

SCOPE = "breast_postcount_research_qc"
REQUIRED_EVIDENCE = {"capture_chemistry", "ambient_rna", "annotation", "doublet", "held_out_donors"}
COUNT_AUDIT_CHECKS = {"all_raw_counts_exact", "retained_raw_counts_exact", "doublet_exclusion_exact",
                      "input_barcode_order_exact", "input_gene_order_exact", "retained_barcode_order_exact",
                      "retained_gene_order_exact", "source_sha256_verified", "malignancy_uncalled"}


def config_digest(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def verify_run(root: Path) -> tuple[dict, dict, dict]:
    """Recheck canonical bytes, not the collector's unbound success string."""
    manifest = json.loads((root / "run_manifest.json").read_text())
    safe_id(manifest["run_id"])
    if manifest["status"] != "complete" or manifest["evidence_lane"] != "public_benchmark":
        raise ValueError("A complete public benchmark run is required")
    verify_file(root / "artifact_index.json", manifest["artifact_index_sha256"])
    index = json.loads((root / "artifact_index.json").read_text())
    validate_artifact_index(index)
    paths = set()
    for entry in index:
        name = safe_key(entry["path"])
        if name in paths or name in {"artifact_index.json", "run_manifest.json", "s3_verification.json"}:
            raise ValueError("Duplicate or reserved artifact path")
        paths.add(name)
        target = root / name
        if target.resolve().is_relative_to(root.resolve()) is False or target.is_symlink():
            raise ValueError("Artifact escapes the run directory")
        if target.stat().st_size != entry["size_bytes"]:
            raise ValueError(f"Artifact size mismatch: {name}")
        verify_file(target, entry["sha256"])
    required = {"input_manifest.json", "calibration_summary.json", "source_hashes.json", "python_packages.json", "source/modal_runner.py"}
    if not required.issubset(paths):
        raise ValueError("Run lacks required custody artifacts")
    config = json.loads((root / "input_manifest.json").read_text())
    validate_config(config)
    summaries = json.loads((root / "calibration_summary.json").read_text())
    ids = {d["dataset_id"] for d in config["datasets"]}
    if set(summaries) != ids:
        raise ValueError("Summary must cover every input dataset exactly once")
    return manifest, config, summaries


def assess_release(root: Path, expected_config: dict, audit_path: Path, evidence_path: Path | None = None) -> dict:
    """Assess one immutable run; missing, stale, or failed evidence quarantines it."""
    manifest, config, summaries = verify_run(root)
    blockers = []
    if config != expected_config:
        blockers.append("Run differs from the frozen release inputs, parameters, or acceptance screens")
    audit = json.loads(audit_path.read_text())
    # Audit must be regenerated for this run. Its count comparison is narrower than biology validation.
    if audit.get("run_id") != manifest["run_id"] or audit.get("status") != "pass":
        blockers.append("Independent count audit is absent, failed, or from another run")
    if audit.get("artifact_index_sha256") != manifest["artifact_index_sha256"]:
        blockers.append("Independent count audit is not bound to this artifact index")
    source_hashes = json.loads((root / "source_hashes.json").read_text())
    for name in ("scrna.py", "scrna_io.py", "scrna_qc.py", "scrna_miqc.py"):
        current = Path(__file__).with_name(name)
        if source_hashes.get(name) != sha256_file(current) or sha256_file(root / "source" / name) != sha256_file(current):
            blockers.append(f"Run source differs from the current release: {name}")
    runner = Path(__file__).parents[2] / "scripts/modal/scrna_platform.py"
    if sha256_file(root / "source/modal_runner.py") != sha256_file(runner):
        blockers.append("Run Modal runner differs from the current release")
    ids = {d["dataset_id"] for d in config["datasets"]}
    if set(audit.get("checks", {})) != ids or any(not COUNT_AUDIT_CHECKS.issubset(checks) or any(v is not True for v in checks.values())
                                                 for checks in audit.get("checks", {}).values()):
        blockers.append("Independent count audit does not pass for every dataset")
    for dataset in config["datasets"]:
        name = dataset["dataset_id"]
        if dataset.get("qc_profile") != "human_breast_tumor":
            blockers.append(f"{name}: release scope requires a breast tumor profile")
        if dataset.get("capture_scope") != "verified_single_capture" or not dataset.get("capture_evidence"):
            blockers.append(f"{name}: source-backed technical capture mapping required")
        if dataset.get("chemistry_status") != "verified" or not dataset.get("chemistry_evidence"):
            blockers.append(f"{name}: source-backed chemistry required")
        for field in ("treatment_status", "timepoint"):
            if dataset.get(field) in {None, "", "unknown"}:
                blockers.append(f"{name}: {field} unresolved")
        metrics = summaries[name]
        # Do not trust production_ready or calibration_status flags supplied by a caller.
        gates = metrics.get("gates", {})
        mandatory = {"input_cells_match", "retention", "cluster_count", "finite_embedding", "seed_stability",
                     "raw_counts_preserved", "doublets_called", "compartment_retention",
                     "capture_metadata_resolved", "chemistry_metadata_resolved"}
        for key in sorted(mandatory | set(gates)):
            if gates.get(key) is not True:
                blockers.append(f"{name}: calibration screen failed or missing: {key}")
        if metrics.get("coarse_reference_balanced_accuracy", 0) < 0.8:
            blockers.append(f"{name}: coarse compartment balanced agreement below 0.80")
        if metrics.get("unknown_label_fraction", 1) > 0.1:
            blockers.append(f"{name}: more than 10% unknown coarse labels")
        if metrics.get("ambient_rna_status") not in {"assessed_raw_droplets", "corrected_raw_droplets"}:
            blockers.append(f"{name}: ambient assessment on matching raw droplets required")
    evidence = None
    if evidence_path is None:
        blockers.append("Missing reviewed capture/chemistry, ambient, annotation, doublet, and held-out-donor validation packet")
    else:
        evidence = json.loads(evidence_path.read_text())
        if evidence.get("scope") != SCOPE or evidence.get("config_sha256") != config_digest(config):
            blockers.append("Validation packet scope or frozen recipe does not match this run")
        if evidence.get("artifact_index_sha256") != manifest["artifact_index_sha256"]:
            blockers.append("Validation packet is not bound to this run's artifacts")
        reports = evidence.get("reports", {})
        if set(reports) != REQUIRED_EVIDENCE:
            blockers.append("Validation packet must cover all five required evidence types")
        for kind, report in reports.items():
            if report.get("status") != "validated" or not report.get("reviewer") or not report.get("source"):
                blockers.append(f"{kind}: validation has no successful reviewed source")
            # Referenced reports are required locally and hash-bound in the release certificate.
            if "path" not in report or "sha256" not in report:
                blockers.append(f"{kind}: validation report lacks content custody")
            else:
                path = evidence_path.parent / safe_key(report["path"])
                if not path.resolve().is_relative_to(evidence_path.parent.resolve()):
                    raise ValueError("Validation report escapes packet directory")
                verify_file(path, report["sha256"])
        heldout = reports.get("held_out_donors", {})
        train, test = set(heldout.get("training_donors", [])), set(heldout.get("evaluation_donors", []))
        training_studies, evaluation_studies = set(heldout.get("training_studies", [])), set(heldout.get("evaluation_studies", []))
        if len(test) < 3 or train & test or not {"TNBC", "ER+", "HER2+"}.issubset(heldout.get("subtypes", [])):
            blockers.append("Held-out validation requires disjoint donors and coverage of TNBC, ER+, and HER2+")
        if not training_studies or not evaluation_studies or training_studies & evaluation_studies:
            blockers.append("External validation must use a study separate from method calibration")
    return {"schema_version": 1, "scope": SCOPE, "run_id": manifest["run_id"],
            "decision": "admitted" if not blockers else "quarantined", "production_ready": not blockers,
            "config_sha256": config_digest(config), "artifact_index_sha256": manifest["artifact_index_sha256"],
            "audit_sha256": sha256_file(audit_path), "evidence_sha256": sha256_file(evidence_path) if evidence else None,
            "release_policy_sha256": sha256_file(Path(__file__)),
            "blockers": blockers, "allowed_use": "post-count research QC" if not blockers else "review and calibration only",
            "clinical_use": False, "policy": {"minimum_balanced_agreement": 0.8, "maximum_unknown_fraction": 0.1}}


def run_state(started: dict | None, failed: dict | None, complete: dict | None, now: datetime | None = None) -> dict:
    """Operational status with stale-run detection; no implicit retry or ID overwrite."""
    if failed and complete:
        return {"state": "inconsistent", "action": "Investigate conflicting terminal markers"}
    if complete:
        if complete.get("status") != "complete" or not complete.get("artifact_index_sha256"):
            return {"state": "inconsistent", "action": "Investigate invalid completion marker"}
        return {"state": "complete", "calibration_status": complete.get("calibration_status", "unknown"),
                "action": "Collect, independently audit, then assess release"}
    if failed:
        return {"state": "failed", "action": "Inspect failure; retry with a new run ID after fixing the cause"}
    if not started:
        return {"state": "not_found", "action": "No run has claimed this ID"}
    stamp = datetime.fromisoformat(started["started_at"])
    if stamp.tzinfo is None:
        raise ValueError("Run timestamps must include a timezone")
    age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
    if age < 0:
        return {"state": "inconsistent", "action": "Run start is in the future"}
    timeout = started.get("timeout_seconds", 1800)
    return {"state": "stale" if age > timeout + 300 else "running", "age_seconds": round(age),
            "action": "Inspect Modal logs; do not overwrite this run ID" if age > timeout + 300 else "Await completion"}
