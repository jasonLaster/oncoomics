#!/usr/bin/env python3
"""Generate synthetic paired 10x-like reads with an independently specified UMI count answer."""
import gzip
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from diana_omics.scrna_io import sha256_file  # noqa: E402
from diana_omics.scrna_private import digest_json  # noqa: E402


def prepare(root: Path):
    root.mkdir(parents=True, exist_ok=False)
    rng = random.Random(24042)
    def sequence(length):
        return "".join(rng.choice("ACGT") for _ in range(length))
    genome = sequence(80000)
    symbols = ["MT-CO1", "CD3D", "CD3E", "TRAC", "MS4A1", "LYZ", "EPCAM", "KRT8", "KRT18", "KRT19"] + [f"TOY_GENE_{i}" for i in range(70)]
    fasta = root / "genome.fa"
    fasta.write_text(">toy_chr\n" + "\n".join(genome[i:i + 80] for i in range(0, len(genome), 80)) + "\n")
    gtf = root / "genes.gtf"
    gtf.write_text("".join(f'toy_chr\tsynthetic\texon\t{g * 1000 + 1}\t{g * 1000 + 500}\t.\t+\t.\tgene_id "TOY_ID_{g}"; transcript_id "TOY_TX_{g}"; gene_name "{name}";\n' for g, name in enumerate(symbols)))
    barcodes = []
    while len(barcodes) < 228:
        value = sequence(16)
        if all(sum(a != b for a, b in zip(value, known)) >= 3 for known in barcodes):
            barcodes.append(value)
    whitelist = root / "whitelist.txt"
    whitelist.write_text("\n".join(barcodes) + "\n")
    answer, records = [], 0
    with gzip.open(root / "R1.fastq.gz", "wt") as r1, gzip.open(root / "R2.fastq.gz", "wt") as r2:
        for cell, barcode in enumerate(barcodes):
            umis = []
            for gene in range(80 if cell < 100 else 3):
                molecules = 2 if cell < 100 else 1
                answer.append({"barcode": barcode + "-1", "gene_id": f"TOY_ID_{gene}", "umis": molecules})
                for _molecule in range(molecules):
                    while True:
                        umi = sequence(12)
                        if all(sum(a != b for a, b in zip(umi, old)) >= 3 for old in umis):
                            umis.append(umi)
                            break
                    transcript = genome[gene * 1000 + 100:gene * 1000 + 190]
                    for _ in range(2 if cell < 100 else 1):
                        header = f"@synthetic-{records}"
                        r1.write(f"{header} 1:N:0:ACGT\n{barcode}{umi}\n+\n{'I' * 28}\n")
                        r2.write(f"{header} 2:N:0:ACGT\n{transcript}\n+\n{'I' * 90}\n")
                        records += 1
    assets = {role: {"path": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)} for role, path in {"fasta": fasta, "gtf": gtf, "whitelist": whitelist}.items()}
    reference = {"schema_version": 1, "star_version": "2.7.11b", "reference_id": "synthetic-known-UMIs-v1", "reference_class": "synthetic_mechanical",
                 "chemistry": "3prime_v3", "review_status": "reviewed", "reviewer": "synthetic-fixture-operator", "source": "Deterministically generated engineering fixture; no biological or patient validation", "files": assets}
    capture = {"capture_id": "synthetic-count-cap", "specimen_id": "synthetic-count-specimen", "chemistry": "3prime_v3", "assay": "10x_3prime_gex",
               "reference": reference["reference_id"], "reference_sha256": digest_json(reference), "format": "fastq", "expected_cells": 100, "pooled_donors": False,
               "clinical_subtype": "unknown", "treatment_status": "unknown", "timepoint": "synthetic_control", "files": [
                   {"role": role, "path": role + ".fastq.gz", "sha256": sha256_file(root / (role + ".fastq.gz")), "size_bytes": (root / (role + ".fastq.gz")).stat().st_size, "pair_id": "synthetic-lane"} for role in ("R1", "R2")]}
    contract = {"schema_version": 1, "evidence_lane": "public_control", "case_id": "synthetic-count-case", "species": "Homo sapiens", "tissue": "breast tumor", "material": "whole_cell", "captures": [capture]}
    metadata = {key: capture[key] for key in ("capture_id", "specimen_id", "chemistry", "assay", "reference", "reference_sha256", "pooled_donors")}
    metadata.update({key: contract[key] for key in ("species", "tissue", "material")})
    metadata.update(complete_capture=True, reviewer="synthetic-fixture-operator", source="synthetic computational control, not a breast tissue experiment", source_sha256=sha256_file(Path(__file__)))
    packet = root / "metadata.json"
    packet.write_text(json.dumps(metadata, indent=2) + "\n")
    capture["metadata"] = {"status": "reviewed", "path": packet.name, "sha256": sha256_file(packet)}
    for name, value in (("contract.json", contract), ("reference_lock.json", reference), ("expected_counts.json", {"records": records, "filtered_cells": 100, "raw_barcodes": 228, "counts": answer})):
        (root / name).write_text(json.dumps(value, indent=2) + "\n")
    return {"paired_records": records, "expected_raw_UMIs": sum(row["umis"] for row in answer), "filtered_cells": 100, "raw_barcodes": 228, "biological_validation": False}


if __name__ == "__main__":
    print(json.dumps(prepare(Path(sys.argv[1]))))
