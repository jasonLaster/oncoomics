from __future__ import annotations

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json

SMOKE_PAIR_ID = "seqc2_hcc1395_wes_minimal_smoke"
SMOKE_DIR = "data/raw/smoke/seqc2_hcc1395_wes_minimal_smoke"


def nf_core_status(role: str) -> int:
    return 1 if role == "tumor" else 0


def main() -> None:
    ensure_dir(path_from_root("manifests"))
    ensure_dir(path_from_root("results/raw_smoke"))

    panel = parse_csv(read_text(path_from_root("manifests/raw_representative_panel.csv")))
    rows = [
        {
            "pair_id": row["pair_id"],
            "patient": "HCC1395_SEQC2",
            "sample": f"{row['sample_name']}_{row['run']}",
            "role": row["role"],
            "status": nf_core_status(row["role"]),
            "assay": row["assay"],
            "library_strategy": row["library_strategy"],
            "library_layout": row["library_layout"],
            "platform": row["platform"],
            "model": row["model"],
            "run_accession": row["run"],
            "fastq_1": row["fastq_1_url"],
            "fastq_2": row["fastq_2_url"],
            "expected_size_mb": row["size_mb"],
            "source": "ENA direct FASTQ links derived from SEQC2/HCC1395 SRA metadata",
            "caveat": "Remote full-run samplesheet; use smoke samplesheet or downsample before local full WES/WGS.",
        }
        for row in panel
    ]

    smoke_rows = []
    for row in rows:
        if row["pair_id"] != SMOKE_PAIR_ID:
            continue
        smoke_row = dict(row)
        smoke_row.update(
            {
                "fastq_1": f"{SMOKE_DIR}/{row['run_accession']}_R1.fastq",
                "fastq_2": f"{SMOKE_DIR}/{row['run_accession']}_R2.fastq",
                "source": "Local first-read subset streamed from ENA direct FASTQ links",
                "caveat": "Tiny raw-read smoke subset for pairing/QC/plumbing only; not variant-calling depth.",
            }
        )
        smoke_rows.append(smoke_row)

    write_csv(path_from_root("manifests/raw_samplesheet.csv"), rows)
    write_csv(path_from_root("manifests/raw_smoke_samplesheet.csv"), smoke_rows)
    write_json(
        path_from_root("results/raw_smoke/samplesheet_summary.json"),
        {
            "generatedAt": iso_now(),
            "remoteRows": len(rows),
            "smokeRows": len(smoke_rows),
            "smokePairId": SMOKE_PAIR_ID,
            "nfCoreStatusConvention": "status 0 = normal, status 1 = tumor",
            "boundaries": [
                "Remote samplesheet points to full public ENA FASTQ files.",
                "Smoke samplesheet points to local ignored first-read subsets created by diana_omics.commands.run_raw_smoke.",
                "These samplesheets are representative templates for Diana, not Diana data.",
            ],
        },
    )
    print(f"Wrote {len(rows)} raw samplesheet rows and {len(smoke_rows)} smoke rows.")


if __name__ == "__main__":
    main()
