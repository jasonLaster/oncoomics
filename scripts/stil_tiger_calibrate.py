"""Out-of-fold monotone endpoint mapping on the TIGER development split.

Implements docs/validation/stil-tiger-calibration-spec.md using existing baseline
outputs only (no inference):

  python scripts/stil_tiger_calibrate.py --scores <dir>/tiger-til-scores-wsitils.csv \
      --bench private/stil/benchmark-20261022
"""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from diana_omics.stil_benchmark import agreement, bootstrap_ci, icc_absolute_single, lins_ccc, per_band  # noqa: E402
from diana_omics.stil_calibration import cross_fit, fit, predict  # noqa: E402

SCORES_SHA256 = "a70061c9ad5191963d199d3137f7e205bf4ccd52755df3031a333e8a0f54c846"
DENSITY_OFFSET, PERCENT_OFFSET = 10.0, 0.01
MUTILS_PX_PER_MM2 = 4e6  # 0.5 um/px working scale
MODELS = ("log_logit", "isotonic")


def hovernet_features(bench):
    slides = {r["image_id"]: r for r in json.loads((bench / "baselines/hovernet_slides.json").read_text())}
    out, status = {}, {}
    for image_id, r in slides.items():
        rows = list(csv.DictReader((bench / "baselines/hovernet_tiles" / (image_id + ".csv")).open()))
        bedc = [t for t in rows if float(t["hv_tumor"]) >= 5
                and not (float(t["hv_dead"]) >= 10 and float(t["hv_dead"]) / max(float(t["hv_n"]), 1) >= 0.2)
                and float(t["px_rbc"]) < 0.3]
        stroma = sum(float(t["stroma_um2"]) for t in bedc)
        status[image_id] = r["status"]
        if r["status"] != "completed" or stroma <= 0:
            continue
        # Consistency with the saved endpoint: 1.5 x nuclear area / stroma.
        recon = 100 * min(1.5 * sum(float(t["lymph_stromal_nuc_area_um2"]) for t in bedc) / stroma, 1)
        if abs(recon - r["stil_nuclear_area_percent"]) > 1e-6:
            raise SystemExit(f"tile metrics do not reproduce the saved HoVer-Net endpoint for {image_id}")
        out[image_id] = {"stromal_lymph_density_per_mm2": sum(float(t["lymph_stromal_n"]) for t in bedc) / (stroma / 1e6),
                         "nuclear_area_stil_percent": r["stil_nuclear_area_percent"],
                         "lymph_fraction_of_nuclei_percent": 100 * r["lymph_nuclei_fraction"]}
    return out, status


def mutils_features(collected):
    out, status = {}, {}
    for r in collected["mutils"]:
        image_id = Path(r["filename"]).stem
        if r["status"] == "running":
            continue  # cancelled at the budget cap: not-run
        status[image_id] = r["status"]
        if r["status"] != "completed":
            continue
        m = r["native_summary"]["metrics"]["unweighted_global"]
        out[image_id] = {"til_cells_per_mm2_stroma": m["nTILsCells2AnyStromaRegionArea"] * MUTILS_PX_PER_MM2,
                         "til_region_to_stroma_percent": 100 * m["TILs2AnyStromaRatio"],
                         "til_cells_of_stroma_cells_percent": 100 * m["nTILsCells2nAllStromaCells"]}
    return out, status


def ectil_features(collected):
    out, status = {}, {}
    for r in collected["ectil"]:
        image_id = Path(r["filename"]).stem
        status[image_id] = r["status"]
        if r["status"] == "completed":
            out[image_id] = {"raw_prediction_percent": 100 * r["uncalibrated_model_output_fraction"]}
    return out, status


ANALYSES = [  # (pipeline, feature, offset, primary)
    ("hovernet", "stromal_lymph_density_per_mm2", DENSITY_OFFSET, True),
    ("hovernet", "nuclear_area_stil_percent", PERCENT_OFFSET, False),
    ("hovernet", "lymph_fraction_of_nuclei_percent", PERCENT_OFFSET, False),
    ("mutils", "til_cells_per_mm2_stroma", DENSITY_OFFSET, True),
    ("mutils", "til_region_to_stroma_percent", PERCENT_OFFSET, False),
    ("mutils", "til_cells_of_stroma_cells_percent", PERCENT_OFFSET, False),
    ("ectil", "raw_prediction_percent", PERCENT_OFFSET, True),
]


def passes(a, icc_ci, no_call_rate):
    acc = {c["cutoff"]: c["accuracy"] for c in a["categorical"]}
    checks = {"icc_ge_0.66": a["icc_a1"] >= 0.66, "icc_lower_ge_0.50": icc_ci[0] >= 0.50, "ccc_ge_0.66": a["lins_ccc"] >= 0.66,
              "acc10_ge_0.77": acc[10] >= 0.77, "acc30_ge_0.81": acc[30] >= 0.81, "abs_bias_le_5": abs(a["bias"]) <= 5,
              "mae_le_15": a["mae_pp"] <= 15, "no_call_rate_le_0.05": no_call_rate <= 0.05}
    return all(checks.values()), checks


