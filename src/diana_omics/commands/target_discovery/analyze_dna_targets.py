from __future__ import annotations

from ...paths import path_from_root
from ...target_discovery import (
    CANDIDATE_BOARD_COLUMNS,
    DNA_EVIDENCE_COLUMNS,
    RNA_EVIDENCE_COLUMNS,
    TARGET_DISCOVERY_CANDIDATES,
    TARGET_DISCOVERY_RESULTS,
    build_dna_board,
    read_csv_rows,
    selected_dna_evidence_path,
    selected_rna_evidence_path,
    validate_candidate_board,
    validate_candidate_rows,
)
from ...utils import ensure_dir, iso_now, write_csv, write_json


def main() -> None:
    candidates = read_csv_rows(TARGET_DISCOVERY_CANDIDATES)
    evidence_path = selected_dna_evidence_path()
    evidence_rows = read_csv_rows(evidence_path)
    rna_evidence_path = selected_rna_evidence_path()
    rna_evidence_rows = read_csv_rows(rna_evidence_path)
    errors = validate_candidate_rows(candidates)
    if evidence_rows:
        missing_columns = set(DNA_EVIDENCE_COLUMNS) - set(evidence_rows[0])
        for column in sorted(missing_columns):
            errors.append(f"{evidence_path} is missing required column {column}.")
    if rna_evidence_rows:
        missing_columns = set(RNA_EVIDENCE_COLUMNS) - set(rna_evidence_rows[0])
        for column in sorted(missing_columns):
            errors.append(f"{rna_evidence_path} is missing required column {column}.")
    if errors:
        raise SystemExit("\n".join(errors))

    locus_rows, board_rows = build_dna_board(candidates, evidence_rows, rna_evidence_rows)
    board_errors = validate_candidate_board(board_rows)
    if board_errors:
        raise SystemExit("\n".join(board_errors))

    ensure_dir(path_from_root(TARGET_DISCOVERY_RESULTS))
    write_csv(path_from_root(f"{TARGET_DISCOVERY_RESULTS}/dna_target_locus_summary.csv"), locus_rows)
    write_csv(path_from_root(f"{TARGET_DISCOVERY_RESULTS}/candidate_target_board.csv"), board_rows, CANDIDATE_BOARD_COLUMNS)
    write_json(
        path_from_root(f"{TARGET_DISCOVERY_RESULTS}/dna_target_locus_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "partial_evidence" if evidence_rows else "no_call",
            "candidateManifest": TARGET_DISCOVERY_CANDIDATES,
            "dnaEvidence": evidence_path,
            "rnaEvidence": rna_evidence_path if rna_evidence_rows else "",
            "candidateCount": len(candidates),
            "evidenceRowCount": len(evidence_rows),
            "rnaEvidenceRowCount": len(rna_evidence_rows),
            "blockedCount": sum(1 for row in board_rows if row["overall_status"] == "blocked"),
            "notSupportedCount": sum(1 for row in board_rows if row["overall_status"] == "not_supported"),
            "boundary": "DNA target evidence cannot confirm RNA expression, surface protein abundance, CDK dependency, or drug response.",
        },
    )
    print(f"DNA target board written: {TARGET_DISCOVERY_RESULTS}/candidate_target_board.csv")


if __name__ == "__main__":
    main()
