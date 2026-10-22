"""Held-out TIGER benchmark arithmetic for breast H&E stromal TIL research pipelines.

This module freezes the slide split and computes the prespecified agreement and
component metrics. It performs no inference, downloads or calibration. Reference
scores are pathologist visual sTIL estimates; model outputs keep their own
endpoint names and are compared on the same 0-100 scale without transformation.
"""

import math
import random
import re

SCORE_BANDS = (("0-4", 0, 4), ("5-9", 5, 9), ("10-29", 10, 29), ("30-59", 30, 59), ("60+", 60, 100))
CUTOFFS = (10, 30)
# TIGER tissue-cells mask labels (0 is unannotated and excluded from every metric).
TIGER_TISSUE_LABELS = {1: "invasive_tumor", 2: "tumor_associated_stroma", 3: "in_situ_tumor", 4: "healthy_glands",
                       5: "necrosis_not_in_situ", 6: "inflamed_stroma", 7: "rest"}
TIGER_STROMA_LABELS = (2, 6)
TIGER_TUMOR_LABELS = (1,)
PITFALL_PATTERNS = {
    "dcis": r"\bdcis\b",
    "normal_structures": r"normal (structures|lobules)",
    "lymph_node": r"lymph node",
    "necrosis": r"necrosis",
    "neutrophils": r"neutrophil",
    "granulation_tissue": r"granulation",
    "lymphoid_aggregates": r"lymphoid aggregate",
    "stated_pitfall": r"pitfall",
}
SPLIT_SCHEMA = "diana-stil-tiger-split/v1"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def score_band(score):
    _require(isinstance(score, (int, float)) and math.isfinite(score) and 0 <= score <= 100, "score must be in [0, 100]")
    for name, low, high in SCORE_BANDS:
        if low <= score <= high or (name == "60+" and score >= low):
            return name
    # Non-integer scores between band edges (e.g. 4.5) belong to the lower band.
    for name, low, _ in reversed(SCORE_BANDS):
        if score >= low:
            return name
    raise ValueError("unbanded score")


def slide_source(image_id):
    """TIGER wsitils IDs are either numeric with an S/B suffix or TC_* identifiers."""
    if re.fullmatch(r"\d+[SB]", image_id):
        return "numeric_SB"
    if re.fullmatch(r"TC_S\d+_P\d+_C\d+_B\d+", image_id):
        return "TC"
    raise ValueError("unrecognized TIGER wsitils image-id: " + image_id)


def pitfall_flags(comment):
    text = (comment or "").lower()
    flags = sorted(name for name, pattern in PITFALL_PATTERNS.items() if re.search(pattern, text))
    return flags


def make_split(rows, seed, n_dev=40, n_folds=5):
    """Stratified development/locked-test split plus development folds.

    `rows` are dicts with `image-id` and `tils-score`. Allocation per
    (source, band) stratum uses largest remainders so the development total is
    exact; ties and within-stratum selection use a seeded RNG over sorted IDs, so
    the output depends only on the IDs, scores and seed.
    """
    ids = [r["image-id"] for r in rows]
    _require(len(ids) == len(set(ids)), "duplicate image IDs")
    _require(0 < n_dev < len(rows), "development size must leave a test set")
    rng = random.Random(seed)
    strata = {}
    for r in sorted(rows, key=lambda r: r["image-id"]):
        key = (slide_source(r["image-id"]), score_band(float(r["tils-score"])))
        strata.setdefault(key, []).append(r["image-id"])
    keys = sorted(strata, key=lambda k: (k[0], [b[0] for b in SCORE_BANDS].index(k[1])))
    total = len(rows)
    quota = {k: len(strata[k]) * n_dev / total for k in keys}
    alloc = {k: int(math.floor(quota[k])) for k in keys}
    tiebreak = {k: rng.random() for k in keys}
    for k in sorted(keys, key=lambda k: (-(quota[k] - alloc[k]), tiebreak[k]))[: n_dev - sum(alloc.values())]:
        alloc[k] += 1
    assignment = {}
    for k in keys:
        members = list(strata[k])
        rng.shuffle(members)
        for i, image_id in enumerate(members):
            assignment[image_id] = "development" if i < alloc[k] else "locked_test"
    # Folds: walk development strata in band order and deal slides round-robin.
    folds, position = {}, 0
    for k in sorted(keys, key=lambda k: ([b[0] for b in SCORE_BANDS].index(k[1]), k[0])):
        members = sorted(i for i in strata[k] if assignment[i] == "development")
        rng.shuffle(members)
        for image_id in members:
            folds[image_id] = position % n_folds
            position += 1
    slides = []
    for r in sorted(rows, key=lambda r: r["image-id"]):
        image_id = r["image-id"]
        slides.append({"image_id": image_id, "source": slide_source(image_id), "band": score_band(float(r["tils-score"])),
                       "pitfall_flags": pitfall_flags(r.get("comment", "")), "split": assignment[image_id],
                       "dev_fold": folds.get(image_id)})
    return {"schema": SPLIT_SCHEMA, "seed": seed, "n_dev": n_dev, "n_folds": n_folds,
            "strata": [{"source": k[0], "band": k[1], "n": len(strata[k]), "development": alloc[k]} for k in keys],
            "slides": slides}


