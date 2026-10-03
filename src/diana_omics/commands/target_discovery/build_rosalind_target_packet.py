from __future__ import annotations

from ...paths import path_from_root
from ...target_discovery import (
    CANDIDATE_BOARD_COLUMNS,
    ROSALIND_TARGET_RESULTS,
    TARGET_DISCOVERY_CANDIDATES,
    TARGET_DISCOVERY_RESULTS,
    build_dna_board,
    markdown_table,
    read_csv_rows,
    selected_dna_evidence_path,
    selected_rna_evidence_path,
    selected_run_id,
    selected_sample_or_cohort,
    source_index,
    validate_candidate_board,
    validate_candidate_rows,
)
from ...utils import ensure_dir, iso_now, write_csv, write_json, write_text


def main() -> None:
    sample = selected_sample_or_cohort()
    run_id = selected_run_id()
    output_root = path_from_root(f"{ROSALIND_TARGET_RESULTS}/{sample}/{run_id}")

    candidates = read_csv_rows(TARGET_DISCOVERY_CANDIDATES)
    errors = validate_candidate_rows(candidates)
    if errors:
        raise SystemExit("\n".join(errors))

    board_path = path_from_root(f"{TARGET_DISCOVERY_RESULTS}/candidate_target_board.csv")
    locus_path = path_from_root(f"{TARGET_DISCOVERY_RESULTS}/dna_target_locus_summary.csv")
    if board_path.exists() and locus_path.exists():
        board_rows = read_csv_rows(f"{TARGET_DISCOVERY_RESULTS}/candidate_target_board.csv")
        locus_rows = read_csv_rows(f"{TARGET_DISCOVERY_RESULTS}/dna_target_locus_summary.csv")
    else:
        locus_rows, board_rows = build_dna_board(
            candidates,
            read_csv_rows(selected_dna_evidence_path()),
            read_csv_rows(selected_rna_evidence_path()),
        )
    board_errors = validate_candidate_board(board_rows)
    if board_errors:
        raise SystemExit("\n".join(board_errors))

    followup_rows = [
        {
            "target_id": row["target_id"],
            "gene_symbol": row["gene_symbol"],
            "recommended_followup": row["recommended_followup"],
            "reason": row["sample_blockers"],
        }
        for row in board_rows
        if row["overall_status"] in {"partial_evidence", "blocked", "no_call"}
    ]
    research_rows = research_context_rows(candidates)
    validation_rows = [
        {
            "status": "passed",
            "candidate_count": len(candidates),
            "board_row_count": len(board_rows),
            "ready_count": sum(1 for row in board_rows if row["overall_status"] == "ready"),
            "partial_evidence_count": sum(1 for row in board_rows if row["overall_status"] == "partial_evidence"),
            "blocked_count": sum(1 for row in board_rows if row["overall_status"] == "blocked"),
            "not_supported_count": sum(1 for row in board_rows if row["overall_status"] == "not_supported"),
            "boundary": "Target packets rank follow-up hypotheses; they do not authorize treatment decisions.",
        }
    ]
    source_rows = source_index(
        [
            TARGET_DISCOVERY_CANDIDATES,
            selected_dna_evidence_path(),
            selected_rna_evidence_path(),
            f"{TARGET_DISCOVERY_RESULTS}/input_validation_summary.json",
            f"{TARGET_DISCOVERY_RESULTS}/dna_target_locus_summary.json",
            f"{TARGET_DISCOVERY_RESULTS}/dna_target_locus_summary.csv",
            f"{TARGET_DISCOVERY_RESULTS}/candidate_target_board.csv",
        ]
    )

    ensure_dir(output_root)
    write_csv(output_root / "sample_validation_summary.csv", validation_rows)
    write_csv(output_root / "dna_target_locus_summary.csv", locus_rows)
    write_csv(output_root / "candidate_target_board.csv", board_rows, CANDIDATE_BOARD_COLUMNS)
    write_csv(output_root / "orthogonal_followup.csv", followup_rows)
    write_json(
        output_root / "research_context_sources.json",
        {
            "generatedAt": iso_now(),
            "status": "no_call",
            "rows": research_rows,
            "boundary": "External research context is recorded after sample evidence and cannot rescue failed or missing sample lanes.",
        },
    )
    write_json(output_root / "input_evidence_index.json", {"generatedAt": iso_now(), "status": "passed", "rows": source_rows})
    write_json(
        output_root / "run_manifest.json",
        {
            "generatedAt": iso_now(),
            "status": "passed",
            "sampleOrCohort": sample,
            "runId": run_id,
            "outputs": [
                "sample_validation_summary.csv",
                "dna_target_locus_summary.csv",
                "candidate_target_board.csv",
                "orthogonal_followup.csv",
                "research_context_sources.json",
                "reviewer_packet.md",
                "next_actions.md",
            ],
            "boundary": "Pan-target Rosalind discovery is research-use follow-up triage.",
        },
    )
    write_text(output_root / "reviewer_packet.md", reviewer_packet(sample, run_id, validation_rows[0], board_rows, research_rows))
    write_text(output_root / "next_actions.md", next_actions(followup_rows))
    print(f"Rosalind target packet written: {output_root}")