def subgroups(ids, refs, preds, meta):
    groups = {}
    for i in ids:
        keys = ["source_" + meta[i]["source"]]
        if meta[i]["source"] == "numeric_SB":
            keys.append("JB_resection" if i.endswith("S") else "JB_biopsy")
        keys.append("pitfall_comment" if meta[i]["pitfall_flags"] else "no_pitfall_comment")
        for k in keys:
            groups.setdefault(k, []).append(i)
    out = {}
    for k, g in sorted(groups.items()):
        d = [preds[i] - refs[i] for i in g]
        out[k] = {"n": len(g), "mae_pp": sum(abs(v) for v in d) / len(d), "bias": sum(d) / len(d)}
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scores", type=Path, required=True)
    p.add_argument("--bench", type=Path, required=True)
    args = p.parse_args()
    if hashlib.sha256(args.scores.read_bytes()).hexdigest() != SCORES_SHA256:
        raise SystemExit("TIGER score file hash mismatch")
    refs = {r["image-id"]: float(r["tils-score"]) for r in csv.DictReader(args.scores.open(newline=""))}
    split = json.loads((ROOT / "manifests/stil_tiger_benchmark_split.json").read_text())
    meta = {s["image_id"]: s for s in split["slides"]}
    dev = {i for i, s in meta.items() if s["split"] == "development"}
    collected = json.loads((args.bench / "baselines/collected_tiger-dev-baseline-v1.json").read_text())
    features = {"hovernet": hovernet_features(args.bench), "mutils": mutils_features(collected), "ectil": ectil_features(collected)}
    out_dir = args.bench / "calibration"
    (out_dir / "plots").mkdir(parents=True, exist_ok=True)
    results, oof_rows = [], {}
    for pipeline, feature, offset, primary in ANALYSES:
        values, status = features[pipeline]
        assert set(values) <= dev and set(status) <= dev, "non-development slide in features"
        ids = sorted(values)
        attempted = sorted(status)
        no_call_rate = (len(attempted) - len(ids)) / len(attempted)
        x = [values[i][feature] for i in ids]
        r = [refs[i] for i in ids]
        folds = [meta[i]["dev_fold"] for i in ids]
        for model in MODELS:
            oof, fitted = cross_fit(ids, x, r, folds, model, offset)
            y = [oof[i] for i in ids]
            a = agreement(r, y)
            icc_ci = bootstrap_ci(r, y, icc_absolute_single, seed=3)
            ok, checks = passes(a, icc_ci, no_call_rate)
            full = fit(model, x, r, offset)
            insample = agreement(r, predict(full, x))
            name = f"{pipeline}:{feature}:{model}"
            results.append({
                "analysis": name, "pipeline": pipeline, "feature": feature, "model": model, "primary": primary,
                "n_scored": len(ids), "n_attempted": len(attempted), "no_call_rate": no_call_rate,
                "not_run": sorted(dev - set(attempted)), "feature_vs_reference_spearman": agreement(r, x)["spearman"],
                "oof": a, "oof_mae_ci95": bootstrap_ci(r, y, lambda p_, q_: sum(abs(u - v) for u, v in zip(p_, q_)) / len(p_), seed=1),
                "oof_ccc_ci95": bootstrap_ci(r, y, lins_ccc, seed=2), "oof_icc_ci95": icc_ci,
                "oof_per_band": per_band([{"reference": refs[i], "prediction": oof[i]} for i in ids]),
                "oof_subgroups": subgroups(ids, refs, oof, meta), "passes_minimum_tier": ok, "criteria": checks,
                "fold_models": {str(k): v for k, v in fitted.items()},
                "in_sample_reference_only": {k: insample[k] for k in ("mae_pp", "bias", "lins_ccc", "icc_a1", "spearman")},
            })
            for i in ids:
                oof_rows.setdefault(i, {})[name] = oof[i]
            if primary:
                import stil_tiger_evaluate
                stil_tiger_evaluate.ENDPOINTS.setdefault(name.replace(":", "__"), f"Out-of-fold {model} map of {pipeline} {feature}")
                stil_tiger_evaluate.plot(name.replace(":", "__"), refs, oof, ids, out_dir / "plots",
                                         f"OUT-OF-FOLD {model} mapping: {pipeline} {feature}")
    (out_dir / "calibration_results.json").write_text(json.dumps(results, indent=2) + "\n")
    names = [f"{p}:{f}:{m}" for p, f, _, _ in ANALYSES for m in MODELS]
    with (out_dir / "oof_predictions.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_id", "dev_fold", "reference"] + names)
        for i in sorted(oof_rows):
            w.writerow([i, meta[i]["dev_fold"], refs[i]] + [f"{oof_rows[i][n]:.3f}" if n in oof_rows[i] else "" for n in names])
    for res in results:
        a = res["oof"]
        acc = {c["cutoff"]: c["accuracy"] for c in a["categorical"]}
        print(f"{'P' if res['primary'] else ' '} {res['analysis']:62s} n={res['n_scored']:2d} rho_feat={res['feature_vs_reference_spearman']:.2f} "
              f"MAE={a['mae_pp']:.1f} bias={a['bias']:+.1f} CCC={a['lins_ccc']:.2f} ICC={a['icc_a1']:.2f} "
              f"acc10={acc[10]:.2f} acc30={acc[30]:.2f} pass={res['passes_minimum_tier']} | in-sample CCC={res['in_sample_reference_only']['lins_ccc']:.2f}")


if __name__ == "__main__":
    main()
