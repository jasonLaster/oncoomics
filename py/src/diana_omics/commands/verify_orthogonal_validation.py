from __future__ import annotations

import sys
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json

RESULTS_DIR = "results/orthogonal_validation"
EXAMPLES_PATH = "manifests/orthogonal_public_examples.csv"
CANDIDATES_PATH = "manifests/orthogonal_validation_candidates.csv"
DOC_PATH = "docs/orthogonal-validation-samples.md"

REQUIRED_CANDIDATES = {
    "giab_hg008",
    "giab_hg008_rna",
    "colo829",
    "colo829_purity_series",
    "seraseq_ctdna_mrd",
}

REQUIRED_EXAMPLES = {
    "seqc2_hcc1395_full_wes",
    "seqc2_hcc1395_phase3_wgs",
    "giab_hg008_wgs",
    "giab_hg008_rna",
    "colo829_wgs",
    "colo829_purity_series",
    "seraseq_ctdna_mrd",
}


def json_status(relative_path: str) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if not path.exists():
        return {"exists": False, "status": "missing"}
    data = read_json(path)
    if not isinstance(data, dict):
        return {"exists": True, "status": "invalid_json"}
    status = data.get("status", "")
    return {
        "exists": True,
        "status": status,
        "phase3Complete": data.get("phase3Complete", ""),
        "readPairsMode": data.get("readPairsMode", ""),
        "fullSourceFastqs": data.get("fullSourceFastqs", ""),
        "readyForPhase3": data.get("readyForPhase3", ""),
        "readyForPhase4WhenDianaRawArrives": data.get("readyForPhase4WhenDianaRawArrives", ""),
    }