def research_context_rows(candidates):
    families = sorted({row["target_family"] for row in candidates})
    return [
        {
            "source_family": "target_identity_pathway",
            "status": "no_call",
            "skills": "UniProt;Ensembl;Reactome;STRING;GO",
            "applies_to": ";".join(families),
            "boundary": "Normalize identity and function after sample evidence exists.",
        },
        {
            "source_family": "expression_normal_tissue",
            "status": "no_call",
            "skills": "Human Protein Atlas;Bgee;GTEx;cellxgene",
            "applies_to": "adc_antigen;bispecific_antigen;immune_context",
            "boundary": "Normal expression cannot prove sample surface abundance.",
        },
        {
            "source_family": "cancer_clinical_context",
            "status": "no_call",
            "skills": "cBioPortal;CIViC;ClinicalTrials.gov;PubMed;PMC",
            "applies_to": ";".join(families),
            "boundary": "Clinical or public tumor evidence cannot override sample no_call gates.",
        },
    ]


def reviewer_packet(
    sample: str,
    run_id: str,
    validation: dict[str, object],
    board_rows: list[dict[str, str]],
    research_rows: list[dict[str, str]],
) -> str:
    columns = ["target_id", "gene_symbol", "target_family", "overall_status", "candidate_class", "sample_blockers"]
    return "\n".join(
        [
            "# Pan-Target Rosalind Discovery Packet",
            "",
            f"Sample or cohort: `{sample}`",
            f"Run ID: `{run_id}`",
            "",
            "## Boundary",
            "",
            "WGS and WES are first-pass support or blocker lanes. RNA expression, cell-surface protein abundance, CDK-pathway dependency, and drug response stay `no_call` until their own evidence lanes pass.",
            "",
            "## Sample Validation",
            "",
            markdown_table([validation], ["status", "candidate_count", "board_row_count", "ready_count", "partial_evidence_count", "blocked_count", "not_supported_count"]),
            "",
            "## Candidate Board",
            "",
            markdown_table(board_rows, columns),
            "",
            "## Research Context Sources",
            "",
            markdown_table(research_rows, ["source_family", "status", "skills", "applies_to", "boundary"]),
        ]
    )


def next_actions(followup_rows: list[dict[str, str]]) -> str:
    lines = ["# Pan-Target Next Actions", ""]
    if not followup_rows:
        lines.append("No blocked follow-up rows were emitted.")
        return "\n".join(lines)
    lines.extend(
        [
            "| target_id | gene_symbol | recommended_followup | reason |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in followup_rows:
        lines.append(
            f"| {row['target_id']} | {row['gene_symbol']} | {row['recommended_followup']} | {row['reason']} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
