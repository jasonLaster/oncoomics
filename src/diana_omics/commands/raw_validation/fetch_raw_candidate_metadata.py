from __future__ import annotations

from typing import TypedDict

from ...paths import path_from_root
from ...utils import ensure_dir, fetch_text, iso_now, parse_csv, parse_delimited, write_csv, write_json

RUN_INFO_URL = "https://trace.ncbi.nlm.nih.gov/Traces/sra-db-be/runinfo"
ENA_RUN_REPORT_URL = "https://www.ebi.ac.uk/ena/portal/api/filereport"
SEQC2_STUDY = "SRP162370"
TRUTH_SET_ROOT = "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/"


class Candidate(TypedDict):
    pair_id: str
    role: str
    run: str
    assay: str
    phase: str
    priority: int
    use_case: str
    caveat: str


CANDIDATES: list[Candidate] = [
    {
        "pair_id": "seqc2_hcc1395_wes_minimal_smoke",
        "role": "tumor",
        "run": "SRR7890850",
        "assay": "WES",
        "phase": "phase-2a-local-smoke",
        "priority": 1,
        "use_case": "Smallest practical paired-end WES tumor run for FASTQ conversion, sample-sheet wiring, QC, alignment, and somatic-calling plumbing.",
        "caveat": "Still multi-GB; use targeted/downsampled smoke locally before full WES.",
    },
    {
        "pair_id": "seqc2_hcc1395_wes_minimal_smoke",
        "role": "normal",
        "run": "SRR7890851",
        "assay": "WES",
        "phase": "phase-2a-local-smoke",
        "priority": 1,
        "use_case": "Matched normal for the minimal WES tumor smoke run.",
        "caveat": "Still multi-GB; use targeted/downsampled smoke locally before full WES.",
    },
    {
        "pair_id": "seqc2_hcc1395_wes_ffpe_like",
        "role": "tumor",
        "run": "SRR7890945",
        "assay": "WES",
        "phase": "phase-2b-ffpe-stress",
        "priority": 2,
        "use_case": "FFPE/process-stress WES tumor run to exercise artifact/QC handling before Diana FFPE-derived data arrives.",
        "caveat": "FFPE-like benchmark for plumbing and QC; not Diana tissue and not HRD clinical truth.",
    },
    {
        "pair_id": "seqc2_hcc1395_wes_ffpe_like",
        "role": "normal",
        "run": "SRR7890963",
        "assay": "WES",
        "phase": "phase-2b-ffpe-stress",
        "priority": 2,
        "use_case": "Matched normal for FFPE/process-stress WES run.",
        "caveat": "FFPE-like benchmark for plumbing and QC; not Diana tissue and not HRD clinical truth.",
    },
    {
        "pair_id": "seqc2_hcc1395_wgs_hiseqx_full",
        "role": "tumor",
        "run": "SRR7890824",
        "assay": "WGS",
        "phase": "phase-2c-wgs-full",
        "priority": 3,
        "use_case": "HiSeq X Ten WGS tumor benchmark for raw WGS pipeline, SV/signature readiness, and HCC1395 truth-set comparison.",
        "caveat": "About 65 GB SRA input for this run alone; use cloud/HPC or regional/downsampled smoke first.",
    },
    {
        "pair_id": "seqc2_hcc1395_wgs_hiseqx_full",
        "role": "normal",
        "run": "SRR7890827",
        "assay": "WGS",
        "phase": "phase-2c-wgs-full",
        "priority": 3,
        "use_case": "Matched normal for HiSeq X Ten WGS tumor benchmark.",
        "caveat": "About 70 GB SRA input for this run alone; use cloud/HPC or regional/downsampled smoke first.",
    },
    {
        "pair_id": "seqc2_hcc1395_wgs_novaseq_full",
        "role": "tumor",
        "run": "SRR7890905",
        "assay": "WGS",
        "phase": "phase-2c-wgs-full",
        "priority": 4,
        "use_case": "NovaSeq WGS tumor benchmark to test modern platform behavior and cross-platform robustness.",
        "caveat": "Large WGS run; not a local first pass.",
    },
    {
        "pair_id": "seqc2_hcc1395_wgs_novaseq_full",
        "role": "normal",
        "run": "SRR7890943",
        "assay": "WGS",
        "phase": "phase-2c-wgs-full",
        "priority": 4,
        "use_case": "Matched normal for NovaSeq WGS tumor benchmark.",
        "caveat": "Large WGS run; not a local first pass.",
    },
]


