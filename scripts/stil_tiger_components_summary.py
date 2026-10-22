"""Summarize wsirois component records per pipeline, applying the leakage audit.

  python scripts/stil_tiger_components_summary.py --dir private/stil/benchmark-20261022/components

Reads `<pipeline>_component_records.json` and writes component_metrics.json.
Exclusions follow docs/validation/stil-tiger-benchmark-leakage.md: VISTA-PATH
tissue Dice is contaminated on every wsirois ROI; TCGA ROIs are excluded for
MuTILs and reported separately ("possibly seen") for HoVer-Net.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from diana_omics.stil_benchmark import pooled_detection  # noqa: E402

PIPELINES = {
    "modular": {"detection_key": "detection_raw", "tissue": "VISTA-PATH", "tissue_excluded_sources": {"TCGA", "RUMC", "JB"},
                "detection_excluded_sources": set(), "area_key": "pred_immune_nuclear_um2_in_ref_stroma"},
    "hovernet": {"detection_key": "detection_lymph", "tissue": "step-10 tumour-nest mask", "tissue_excluded_sources": set(),
                 "detection_excluded_sources": set(), "possibly_seen_sources": {"TCGA"},
                 "area_key": "pred_lymph_nuclear_um2_in_ref_stroma"},
    "mutils": {"detection_key": "detection_lymph", "tissue": "MuTILs regions", "tissue_excluded_sources": {"TCGA"},
               "detection_excluded_sources": {"TCGA"}, "area_key": "pred_lymph_nuclear_um2_in_ref_stroma"},
}


def pooled_dice(records, part):
    inter = sum(r["dice"][part]["intersection"] for r in records)
    total = sum(r["dice"][part]["pred_pixels"] + r["dice"][part]["ref_pixels"] for r in records)
    per_roi = [r["dice"][part]["dice"] for r in records if r["dice"][part]["dice"] is not None]
    per_roi.sort()
    return {"pooled_dice": 2 * inter / total if total else None, "n_rois": len(records),
            "median_roi_dice": per_roi[len(per_roi) // 2] if per_roi else None,
            "pred_fraction_of_annotated": sum(r["dice"][part]["pred_pixels"] for r in records) / max(sum(r["annotated_pixels"] for r in records), 1),
            "ref_fraction_of_annotated": sum(r["dice"][part]["ref_pixels"] for r in records) / max(sum(r["annotated_pixels"] for r in records), 1)}


def summarize(name, records):
    cfg = PIPELINES[name]
    ok = [r for r in records if r["status"] == "ok"]
    out = {"pipeline": name, "n_records": len(records), "n_scored": len(ok), "tissue_model": cfg["tissue"], "by_source": {}}
    for source in ("RUMC", "JB", "TCGA"):
        rs = [r for r in ok if r["source"] == source]
        if not rs:
            continue
        s = {"n_rois": len(rs), "n_ref_cells": sum(r["n_ref_cells"] for r in rs)}
        s["tissue_status"] = ("excluded_training_overlap" if source in cfg["tissue_excluded_sources"] else
                              "possibly_seen" if source in cfg.get("possibly_seen_sources", set()) else "clean")
        s["stroma"] = pooled_dice(rs, "stroma")
        s["tumor"] = pooled_dice(rs, "tumor")
        s["detection_status"] = ("excluded_training_overlap" if source in cfg["detection_excluded_sources"] else
                                 "possibly_seen" if source in cfg.get("possibly_seen_sources", set()) else "clean")
        s["detection"] = {d: pooled_detection([r[cfg["detection_key"]][d] for r in rs]) for d in ("4um", "8um")}
        ep = [r["endpoint"] for r in rs]
        stroma_mm2 = sum(e["ref_stroma_um2"] for e in ep) / 1e6
        s["endpoint"] = {
            "ref_stroma_mm2": stroma_mm2,
            "ref_cells_per_mm2_stroma": sum(e["ref_cells_in_ref_stroma"] for e in ep) / stroma_mm2 if stroma_mm2 else None,
            "pred_cells_per_mm2_ref_stroma": sum(e["pred_cells_in_ref_stroma"] for e in ep) / stroma_mm2 if stroma_mm2 else None,
            "pred_immune_nuclear_area_percent_of_ref_stroma":
                100 * sum(e[cfg["area_key"]] for e in ep) / (stroma_mm2 * 1e6) if stroma_mm2 else None,
        }
        if s["endpoint"]["ref_cells_per_mm2_stroma"]:
            s["endpoint"]["pred_to_ref_density_ratio"] = s["endpoint"]["pred_cells_per_mm2_ref_stroma"] / s["endpoint"]["ref_cells_per_mm2_stroma"]
        out["by_source"][source] = s
    clean = [r for r in ok if r["source"] not in cfg["detection_excluded_sources"] and r["source"] not in cfg.get("possibly_seen_sources", set())]
    out["clean_detection_pooled"] = {d: pooled_detection([r[cfg["detection_key"]][d] for r in clean]) for d in ("4um", "8um")}
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", type=Path, required=True)
    args = p.parse_args()
    results = []
    for name in PIPELINES:
        path = args.dir / f"{name}_component_records.json"
        if path.exists():
            results.append(summarize(name, json.loads(path.read_text())))
    (args.dir / "component_metrics.json").write_text(json.dumps(results, indent=2) + "\n")
    for r in results:
        for source, s in r["by_source"].items():
            d = s["detection"]["4um"]
            e = s["endpoint"]
            print(f"{r['pipeline']:9s} {source:5s} n={s['n_rois']:3d} stromaDice={s['stroma']['pooled_dice']:.2f} ({s['tissue_status']}) "
                  f"tumorDice={s['tumor']['pooled_dice'] or 0:.2f} P={d['precision'] or 0:.2f} R={d['recall'] or 0:.2f} F1={d['f1'] or 0:.2f} "
                  f"density pred/ref={e.get('pred_to_ref_density_ratio') or 0:.2f} nucArea%={e['pred_immune_nuclear_area_percent_of_ref_stroma'] or 0:.1f}")


if __name__ == "__main__":
    main()