def _arrays(reference, prediction):
    _require(len(reference) == len(prediction) and len(reference) >= 2, "need at least two paired scores")
    x = [float(v) for v in reference]
    y = [float(v) for v in prediction]
    _require(all(math.isfinite(v) for v in x + y), "scores must be finite")
    return x, y


def _mean(v):
    return sum(v) / len(v)


def _var(v, ddof=0):
    m = _mean(v)
    return sum((a - m) ** 2 for a in v) / (len(v) - ddof)


def _ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    ranks = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def pearson(x, y):
    mx, my = _mean(x), _mean(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else None


def spearman(x, y):
    return pearson(_ranks(x), _ranks(y))


def lins_ccc(x, y):
    """Lin's concordance correlation coefficient with population moments."""
    mx, my = _mean(x), _mean(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y)) / len(x)
    denom = _var(x) + _var(y) + (mx - my) ** 2
    return 2 * sxy / denom if denom > 0 else None


def icc_absolute_single(x, y):
    """ICC(A,1): two-way, absolute agreement, single measurement (McGraw & Wong)."""
    n, k = len(x), 2
    data = list(zip(x, y))
    grand = _mean(x + y)
    row_means = [_mean(r) for r in data]
    col_means = [_mean(x), _mean(y)]
    ssr = k * sum((m - grand) ** 2 for m in row_means)
    ssc = n * sum((m - grand) ** 2 for m in col_means)
    sst = sum((v - grand) ** 2 for r in data for v in r)
    sse = sst - ssr - ssc
    msr, msc, mse = ssr / (n - 1), ssc / (k - 1), sse / ((n - 1) * (k - 1))
    denom = msr + (k - 1) * mse + k * (msc - mse) / n
    return (msr - mse) / denom if denom > 0 else None


def bland_altman(x, y):
    """Bias and 95% limits of agreement for prediction minus reference."""
    d = [b - a for a, b in zip(x, y)]
    bias = _mean(d)
    sd = math.sqrt(_var(d, ddof=1))
    return {"bias": bias, "sd_diff": sd, "loa_low": bias - 1.96 * sd, "loa_high": bias + 1.96 * sd}


def categorical(x, y, cutoff):
    """Agreement for score >= cutoff (high) versus below."""
    rx = [a >= cutoff for a in x]
    ry = [b >= cutoff for b in y]
    n = len(rx)
    tp = sum(a and b for a, b in zip(rx, ry))
    tn = sum((not a) and (not b) for a, b in zip(rx, ry))
    fp = sum((not a) and b for a, b in zip(rx, ry))
    fn = sum(a and (not b) for a, b in zip(rx, ry))
    po = (tp + tn) / n
    pe = ((tp + fn) * (tp + fp) + (tn + fp) * (tn + fn)) / (n * n)
    kappa = (po - pe) / (1 - pe) if pe < 1 else None
    return {"cutoff": cutoff, "n": n, "accuracy": po, "cohen_kappa": kappa,
            "sensitivity": tp / (tp + fn) if tp + fn else None, "specificity": tn / (tn + fp) if tn + fp else None,
            "tp": tp, "tn": tn, "fp": fp, "fn": fn}


def agreement(reference, prediction):
    x, y = _arrays(reference, prediction)
    out = {"n": len(x), "mae_pp": _mean([abs(b - a) for a, b in zip(x, y)]),
           "lins_ccc": lins_ccc(x, y), "icc_a1": icc_absolute_single(x, y),
           "spearman": spearman(x, y), "pearson": pearson(x, y)}
    out.update(bland_altman(x, y))
    out["categorical"] = [categorical(x, y, c) for c in CUTOFFS]
    return out


def bootstrap_ci(reference, prediction, statistic, reps=2000, seed=0, alpha=.05):
    """Percentile bootstrap over slides for a scalar statistic of (x, y)."""
    x, y = _arrays(reference, prediction)
    rng = random.Random(seed)
    values = []
    for _ in range(reps):
        idx = [rng.randrange(len(x)) for _ in x]
        v = statistic([x[i] for i in idx], [y[i] for i in idx])
        if v is not None:
            values.append(v)
    _require(values, "bootstrap produced no finite values")
    values.sort()
    lo = values[int(math.floor(alpha / 2 * (len(values) - 1)))]
    hi = values[int(math.ceil((1 - alpha / 2) * (len(values) - 1)))]
    return lo, hi