def main() -> None:
    ensure_dir(path_from_root("data/processed/catalog"))
    ensure_dir(path_from_root("manifests"))
    runs = [candidate["run"] for candidate in CANDIDATES]
    run_info = parse_csv(fetch_text(f"{RUN_INFO_URL}?acc={','.join(runs)}"))
    by_run = {row["Run"]: row for row in run_info}
    ena_rows = []
    for run in runs:
        ena_text = fetch_text(
            f"{ENA_RUN_REPORT_URL}?accession={run}&result=read_run&fields=run_accession,fastq_ftp,fastq_md5,fastq_bytes,library_layout,library_strategy,instrument_platform,instrument_model,sample_alias&format=tsv"
        )
        ena_rows.extend(parse_delimited(ena_text, "\t"))
    ena_by_run = {row["run_accession"]: row for row in ena_rows}
    selected_run_info = []
    selected_ena_rows = []
    manifest_rows = []
    for candidate in CANDIDATES:
        run = candidate["run"]
        row = by_run.get(run)
        ena = ena_by_run.get(run)
        if not row:
            raise RuntimeError(f"Missing SRA runinfo row for {run}")
        if not ena:
            raise RuntimeError(f"Missing ENA FASTQ row for {run}")
        selected_run_info.append(row)
        selected_ena_rows.append(ena)
        fastq_urls = [f"https://{url}" for url in (ena.get("fastq_ftp") or "").split(";") if url]
        fastq_md5s = [value for value in (ena.get("fastq_md5") or "").split(";") if value]
        fastq_bytes = [value for value in (ena.get("fastq_bytes") or "").split(";") if value]
        if len(fastq_urls) != 2:
            raise RuntimeError(f"Expected paired FASTQ URLs for {run}, got {len(fastq_urls)}")
        manifest_rows.append(
            {
                "pair_id": candidate["pair_id"],
                "role": candidate["role"],
                "run": run,
                "assay": candidate["assay"],
                "phase": candidate["phase"],
                "priority": candidate["priority"],
                "sra_study": row.get("SRAStudy", ""),
                "bioproject": row.get("BioProject", ""),
                "experiment": row.get("Experiment", ""),
                "library_name": row.get("LibraryName", ""),
                "library_strategy": row.get("LibraryStrategy", ""),
                "library_layout": row.get("LibraryLayout", ""),
                "sample_name": row.get("SampleName", ""),
                "biosample": row.get("BioSample", ""),
                "platform": row.get("Platform", ""),
                "model": row.get("Model", ""),
                "spots": row.get("spots", ""),
                "bases": row.get("bases", ""),
                "avg_length": row.get("avgLength", ""),
                "size_mb": row.get("size_MB", ""),
                "consent": row.get("Consent", ""),
                "download_path": row.get("download_path", ""),
                "fastq_1_url": fastq_urls[0],
                "fastq_2_url": fastq_urls[1],
                "fastq_1_md5": fastq_md5s[0] if len(fastq_md5s) > 0 else "",
                "fastq_2_md5": fastq_md5s[1] if len(fastq_md5s) > 1 else "",
                "fastq_1_bytes": fastq_bytes[0] if len(fastq_bytes) > 0 else "",
                "fastq_2_bytes": fastq_bytes[1] if len(fastq_bytes) > 1 else "",
                "use_case": candidate["use_case"],
                "caveat": candidate["caveat"],
            }
        )
    write_csv(path_from_root("data/processed/catalog/seqc2_sra_runinfo_selected.csv"), selected_run_info)
    write_csv(path_from_root("data/processed/catalog/seqc2_ena_fastq_selected.csv"), selected_ena_rows)
    write_csv(path_from_root("manifests/raw_representative_panel.csv"), manifest_rows)
    write_json(
        path_from_root("manifests/raw_representative_panel_summary.json"),
        {
            "generatedAt": iso_now(),
            "source": f"{RUN_INFO_URL}?acc={','.join(runs)}",
            "study": SEQC2_STUDY,
            "truthSetRoot": TRUTH_SET_ROOT,
            "pairCount": len(set(candidate["pair_id"] for candidate in CANDIDATES)),
            "runCount": len(manifest_rows),
            "allPublic": all(row["consent"] == "public" for row in manifest_rows),
            "phases": sorted(set(candidate["phase"] for candidate in CANDIDATES)),
            "boundaries": [
                "These are representative raw-data candidates, not Diana data.",
                "SRA paths may point to SRA Lite objects; verify quality handling before sensitivity benchmarking.",
                "Use small regional/downsampled smoke runs locally before full WGS.",
                "Use SEQC2 truth-set FTP outputs for caller comparison when full raw calling is attempted.",
            ],
        },
    )
    print(f"Wrote {len(manifest_rows)} representative raw-data run candidates from {SEQC2_STUDY}.")


if __name__ == "__main__":
    main()
