"""Multi-class tissue labels, assessable stroma and QC gates for the modular H&E pipeline.

Not clinical sTIL. Pure NumPy so the Modal runner and the local verifier share one
definition. Under the ITWG definition the stromal compartment includes area
occupied by immune cells, so assessable stroma = predicted stroma + predicted
immune infiltrate; tumor nests, fat, necrosis, background and artifact are excluded.
"""

BACKGROUND, TUMOR, STROMA, IMMUNE, FAT, NECROSIS, ARTIFACT = range(7)
LABELS = {BACKGROUND: "background", TUMOR: "tumor", STROMA: "stroma", IMMUNE: "immune_infiltrate",
          FAT: "fat", NECROSIS: "necrosis", ARTIFACT: "artifact"}
ASSESSABLE = (STROMA, IMMUNE)
# Model classes in argmax order; ARTIFACT is never predicted, only imposed from pixels.
MODEL_CLASSES = (BACKGROUND, TUMOR, STROMA, IMMUNE, FAT, NECROSIS)
# VISTA-PATH prompts per class (BCSS-style names, the vocabulary of its BRCA example);
# a class probability is the maximum over its prompts.
DEFAULT_PROMPTS = {
    "background": ["background", "outside_roi"],
    "tumor": ["tumor"],
    "stroma": ["stroma"],
    "immune_infiltrate": ["lymphocytic_infiltrate", "plasma_cells", "other_immune_infiltrate"],
    "fat": ["fat"],
    "necrosis": ["necrosis_or_debris"],
}
IMMUNE_CELLS = ("Lymphocyte", "Plasma_cell")
TUMOR_CELLS = ("tumor",)
GATES = {
    "immune_in_assessable_minimum": 0.85,
    "tumor_fraction_max_abs_difference": 0.15,
    "tumor_fraction_max_ratio": 3.0,
    "tumor_fraction_ratio_floor": 0.05,
}


def _np():
    import numpy as np

    return np


def label_map(probabilities, glass_pixels=None, artifact_pixels=None):
    """Argmax over MODEL_CLASSES with an explicit background class.

    ``probabilities`` maps label names to equally shaped arrays. ``glass_pixels``
    (unstained pixels: glass, fat lumens, tears) are forced to background and
    ``artifact_pixels`` (ink) to ARTIFACT. Ties resolve to the earlier class, so
    background wins an exact tie.
    """
    np = _np()
    stack = np.stack([np.asarray(probabilities[LABELS[c]], np.float32) for c in MODEL_CLASSES])
    if not np.isfinite(stack).all():
        raise ValueError("nonfinite class probabilities")
    labels = np.asarray(MODEL_CLASSES, np.uint8)[stack.argmax(0)]
    if glass_pixels is not None:
        labels[glass_pixels] = BACKGROUND
    if artifact_pixels is not None:
        labels[artifact_pixels] = ARTIFACT
    return labels


def assessable(labels):
    return _np().isin(labels, ASSESSABLE)


def tile_metrics(labels, instances, cells):
    """Pixel and nucleus counts for one core tile.

    A nucleus belongs to a compartment when at least half of its core pixels lie
    in it. Cells with class Unknown stay in nuclear totals but in no class count.
    """
    np = _np()
    if labels.shape != instances.shape:
        raise ValueError("labels and instances must share a grid")
    stroma = assessable(labels)
    tissue = (labels != BACKGROUND) & (labels != ARTIFACT)
    size = int(instances.max()) + 1
    flat = instances.ravel()
    pixels = np.bincount(flat, minlength=size)
    in_stroma = np.bincount(flat, weights=stroma.ravel().astype(np.float64), minlength=size)
    classes = {c["instance_id"]: c["class_name"] for c in cells}
    if set(classes) != set(int(i) for i in np.unique(instances) if i):
        raise ValueError("cell classifications do not match nucleus instances")
    immune = [i for i, name in classes.items() if name in IMMUNE_CELLS]
    tumor = [i for i, name in classes.items() if name in TUMOR_CELLS]
    inside = [i for i in immune if pixels[i] and in_stroma[i] >= .5 * pixels[i]]
    immune_mask = np.isin(instances, immune)
    counts = {LABELS[c]: int((labels == c).sum()) for c in LABELS}
    return {
        "label_pixels": counts,
        "tissue_pixels": int(tissue.sum()),
        "assessable_stroma_pixels": int(stroma.sum()),
        "immune_nuclear_pixels_in_assessable": int((immune_mask & stroma).sum()),
        "immune_nuclei": len(immune),
        "immune_nuclei_in_assessable": len(inside),
        "tumor_nuclei": len(tumor),
        "classified_nuclei": sum(name != "Unknown" for name in classes.values()),
        "nuclei": len(classes),
    }


