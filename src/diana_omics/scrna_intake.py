"""Local, count-preserving intake for single-capture 10x GEX deliveries.

Intake establishes file custody and compatibility, not biological validity.
Local paths and vendor documents stay in the ignored patient workspace.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

from .scrna_io import safe_id, safe_key, sha256_file

SCHEMA_VERSION = 1
FORMATS = {"10x_h5", "10x_mtx", "fastq"}
CHEMISTRIES = {"3prime_v2", "3prime_v3", "3prime_v3.1", "3prime_v3.1_LT", "3prime_v4", "5prime_v1", "5prime_v2", "5prime_v3", "unknown"}
CONTRACT_FIELDS = {"schema_version", "evidence_lane", "case_id", "species", "tissue", "material", "captures"}
CAPTURE_FIELDS = {"capture_id", "specimen_id", "chemistry", "assay", "reference", "reference_sha256", "format", "expected_cells", "pooled_donors",
                  "clinical_subtype", "treatment_status", "timepoint", "metadata", "files", "count_origin"}
FILE_FIELDS = {"role", "path", "sha256", "size_bytes", "pair_id"}
MATRIX_ROLES = {"filtered_h5", "raw_h5", "filtered_matrix", "filtered_features", "filtered_barcodes", "raw_matrix", "raw_features", "raw_barcodes"}
MAX_FILE_BYTES = 1024**4  # Bound FASTQs; post-count matrices have tighter limits below.


def validate_contract(contract: dict) -> None:
    if set(contract) - CONTRACT_FIELDS or contract.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unknown intake fields or schema; keep identifying metadata in a separate local document")
    if contract.get("evidence_lane") not in {"patient_research", "public_control"}:
        raise ValueError("Explicit patient_research or public_control lane required")
    safe_id(contract["case_id"])
    if contract.get("species") != "Homo sapiens" or contract.get("tissue") not in {"breast tumor", "PBMC"}:
        raise ValueError("Unsupported species/tissue")
    if contract.get("material") not in {"whole_cell", "nuclei", "unknown"}:
        raise ValueError("Unknown material; FFPE/Flex and spatial assays require separate qualification")
    captures = contract.get("captures", [])
    if not 1 <= len(captures) <= 8:
        raise ValueError("Expected one to eight complete captures")
    ids, paths, count_checksums = set(), set(), set()
    for capture in captures:
        if set(capture) - CAPTURE_FIELDS:
            raise ValueError("Unknown capture fields")
        identity = safe_id(capture["capture_id"])
        if identity in ids:
            raise ValueError("Duplicate capture: do not split a technical capture before doublet calling")
        ids.add(identity)
        safe_id(capture["specimen_id"])
        origin = capture.get("count_origin")
        if origin is not None:
            if set(origin) != {"backend", "version", "run_id", "artifact_index_sha256", "count_receipt_sha256", "qualified_for_patient"} or origin["backend"] != "STARsolo" or origin["version"] != "2.7.11b" or origin["qualified_for_patient"] is not False:
                raise ValueError("Pipeline counting origin must retain its unqualified status; no qualification override exists")
            safe_id(origin["run_id"])
            if any(not re.fullmatch(r"[a-f0-9]{64}", origin[field]) for field in ("artifact_index_sha256", "count_receipt_sha256")):
                raise ValueError("Count origin requires content-bound run evidence")
        if capture.get("format") not in FORMATS or capture.get("chemistry") not in CHEMISTRIES:
            raise ValueError("Unsupported format/chemistry")
        if capture.get("assay") not in {"10x_3prime_gex", "10x_5prime_gex", "unknown"}:
            raise ValueError("Only standalone 10x gene-expression captures are supported")
        if type(capture.get("pooled_donors")) is not bool:
            raise ValueError("Declare whether donors were pooled")
        for field in ("clinical_subtype", "treatment_status", "timepoint", "reference"):
            value = capture.get(field)
            if not isinstance(value, str) or not value or len(value) > 160 or any(c in value for c in "\n\r"):
                raise ValueError("Missing or oversized capture metadata")
        if capture.get("reference_sha256") != "unknown" and not re.fullmatch(r"[a-f0-9]{64}", capture.get("reference_sha256", "")):
            raise ValueError("Declare the reference bundle/immutable reference manifest SHA-256, or unknown")
        expected = capture.get("expected_cells")
        if capture["format"] != "fastq" and (type(expected) is not int or not 100 <= expected <= 100000):
            raise ValueError("Matrix deliveries require an independently declared cell count (100..100000)")
        metadata = capture.get("metadata", {})
        if set(metadata) - {"status", "path", "sha256"} or metadata.get("status") not in {"reviewed", "unresolved"}:
            raise ValueError("Declare capture/chemistry metadata review status")
        if metadata["status"] == "reviewed":
            safe_key(metadata["path"])
            if not re.fullmatch(r"[a-f0-9]{64}", metadata.get("sha256", "")):
                raise ValueError("Reviewed vendor metadata requires its source checksum")
        files = capture.get("files", [])
        if not 1 <= len(files) <= 128:
            raise ValueError("Missing files or too many files")
        roles = []
        for item in files:
            if set(item) - FILE_FIELDS:
                raise ValueError("Unknown file fields")
            name = safe_key(item["path"])
            if name in paths:
                raise ValueError("One file cannot belong to multiple captures/roles")
            paths.add(name)
            if not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", "")):
                raise ValueError("Vendor/source SHA-256 required for every file")
            if type(item.get("size_bytes")) is not int or not 0 < item["size_bytes"] <= MAX_FILE_BYTES:
                raise ValueError("Declared file size invalid")
            roles.append(item["role"])
        if capture["format"] == "fastq":
            if set(roles) - {"R1", "R2", "I1", "I2"}:
                raise ValueError("FASTQ roles must be explicit R1/R2/I1/I2")
            pairs = {}
            for item in files:
                pair = safe_id(item["pair_id"])
                if item["role"] in pairs.setdefault(pair, {}):
                    raise ValueError("Duplicate FASTQ pair/read role")
                pairs[pair][item["role"]] = item
            if any(not {"R1", "R2"} <= set(pair) for pair in pairs.values()):
                raise ValueError("Missing R1/R2 mate for a lane/chunk")
        else:
            if len(roles) != len(set(roles)) or set(roles) - MATRIX_ROLES:
                raise ValueError("Invalid or duplicate matrix roles")
            required = {"filtered_h5"} if capture["format"] == "10x_h5" else {"filtered_matrix", "filtered_features", "filtered_barcodes"}
            allowed = required | ({"raw_h5"} if capture["format"] == "10x_h5" else {"raw_matrix", "raw_features", "raw_barcodes"})
            if not required <= set(roles) or set(roles) - allowed:
                raise ValueError("Missing filtered matrix files or mixed matrix formats")
            raw_roles = allowed - required
            if set(roles) & raw_roles and not raw_roles <= set(roles):
                raise ValueError("Incomplete raw droplet matrix")
            count_item = next(item for item in files if item["role"] in {"filtered_h5", "filtered_matrix"})
            if count_item["sha256"] in count_checksums:
                raise ValueError("Same count source reused under multiple capture identities")
            count_checksums.add(count_item["sha256"])


def local_file(root: Path, relative: str) -> Path:
    """Containment includes symlink targets; intake never follows paths outside delivery."""
    path = root / safe_key(relative)
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Missing input or path escapes delivery root")
    return path


def _strings(values):
    return [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in values]


def read_matrix(capture: dict, paths: dict[str, Path], raw: bool = False):
    """Read 10x v3 HDF5 or explicit MEX files sparsely, preserving stable feature IDs."""
    import anndata as ad
    import numpy as np
    import pandas as pd
    from scipy.io import mmread
    from scipy.sparse import csc_matrix, csr_matrix

    prefix = "raw" if raw else "filtered"
    if capture["format"] == "10x_h5":
        import h5py
        with h5py.File(paths[prefix + "_h5"], "r") as handle:
            if "matrix" not in handle:
                raise ValueError("Only modern 10x feature-barcode HDF5 supported")
            group = handle["matrix"]
            shape = tuple(group["shape"][:])
            if len(shape) != 2 or shape[0] > 100000 or shape[1] > 7000000 or group["data"].size > 250000000:
                raise ValueError("Matrix exceeds worker memory envelope")
            matrix = csc_matrix((group["data"][:], group["indices"][:], group["indptr"][:]), shape=shape)
            matrix.check_format(full_check=True)
            matrix = matrix.T.tocsr()
            barcodes = _strings(group["barcodes"][:])
            features = group["features"]
            genes = pd.DataFrame({"gene_ids": _strings(features["id"][:]), "gene_symbols": _strings(features["name"][:]),
                                  "feature_type": _strings(features["feature_type"][:])})
            genomes = _strings(features["genome"][:]) if "genome" in features else []
            if len({g for g in genomes if g}) > 1:
                raise ValueError("Mixed genomes require separate calibration")
    else:
        def read_table(role):
            return pd.read_csv(paths[prefix + "_" + role], sep="\t", header=None, dtype=str, keep_default_na=False)
        features = read_table("features")
        if features.shape[1] != 3:
            raise ValueError("Modern MEX features.tsv must include feature type")
        features.columns = ["gene_ids", "gene_symbols", "feature_type"]
        genes = features
        barcodes = read_table("barcodes")[0].tolist()
        matrix_path = paths[prefix + "_matrix"]
        opener = gzip.open if matrix_path.suffix == ".gz" else open
        with opener(matrix_path, "rb") as handle:
            # Inspect dimensions before the Matrix Market reader allocates sparse storage.
            if not handle.readline().startswith(b"%%MatrixMarket matrix coordinate"):
                raise ValueError("Only sparse coordinate Matrix Market supported")
            dimensions = handle.readline()
            while dimensions.startswith(b"%"):
                dimensions = handle.readline()
            rows, columns, entries = map(int, dimensions.split())
            if rows > 100000 or columns > 7000000 or entries > 250000000:
                raise ValueError("Matrix exceeds worker memory envelope")
        with opener(matrix_path, "rb") as handle:
            matrix = csr_matrix(mmread(handle).T)
    if matrix.shape != (len(barcodes), len(genes)) or not barcodes or not len(genes):
        raise ValueError("Matrix/barcode/feature dimensions disagree")
    if len(set(barcodes)) != len(barcodes) or any(not re.fullmatch(r"[ACGTN]{8,32}-[1-9][0-9]*", b) for b in barcodes):
        raise ValueError("Duplicate or noncanonical 10x barcode; preserve channel suffixes")
    if len({b.rsplit("-", 1)[1] for b in barcodes}) != 1:
        raise ValueError("Multiple GEM groups in one capture: obtain the original per-capture matrices")
    # Inspect all stored entries before sum_duplicates can hide a fractional/negative value.
    if not np.isfinite(matrix.data).all() or (matrix.data < 0).any() or not np.equal(matrix.data, np.round(matrix.data)).all():
        raise ValueError("Expected finite nonnegative integer UMI counts; normalized data are unsupported")
    matrix.sum_duplicates()
    matrix.eliminate_zeros()
    selected = genes.feature_type.eq("Gene Expression").to_numpy()
    genes = genes.loc[selected].copy()
    matrix = matrix[:, selected]
    if not genes.gene_ids.is_unique or genes.gene_ids.eq("").any() or genes.gene_symbols.eq("").any():
        raise ValueError("Duplicate/empty GEX identifiers")
    genes.index = pd.Index(genes.gene_symbols.to_numpy(), name="feature")
    data = ad.AnnData(matrix, obs=pd.DataFrame(index=barcodes), var=genes)
    data.var_names_make_unique()
    if not data.var.gene_symbols.str.startswith("MT-").any():
        raise ValueError("Human mitochondrial symbols absent; resolve the reference/feature mapping")
    if not raw and data.n_obs != capture["expected_cells"]:
        raise ValueError("Declared filtered cell count differs from delivery")
    return data


def align_raw(filtered, raw) -> dict:
    """Require exact raw-to-filtered lineage, allowing explicit feature reordering only."""
    import numpy as np

    if set(filtered.var.gene_ids) != set(raw.var.gene_ids):
        raise ValueError("Raw/filtered gene ID sets differ")
    order = raw.var.gene_ids.reset_index(drop=True).to_numpy()
    positions = {gene: position for position, gene in enumerate(order)}
    gene_order = [positions[gene] for gene in filtered.var.gene_ids]
    if not set(filtered.obs_names) <= set(raw.obs_names):
        raise ValueError("Filtered barcodes are missing from raw matrix")
    subset = raw[filtered.obs_names, gene_order]
    if list(subset.var.gene_symbols) != list(filtered.var.gene_symbols) or (subset.X != filtered.X).nnz:
        raise ValueError("Raw subset differs from filtered counts/symbols; upstream correction or reference mismatch")
    empty_mask = ~raw.obs_names.isin(filtered.obs_names)
    totals = np.asarray(raw.X.sum(axis=1)).ravel()
    # SoupX estimates soup from low-count, non-cell barcodes; merely supplying filtered counts twice cannot pass.
    low = empty_mask & (totals > 0) & (totals < 100)
    if int(low.sum()) < 100:
        raise ValueError("Fewer than 100 non-cell droplets with 1..99 UMIs; ambient assessment is not supported")
    return {"raw_barcodes": raw.n_obs, "filtered_cells": filtered.n_obs, "noncell_barcodes": int(empty_mask.sum()),
            "low_count_noncell_droplets": int(low.sum()), "exact_count_lineage": True,
            "feature_reordered": list(raw.var.gene_ids) != list(filtered.var.gene_ids)}


def inspect_fastq(paths: dict[str, Path], chemistry: str, limit: int | None = 10000) -> dict:
    """Check read IDs/layout on a bounded sample. SHA covers all bytes; this is not full FASTQ validation."""
    from contextlib import ExitStack
    from itertools import repeat

    lengths = {role: set() for role in paths}
    with ExitStack() as stack:
        streams = {role: stack.enter_context(gzip.open(path, "rt") if path.suffix == ".gz" else path.open()) for role, path in paths.items()}  # noqa: SIM115 - ExitStack owns the streams.
        count = 0
        for _ in range(limit) if limit is not None else repeat(None):
            records = {role: [stream.readline().rstrip("\r\n") for _ in range(4)] for role, stream in streams.items()}
            if not any(record[0] for record in records.values()):
                break
            ids = set()
            for role, (header, sequence, plus, quality) in records.items():
                if not header.startswith("@") or not plus.startswith("+") or not sequence or len(sequence) != len(quality):
                    raise ValueError("Malformed FASTQ or sampled mates have different lengths")
                if not re.fullmatch("[ACGTNacgtn]+", sequence) or any(not 33 <= ord(c) <= 126 for c in quality):
                    raise ValueError("Invalid FASTQ sequence/quality")
                ids.add(re.sub(r"/[12]$", "", header.split()[0]))
                lengths[role].add(len(sequence))
            if len(ids) != 1:
                raise ValueError("FASTQ read IDs do not align within a lane/chunk")
            count += 1
    if not count:
        raise ValueError("Empty FASTQ")
    minimum_r1 = 26 if chemistry == "3prime_v2" else 28 if chemistry.startswith("3prime_") else None
    if minimum_r1 and min(lengths["R1"]) < minimum_r1:
        raise ValueError("R1 too short for declared 10x barcode/UMI layout")
    if min(lengths["R2"]) < 25:
        raise ValueError("Transcript read too short")
    return {"sampled_records": count, "read_lengths": {role: sorted(values) for role, values in lengths.items()},
            "validation_scope": "all records, gzip stream and paired identities" if limit is None else "first 10000 records per chunk; full byte SHA verified, full record validation still required"}


def inspect_delivery(contract: dict, root: Path) -> dict:
    validate_contract(contract)
    reports = []
    for capture in contract["captures"]:
        paths = {}
        for item in capture["files"]:
            path = local_file(root, item["path"])
            if path.stat().st_size != item["size_bytes"] or sha256_file(path) != item["sha256"]:
                raise ValueError("Source file size/checksum mismatch")
            paths[item["role"]] = path
        metadata = capture["metadata"]
        if metadata["status"] == "reviewed" and sha256_file(local_file(root, metadata["path"])) != metadata["sha256"]:
            raise ValueError("Vendor metadata checksum mismatch")
        if metadata["status"] == "reviewed":
            packet = json.loads(local_file(root, metadata["path"]).read_text())
            expected = {"capture_id": capture["capture_id"], "specimen_id": capture["specimen_id"],
                        "species": contract["species"], "tissue": contract["tissue"], "material": contract["material"],
                        "assay": capture["assay"], "chemistry": capture["chemistry"], "reference": capture["reference"],
                        "reference_sha256": capture["reference_sha256"], "pooled_donors": capture["pooled_donors"]}
            if any(packet.get(key) != value for key, value in expected.items()) or packet.get("complete_capture") is not True:
                raise ValueError("Reviewed metadata packet disagrees with intake or does not attest to the complete capture")
            if not packet.get("reviewer") or not packet.get("source") or not re.fullmatch(r"[a-f0-9]{64}", packet.get("source_sha256", "")):
                raise ValueError("Reviewed capture metadata requires a reviewer, source and source-document checksum")
        blockers = []
        if contract["material"] != "whole_cell":
            blockers.append("Whole-cell profile cannot be used for nuclei/unknown material")
        identity_unresolved = metadata["status"] != "reviewed" or capture["chemistry"] == "unknown" or capture["reference"] == "unknown"
        # Public controls (never patient data) may be QC'd with unresolved identity so their QC behavior can be
        # studied; the metadata screens then fail visibly and the run can never be admitted.
        if identity_unresolved and contract["evidence_lane"] != "public_control":
            blockers.append("Capture identity, chemistry and reference require reviewed vendor evidence")
        if capture["assay"] == "unknown" or (capture["chemistry"].startswith("3prime") and capture["assay"] != "10x_3prime_gex") or (capture["chemistry"].startswith("5prime") and capture["assay"] != "10x_5prime_gex"):
            blockers.append("Assay and chemistry are unresolved/inconsistent")
        if capture["pooled_donors"]:
            blockers.append("Pooled captures need donor demultiplexing and separate qualification")
        details = {}
        details["capture_identity_status"] = "unresolved_public_control_exploratory" if identity_unresolved else "reviewed"
        details["reference_fingerprint_status"] = "unresolved" if capture["reference_sha256"] == "unknown" else "declared_source_bound"
        if capture["format"] == "fastq":
            pairs = {}
            for item in capture["files"]:
                pairs.setdefault(item["pair_id"], {})[item["role"]] = local_file(root, item["path"])
            details["fastq_samples"] = [inspect_fastq(pair, capture["chemistry"]) for pair in pairs.values()]
            blockers.append("FASTQ count generation needs a qualified counter, pinned reference and full FASTQ validation")
        else:
            filtered = read_matrix(capture, paths)
            details.update({"filtered_cells": filtered.n_obs, "gex_features": filtered.n_vars, "integer_counts": True})
            if any(role.startswith("raw_") for role in paths):
                raw = read_matrix(capture, paths, raw=True)
                details["raw_lineage"] = align_raw(filtered, raw)
            else:
                details["ambient_status"] = "not_assessable_without_raw_droplets"
        reports.append({"capture_id": capture["capture_id"], "details": details, "qc_blockers": blockers})
    return {"schema_version": SCHEMA_VERSION, "case_id": contract["case_id"], "custody_status": "custody_pass",
            "ready_for_postcount_qc": not any(report["qc_blockers"] for report in reports), "captures": reports,
            "clinical_ready": False, "method_qualified": False}