def main() -> None:
    errors: list[str] = []
    warnings: list[str] = []
    ensure_dir(path_from_root(RESULTS_DIR))

    examples = parse_csv(read_text(path_from_root(EXAMPLES_PATH))) if path_from_root(EXAMPLES_PATH).exists() else []
    candidates = parse_csv(read_text(path_from_root(CANDIDATES_PATH))) if path_from_root(CANDIDATES_PATH).exists() else []
    doc_text = read_text(path_from_root(DOC_PATH)) if path_from_root(DOC_PATH).exists() else ""

    if not examples:
        errors.append(f"Missing or empty {EXAMPLES_PATH}.")
    if not candidates:
        errors.append(f"Missing or empty {CANDIDATES_PATH}.")
    if not doc_text:
        errors.append(f"Missing or empty {DOC_PATH}.")

    candidate_ids = {row.get("candidate_id", "") for row in candidates}
    for candidate_id in sorted(REQUIRED_CANDIDATES):
        if candidate_id not in candidate_ids:
            errors.append(f"{CANDIDATES_PATH} is missing candidate {candidate_id}.")

    example_ids = {row.get("example_id", "") for row in examples}
    for example_id in sorted(REQUIRED_EXAMPLES):
        if example_id not in example_ids:
            errors.append(f"{EXAMPLES_PATH} is missing example {example_id}.")

    required_columns = {
        "example_id",
        "priority",
        "status",
        "public_access",
        "modality",
        "source_scope",
        "raw_inputs",
        "truth_or_expected_answer",
        "runnable_command",
        "full_data_command",
        "completion_artifact",
        "pass_gate",
        "documentation",
    }
    actual_columns = set(examples[0].keys()) if examples else set()
    for column in sorted(required_columns - actual_columns):
        errors.append(f"{EXAMPLES_PATH} is missing required column {column}.")

    summary_rows: list[dict[str, Any]] = []
    for row in examples:
        example_id = row.get("example_id", "")
        status = row.get("status", "")
        artifact = row.get("completion_artifact", "")
        documentation = row.get("documentation", "")
        artifact_state = (
            json_status(artifact)
            if artifact.startswith("results/") and not artifact.startswith("planned ")
            else {"exists": False, "status": "planned"}
        )
        documented = bool(documentation and path_from_root(documentation).exists() and example_id.split("_")[0].lower() in doc_text.lower())

        if row.get("public_access") not in {"yes", "request_or_purchase"}:
            errors.append(f"{EXAMPLES_PATH} example {example_id} has invalid public_access {row.get('public_access')!r}.")
        if not row.get("truth_or_expected_answer"):
            errors.append(f"{EXAMPLES_PATH} example {example_id} is missing truth_or_expected_answer.")
        if status == "implemented":
            if not row.get("full_data_command"):
                errors.append(f"Implemented example {example_id} is missing full_data_command.")
            if not artifact_state["exists"]:
                errors.append(f"Implemented example {example_id} is missing completion artifact {artifact}.")
            if artifact_state.get("status") != "passed":
                errors.append(f"Implemented example {example_id} artifact status is {artifact_state.get('status')!r}; expected 'passed'.")
            if example_id == "seqc2_hcc1395_phase3_wgs" and artifact_state.get("phase3Complete") is not True:
                errors.append("Phase 3 SEQC2/HCC1395 public WGS example is not marked phase3Complete.")
            if example_id == "seqc2_hcc1395_phase3_wgs" and artifact_state.get("readPairsMode") != "full":
                errors.append("Phase 3 SEQC2/HCC1395 public WGS example must be a full-source run, not a bounded smoke.")
            if example_id == "seqc2_hcc1395_phase3_wgs" and artifact_state.get("fullSourceFastqs") is not True:
                errors.append("Phase 3 SEQC2/HCC1395 public WGS example must mark fullSourceFastqs=true.")
            if example_id == "seqc2_hcc1395_full_wes" and artifact_state.get("readyForPhase3") is not True:
                errors.append("Full WES SEQC2/HCC1395 example is not marked readyForPhase3.")
        elif status == "planned":
            if not artifact.startswith("planned "):
                warnings.append(f"Planned example {example_id} has a concrete artifact path before implementation: {artifact}.")
        elif status == "blocked_request_or_purchase":
            if row.get("public_access") != "request_or_purchase":
                errors.append(f"Blocked request/purchase example {example_id} must have public_access=request_or_purchase.")
        else:
            errors.append(f"{EXAMPLES_PATH} example {example_id} has invalid status {status!r}.")

        if documentation and not path_from_root(documentation).exists():
            errors.append(f"{EXAMPLES_PATH} example {example_id} references missing documentation {documentation}.")
        if status != "implemented" and not documented and example_id != "seraseq_ctdna_mrd":
            warnings.append(f"Planned example {example_id} should be explicitly described in {DOC_PATH}.")

        summary_rows.append(
            {
                "example_id": example_id,
                "status": status,
                "public_access": row.get("public_access", ""),
                "modality": row.get("modality", ""),
                "source_scope": row.get("source_scope", ""),
                "completion_artifact": artifact,
                "artifact_exists": "yes" if artifact_state["exists"] else "no",
                "artifact_status": artifact_state.get("status", ""),
                "pass_gate": row.get("pass_gate", ""),
                "full_data_command": row.get("full_data_command", ""),
                "documentation": documentation,
            }
        )

    implemented = [row for row in summary_rows if row["status"] == "implemented"]
    if len(implemented) < 2:
        errors.append("Orthogonal validation should include at least the two implemented SEQC2 public examples.")

    write_csv(path_from_root(f"{RESULTS_DIR}/public_examples_summary.csv"), summary_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/public_examples_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "failed" if errors else "passed",
            "implementedExamples": len(implemented),
            "plannedExamples": sum(1 for row in summary_rows if row["status"] == "planned"),
            "blockedExamples": sum(1 for row in summary_rows if row["status"] == "blocked_request_or_purchase"),
            "errors": errors,
            "warnings": warnings,
            "rows": summary_rows,
        },
    )

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Orthogonal validation examples verified: {len(summary_rows)} examples, {len(implemented)} implemented.")


if __name__ == "__main__":
    main()