def aggregate(tiles, pixel_area_um2):
    """Sum physical areas and counts over tiles before dividing."""
    if not tiles:
        raise ValueError("no tiles")
    keys = ("tissue_pixels", "assessable_stroma_pixels", "immune_nuclear_pixels_in_assessable", "immune_nuclei",
            "immune_nuclei_in_assessable", "tumor_nuclei", "classified_nuclei", "nuclei")
    total = {k: sum(t[k] for t in tiles) for k in keys}
    total["label_pixels"] = {name: sum(t["label_pixels"][name] for t in tiles) for name in LABELS.values()}
    stroma_um2 = total["assessable_stroma_pixels"] * pixel_area_um2
    immune_um2 = total["immune_nuclear_pixels_in_assessable"] * pixel_area_um2
    total.update(
        assessable_stroma_um2=stroma_um2,
        immune_nuclear_area_in_assessable_um2=immune_um2,
        assessable_stroma_immune_nuclear_area_percent=100 * immune_um2 / stroma_um2 if stroma_um2 else None,
        immune_in_assessable_fraction=(total["immune_nuclei_in_assessable"] / total["immune_nuclei"]
                                       if total["immune_nuclei"] else None),
        tumor_mask_fraction=total["label_pixels"]["tumor"] / total["tissue_pixels"] if total["tissue_pixels"] else None,
        tumor_nucleus_fraction=total["tumor_nuclei"] / total["classified_nuclei"] if total["classified_nuclei"] else None,
        tiles=len(tiles),
    )
    return total


def tumor_disagreement(mask_fraction, nucleus_fraction, gates=GATES):
    if mask_fraction is None or nucleus_fraction is None:
        return None
    low, high = sorted((mask_fraction, nucleus_fraction))
    return (high - low > gates["tumor_fraction_max_abs_difference"]
            or (high > gates["tumor_fraction_ratio_floor"] and high > gates["tumor_fraction_max_ratio"] * low))


def evaluate_gates(summary, tissue_group, artifact_tiles, gates=GATES):
    """Return per-gate results; ``pass`` is False when any applicable gate flags.

    (a) immune nuclei inside assessable stroma, applied to breast slides only;
    (b) tumor-mask fraction vs CytoFormer tumor-nucleus fraction;
    (c) sampled tiles on ink or off tissue must be zero.
    """
    fraction = summary["immune_in_assessable_fraction"]
    breast = tissue_group.startswith("breast")  # includes the breast_margin block
    a = {"value": fraction, "threshold": gates["immune_in_assessable_minimum"], "applies": breast,
         "flag": bool(breast and (fraction is None or fraction < gates["immune_in_assessable_minimum"]))}
    disagreement = tumor_disagreement(summary["tumor_mask_fraction"], summary["tumor_nucleus_fraction"], gates)
    b = {"tumor_mask_fraction": summary["tumor_mask_fraction"], "tumor_nucleus_fraction": summary["tumor_nucleus_fraction"],
         "max_abs_difference": gates["tumor_fraction_max_abs_difference"], "max_ratio": gates["tumor_fraction_max_ratio"],
         "flag": bool(disagreement) or disagreement is None}
    c = {"artifact_or_off_tissue_tiles": list(artifact_tiles), "flag": bool(artifact_tiles)}
    return {"a_immune_in_assessable_stroma": a, "b_tumor_mask_vs_nuclei": b, "c_ink_and_off_tissue_tiles": c,
            "pass": not (a["flag"] or b["flag"] or c["flag"])}
