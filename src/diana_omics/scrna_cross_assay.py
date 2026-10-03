"""Descriptive RNA summaries for cross-assay review; no activity or dependency inference."""

from __future__ import annotations


def stable_gene_id(value: str) -> str:
    """Only Ensembl version suffixes are removed; symbols are not identity keys."""
    import re

    if not re.fullmatch(r"ENSG[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("Expected a stable human Ensembl gene identifier")
    return value.split(".")[0]


def summarize_targets(library_id: str, targets, totals, groupings: dict, layer: str, minimum_group_size: int = 100) -> list[dict]:
    """All input barcodes remain present; selected groups are diagnostic sensitivity views.

    Caller must use totals from the same matrix layer as target UMIs. Vendor labels
    and doublet classes are unqualified group labels, not biological ground truth.
    Every Series must match the target barcode index in order. Libraries must be
    summarized separately even when their barcode strings happen to overlap.
    """
    import numpy as np

    from .scrna_io import safe_id

    safe_id(library_id)
    if minimum_group_size < 1 or layer not in {"original_counts", "soupx_candidate"}:
        raise ValueError("Explicit matrix layer and positive group-size threshold required")
    if not targets.index.is_unique or not targets.columns.is_unique or not targets.index.equals(totals.index):
        raise ValueError("Targets and same-layer totals require unique, ordered barcode correspondence")
    values = targets.to_numpy()
    total = totals.to_numpy()
    if not np.isfinite(values).all() or (values < 0).any() or not np.equal(values, np.round(values)).all():
        raise ValueError("Target UMIs must be finite nonnegative integer counts")
    if not np.isfinite(total).all() or (total < 0).any() or not np.equal(total, np.round(total)).all() or (values > total[:, None]).any():
        raise ValueError("Same-layer totals are incompatible with target counts")
    rows = []
    for grouping, labels in groupings.items():
        if not labels.index.equals(targets.index) or labels.isna().any():
            raise ValueError("Group labels require complete ordered barcode correspondence")
        labels = labels.astype(str).to_numpy()
        for label in sorted(set(labels)):
            mask = labels == label
            size = int(mask.sum())
            denominator = int(total[mask].sum())
            for j, gene in enumerate(targets.columns):
                v = values[mask, j]
                usable = size >= minimum_group_size and denominator > 0
                logs = np.log1p(np.divide(v * 10000, total[mask], out=np.zeros(size, dtype=float), where=total[mask] > 0))
                rows.append(
                    {
                        "library_id": library_id,
                        "layer": layer,
                        "grouping": grouping,
                        "group": label,
                        "gene": gene,
                        "barcodes": size,
                        "zero_total_barcodes": int((total[mask] == 0).sum()),
                        "minimum_group_size": minimum_group_size,
                        "status": "descriptive" if usable else "insufficient_group",
                        "detected_barcodes": int((v > 0).sum()),
                        "target_umi_sum": int(v.sum()),
                        "total_umi_sum": denominator,
                        "detected_fraction": float((v > 0).mean()) if usable else None,
                        "pseudobulk_umi_cpm": float(v.sum() / denominator * 1e6) if usable else None,
                        "mean_log1p_cp10k": float(logs.mean()) if usable else None,
                        "clinical_ready": False,
                        "interpretation": "Gene abundance only; no malignant-cell, variant-carrier, pathway-flux or drug-response call.",
                    }
                )
    return rows