def per_band(records):
    """records: dicts with `reference` and `prediction`. Bands use the reference score."""
    out = []
    for name, _, _ in SCORE_BANDS:
        rows = [r for r in records if score_band(r["reference"]) == name]
        if not rows:
            out.append({"band": name, "n": 0})
            continue
        d = [r["prediction"] - r["reference"] for r in rows]
        out.append({"band": name, "n": len(rows), "mae_pp": _mean([abs(v) for v in d]), "bias": _mean(d)})
    return out


# ---------------------------------------------------------------- components


def dice(pred, ref, valid=None):
    """Dice of two boolean arrays inside `valid`; None when both are empty."""
    import numpy as np

    pred = np.asarray(pred, dtype=bool)
    ref = np.asarray(ref, dtype=bool)
    _require(pred.shape == ref.shape, "mask shape mismatch")
    if valid is not None:
        valid = np.asarray(valid, dtype=bool)
        _require(valid.shape == ref.shape, "valid-mask shape mismatch")
        pred, ref = pred & valid, ref & valid
    inter = int((pred & ref).sum())
    total = int(pred.sum() + ref.sum())
    return {"dice": 2 * inter / total if total else None, "intersection": inter,
            "pred_pixels": int(pred.sum()), "ref_pixels": int(ref.sum())}


def tissue_component_dice(pred_labels, ref_labels, pred_stroma=(2,), pred_tumor=(1,)):
    """Stroma and tumor Dice against a TIGER mask over annotated (nonzero) pixels."""
    import numpy as np

    ref_labels = np.asarray(ref_labels)
    pred_labels = np.asarray(pred_labels)
    valid = ref_labels > 0
    return {"stroma": dice(np.isin(pred_labels, pred_stroma), np.isin(ref_labels, TIGER_STROMA_LABELS), valid),
            "tumor": dice(np.isin(pred_labels, pred_tumor), np.isin(ref_labels, TIGER_TUMOR_LABELS), valid),
            "annotated_pixels": int(valid.sum())}


def match_points(pred_xy, ref_xy, max_distance):
    """Greedy one-to-one matching by ascending distance within `max_distance`.

    Returns TP/FP/FN and precision, recall, F1. Greedy nearest-pair matching is
    deterministic and equals optimal matching whenever candidate pairs do not
    compete; it is the prespecified rule for this benchmark.
    """
    _require(max_distance > 0, "distance must be positive")
    pairs = []
    r2 = max_distance * max_distance
    for i, (px, py) in enumerate(pred_xy):
        for j, (rx, ry) in enumerate(ref_xy):
            d2 = (px - rx) ** 2 + (py - ry) ** 2
            if d2 <= r2:
                pairs.append((d2, i, j))
    pairs.sort()
    used_p, used_r = set(), set()
    for _, i, j in pairs:
        if i not in used_p and j not in used_r:
            used_p.add(i)
            used_r.add(j)
    tp = len(used_p)
    fp = len(pred_xy) - tp
    fn = len(ref_xy) - tp
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def pooled_detection(results):
    tp = sum(r["tp"] for r in results)
    fp = sum(r["fp"] for r in results)
    fn = sum(r["fn"] for r in results)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None, "f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None}


def coco_box_centers(coco, image_id):
    """Centers of COCO [x, y, w, h] boxes for one image."""
    return [(a["bbox"][0] + a["bbox"][2] / 2, a["bbox"][1] + a["bbox"][3] / 2)
            for a in coco["annotations"] if a["image_id"] == image_id]


# ROI PNGs carry no calibration. RUMC/JB values are the per-scanner MPP observed
# on every wsitils slide of that source; TCGA slides were resampled to 0.5 by TIGER.
ROI_SOURCE_MPP = {"TCGA": 0.5, "RUMC": 0.485069, "JB": 0.456694}


def roi_source(file_name):
    name = file_name.split("/")[-1]
    if name.startswith("TCGA-"):
        return "TCGA"
    if name.startswith("TC_"):
        return "RUMC"
    if re.match(r"\d+[SB]_\[", name):
        return "JB"
    raise ValueError("unrecognized ROI file: " + file_name)


def select_component_rois(coco, seed=20261022, n_tcga=200):
    """All RUMC and JB tissue-cells ROIs plus a seeded random sample of TCGA ROIs."""
    boxes = {}
    for a in coco["annotations"]:
        boxes.setdefault(a["image_id"], []).append(a["bbox"])
    rois = []
    for image in sorted(coco["images"], key=lambda i: i["id"]):
        source = roi_source(image["file_name"])
        rois.append({"image_id": image["id"], "file_name": image["file_name"].split("/")[-1], "source": source,
                     "width": image["width"], "height": image["height"], "mpp": ROI_SOURCE_MPP[source],
                     "box_centers": [[b[0] + b[2] / 2, b[1] + b[3] / 2] for b in boxes.get(image["id"], [])]})
    tcga = [r for r in rois if r["source"] == "TCGA"]
    keep = set(r["image_id"] for r in random.Random(seed).sample(tcga, min(n_tcga, len(tcga))))
    return [r for r in rois if r["source"] != "TCGA" or r["image_id"] in keep]
