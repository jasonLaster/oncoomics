#!/usr/bin/env python3
"""Prepare the hash-locked PUBLIC GSE161529 TNBC captures for the exploratory public_control lane.

Never accepts patient inputs. Chemistry, reference and capture metadata are unresolved in the source, so these
runs stay on the metadata screens' failure path and can never be admitted.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from diana_omics.scrna_intake import validate_contract  # noqa: E402
from diana_omics.scrna_io import sha256_file  # noqa: E402

SOURCE_DIR = ROOT / "data/raw/scrna/GSE161529"
LOCK = ROOT / "manifests/scrna/controls/gse161529-tnbc.sources.lock.json"
FEATURES = "GSE161529_features.tsv.gz"
CAPTURES = {  # GEO accession -> (label, case, subtype, file stem)
    "GSM4909281": ("tn-mh0126", "tnbc", "TNBC", "TN-MH0126"), "GSM4909282": ("tn-mh0135", "tnbc", "TNBC", "TN-MH0135"),
    "GSM4909283": ("tn-sh0106", "tnbc", "TNBC", "TN-SH0106"), "GSM4909284": ("tn-mh0114", "tnbc", "TNBC", "TN-MH0114-T2"),
    "GSM4909285": ("tn-b1-mh4031", "brca1", "TNBC-BRCA1", "TN-B1-MH4031"), "GSM4909286": ("tn-b1-mh0131", "brca1", "TNBC-BRCA1", "TN-B1-MH0131"),
    "GSM4909287": ("tn-b1-tum0554", "brca1", "TNBC-BRCA1", "TN-B1-Tum0554"), "GSM4909288": ("tn-b1-mh0177", "brca1", "TNBC-BRCA1", "TN-B1-MH0177"),
}
LIMITATIONS = ["Public series GSE161529 (Pal et al. 2021, EMBO J); no Diana data",
               "Filtered matrices only: no raw droplet matrix, so ambient RNA is not assessable",
               "Chemistry (3' v2 vs v3) and reference are not stated per sample by the source; Cell Ranger 3.0.2 per the paper",
               "Capture identity is unreviewed; each GEO sample is treated as one complete capture",
               "Treatment-naive per the publication summary; tissue dissociation and viability handling differ from clinical specimens",
               "Post-count QC only; no independent cell-type, doublet or malignancy truth"]


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def build_lock() -> dict:
    files = {}
    for gsm, (_, _, _, stem) in CAPTURES.items():
        for kind in ("barcodes.tsv.gz", "matrix.mtx.gz"):
            path = SOURCE_DIR / f"{gsm}_{stem}-{kind}"
            files[path.name] = {"role": kind.split(".")[0], "gsm": gsm, "size_bytes": path.stat().st_size, "sha256": sha256_file(path),
                                "url": f"https://ftp.ncbi.nlm.nih.gov/geo/samples/{gsm[:-3]}nnn/{gsm}/suppl/{path.name}"}
    path = SOURCE_DIR / FEATURES
    files[FEATURES] = {"role": "features", "size_bytes": path.stat().st_size, "sha256": sha256_file(path),
                       "url": f"https://ftp.ncbi.nlm.nih.gov/geo/series/GSE161nnn/GSE161529/suppl/{FEATURES}"}
    return {"schema_version": 1, "evidence_lane": "public_control", "series": "GSE161529",
            "source_page": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE161529",
            "publication": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8167363", "files": files, "limitations": LIMITATIONS}


def verify_lock() -> dict:
    if not LOCK.exists():
        write_json(LOCK, build_lock())
    lock = json.loads(LOCK.read_text())
    for name, entry in lock["files"].items():
        path = SOURCE_DIR / name
        if path.is_symlink() or path.stat().st_size != entry["size_bytes"] or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Public source checksum/size mismatch: {name}")
    return lock


def prepare(destination: Path) -> dict:
    destination = destination.resolve()
    if not destination.is_relative_to((ROOT / "private").resolve()) or destination.exists():
        raise ValueError("Choose a new directory under private/; existing deliveries are never replaced")
    lock = verify_lock()
    destination.mkdir(parents=True, mode=0o700)
    prepared = {"schema_version": 1, "source_classification": "public_control", "execution_lane": "public_control",
                "purpose": "Exploratory post-count QC of real public TNBC captures with unresolved chemistry",
                "source_lock_sha256": sha256_file(LOCK), "cases": {}, "limitations": lock["limitations"]}
    for case in ("tnbc", "brca1"):
        delivery = destination / case / "delivery"
        delivery.mkdir(parents=True, mode=0o700)
        contract = {"schema_version": 1, "evidence_lane": "public_control", "case_id": f"public-gse161529-{case}-001",
                    "species": "Homo sapiens", "tissue": "breast tumor", "material": "whole_cell", "captures": []}
        mappings = []
        for gsm, (label, which, subtype, stem) in CAPTURES.items():
            if which != case:
                continue
            directory = delivery / label
            directory.mkdir(mode=0o700)
            roles = {"filtered_barcodes": f"{gsm}_{stem}-barcodes.tsv.gz", "filtered_matrix": f"{gsm}_{stem}-matrix.mtx.gz", "filtered_features": FEATURES}
            files = []
            for role, name in roles.items():
                target = directory / name
                shutil.copyfile(SOURCE_DIR / name, target)
                target.chmod(0o600)
                files.append({"role": role, "path": target.relative_to(delivery).as_posix(), "size_bytes": target.stat().st_size, "sha256": sha256_file(target)})
                if lock["files"][name]["sha256"] != files[-1]["sha256"]:
                    raise ValueError("Copied source differs from the lock")
            with gzip.open(directory / roles["filtered_barcodes"], "rt") as handle:
                cells = sum(1 for _ in handle)
            contract["captures"].append({
                "capture_id": f"public-{label}-001", "specimen_id": f"public-{label}-specimen", "chemistry": "unknown",
                "assay": "10x_3prime_gex", "reference": "unknown", "reference_sha256": "unknown", "pooled_donors": False,
                "format": "10x_mtx", "expected_cells": cells, "clinical_subtype": subtype,
                "treatment_status": "treatment_naive_per_publication", "timepoint": "pre_treatment_per_publication",
                "metadata": {"status": "unresolved"}, "files": files})
            mappings.append({"capture_id": f"public-{label}-001", "geo_sample": gsm, "clinical_subtype": subtype})
        validate_contract(copy.deepcopy(contract))
        write_json(destination / case / "contract.json", contract)
        prepared["cases"][case] = {"case_id": contract["case_id"], "captures": mappings}
    write_json(destination / "public_rehearsal.json", prepared)
    return prepared


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    result = prepare(parser.parse_args().destination)
    print(json.dumps({"source_classification": result["source_classification"], "cases": {k: len(v["captures"]) for k, v in result["cases"].items()}}))
