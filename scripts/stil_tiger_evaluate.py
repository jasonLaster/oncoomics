"""Score collected baseline outputs against TIGER wsitils references (development split only).

  python scripts/stil_tiger_evaluate.py --scores <dir>/tiger-til-scores-wsitils.csv \
      --collected private/stil/benchmark-20261022/baselines/collected_tiger-dev-baseline-v1.json \
      [--hovernet private/stil/benchmark-20261022/baselines/hovernet_slides.json] \
      --out private/stil/benchmark-20261022

Writes metrics.json, slide_predictions.csv and per-pipeline scatter / Bland-Altman
plots. Native outputs are compared uncalibrated, as prespecified in
docs/validation/stil-tiger-benchmark.md.
"""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from diana_omics.stil_benchmark import (  # noqa: E402
    agreement,
    bootstrap_ci,
    icc_absolute_single,
    lins_ccc,
    per_band,
    score_band,
)

SCORES_SHA256 = "a70061c9ad5191963d199d3137f7e205bf4ccd52755df3031a333e8a0f54c846"
SPLIT = Path(__file__).resolve().parents[1] / "manifests/stil_tiger_benchmark_split.json"
ENDPOINTS = {
    "ectil": "ECTIL-TCGA fold 0 uncalibrated prediction x 100",
    "mutils": "MuTILs TILs2AnyStromaRatio x 100 (unweighted global over admitted ROIs)",
    "modular": "Modular nuclear-area proxy: accepted lymphocyte+plasma nuclear area / predicted stroma (sampled cores)",
    "modular_competition": "Modular nuclear-area proxy on the tumor-vs-stroma competition mask",
    "hovernet": "Step-10 HoVer-Net lymphocyte nuclear area in non-nest stroma / estimated stroma area (sampled tiles)",
}


def _stem(filename):
    return Path(filename).stem


def predictions(collected, hovernet):
    out = {k: {} for k in ENDPOINTS}
    status = {k: {} for k in ENDPOINTS}
    for r in collected.get("ectil", []):
        sid = _stem(r["filename"])
        status["ectil"][sid] = r["status"]
        if r["status"] == "completed":
            out["ectil"][sid] = 100 * r["uncalibrated_model_output_fraction"]
    for r in collected.get("mutils", []):
        sid = _stem(r["filename"])
        status["mutils"][sid] = r["status"]
        if r["status"] == "completed":
            out["mutils"][sid] = 100 * r["native_summary"]["metrics"]["unweighted_global"]["TILs2AnyStromaRatio"]
    for r in collected.get("modular", []):
        sid = r["slide_key"]
        status["modular"][sid] = status["modular_competition"][sid] = r.get("status")
        if r.get("status") == "completed_experimental_comparison":
            v = r.get("exploratory_model_stroma_nuclear_area_percent")
            c = r.get("competition_model_stroma_nuclear_area_percent")
            if v is not None:
                out["modular"][sid] = v
            if c is not None:
                out["modular_competition"][sid] = c
    for r in hovernet or []:
        status["hovernet"][r["image_id"]] = r["status"]
        if r["status"] == "completed" and r.get("stil_nuclear_area_percent") is not None:
            out["hovernet"][r["image_id"]] = r["stil_nuclear_area_percent"]
    return out, status


def summarize(name, preds, status, refs, dev, slides_meta):
    callable_ids = [i for i in dev if i in preds]
    no_calls = [i for i in dev if i not in preds]
    result = {"pipeline": name, "endpoint": ENDPOINTS[name], "n_development": len(dev), "n_callable": len(callable_ids),
              "no_calls": [{"image_id": i, "status": status.get(i, "not_run")} for i in no_calls]}
    if len(callable_ids) < 3:
        result["status"] = "insufficient_callable_slides"
        return result
    x = [refs[i] for i in callable_ids]
    y = [preds[i] for i in callable_ids]
    result["agreement"] = agreement(x, y)
    result["mae_ci95"] = bootstrap_ci(x, y, lambda a, b: sum(abs(p - q) for p, q in zip(a, b)) / len(a), seed=1)
    result["ccc_ci95"] = bootstrap_ci(x, y, lins_ccc, seed=2)
    result["icc_ci95"] = bootstrap_ci(x, y, icc_absolute_single, seed=3)
    records = [{"image_id": i, "reference": refs[i], "prediction": preds[i]} for i in callable_ids]
    result["per_band"] = per_band(records)
    groups = {}
    for i in callable_ids:
        meta = slides_meta[i]
        keys = ["pitfall_comment" if meta["pitfall_flags"] else "no_pitfall_comment", "source_" + meta["source"]]
        if meta["source"] == "numeric_SB":
            keys.append("JB_resection" if i.endswith("S") else "JB_biopsy")
        keys += ["pitfall_" + f for f in meta["pitfall_flags"]]
        for k in keys:
            groups.setdefault(k, []).append(i)
    result["subgroups"] = {}
    for k, ids in sorted(groups.items()):
        d = [preds[i] - refs[i] for i in ids]
        result["subgroups"][k] = {"n": len(ids), "mae_pp": sum(abs(v) for v in d) / len(d), "bias": sum(d) / len(d)}
    return result


def plot(name, refs, preds, ids, out_dir, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = [refs[i] for i in ids]
    y = [preds[i] for i in ids]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4))
    ax = axes[0]
    ax.scatter(x, y, s=22, color="#2f6db5", alpha=.85, edgecolor="none")
    lim = max(100, max(y) * 1.05)
    ax.plot([0, 100], [0, 100], color="#999999", lw=1, ls="--", label="identity")
    for c in (10, 30):
        ax.axvline(c, color="#dddddd", lw=.8)
        ax.axhline(c, color="#dddddd", lw=.8)
    ax.set_xlim(-2, 100)
    if max(y) < 20:
        # Nuclear-area proxies sit far below the visual scale; symlog keeps them legible.
        ax.set_yscale("symlog", linthresh=0.1)
        ax.set_ylim(0, 100)
    else:
        ax.set_ylim(-2, lim)
    ax.set_xlabel("TIGER pathologist sTIL (%)")
    ax.set_ylabel("Pipeline output (%)")
    ax.set_title("Agreement")
    ax.legend(frameon=False, loc="upper left")
    ax = axes[1]
    mean = [(a + b) / 2 for a, b in zip(x, y)]
    diff = [b - a for a, b in zip(x, y)]
    bias = sum(diff) / len(diff)
    sd = (sum((d - bias) ** 2 for d in diff) / (len(diff) - 1)) ** .5
    ax.scatter(mean, diff, s=22, color="#2f6db5", alpha=.85, edgecolor="none")
    ax.axhline(0, color="#999999", lw=1)
    ax.axhline(bias, color="#c4472b", lw=1.2, label=f"bias {bias:.1f}")
    for v in (bias - 1.96 * sd, bias + 1.96 * sd):
        ax.axhline(v, color="#c4472b", lw=1, ls=":")
    ax.set_xlabel("Mean of reference and output (%)")
    ax.set_ylabel("Output − reference (pp)")
    ax.set_title(f"Bland–Altman (LoA {bias - 1.96 * sd:.1f} to {bias + 1.96 * sd:.1f})")
    ax.legend(frameon=False, loc="lower left")
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    path = out_dir / f"{name}_agreement.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path.name


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scores", type=Path, required=True)
    p.add_argument("--collected", type=Path, required=True)
    p.add_argument("--hovernet", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if hashlib.sha256(args.scores.read_bytes()).hexdigest() != SCORES_SHA256:
        raise SystemExit("TIGER score file hash mismatch")
    refs = {r["image-id"]: float(r["tils-score"]) for r in csv.DictReader(args.scores.open(newline=""))}
    split = json.loads(SPLIT.read_text())
    meta = {s["image_id"]: s for s in split["slides"]}
    dev = sorted(i for i, s in meta.items() if s["split"] == "development")
    collected = json.loads(args.collected.read_text())
    hovernet = json.loads(args.hovernet.read_text()) if args.hovernet else None
    preds, status = predictions(collected, hovernet)
    for name, values in preds.items():
        leaked = set(values) - set(dev)
        if leaked:
            raise SystemExit(f"{name} has non-development predictions: {sorted(leaked)}")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "plots").mkdir(exist_ok=True)
    results = []
    for name in ENDPOINTS:
        if not status[name]:
            continue
        r = summarize(name, preds[name], status[name], refs, dev, meta)
        ids = [i for i in dev if i in preds[name]]
        if len(ids) >= 3:
            r["plot"] = "plots/" + plot(name, refs, preds[name], ids, args.out / "plots", ENDPOINTS[name])
        results.append(r)
    (args.out / "metrics.json").write_text(json.dumps(results, indent=2) + "\n")
    with (args.out / "slide_predictions.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_id", "source", "band", "pitfall_flags", "dev_fold", "reference"] + list(ENDPOINTS))
        for i in dev:
            w.writerow([i, meta[i]["source"], score_band(refs[i]), ";".join(meta[i]["pitfall_flags"]), meta[i]["dev_fold"], refs[i]]
                       + [f"{preds[n][i]:.4f}" if i in preds[n] else "" for n in ENDPOINTS])
    for r in results:
        a = r.get("agreement")
        if a:
            print(f"{r['pipeline']:20s} n={r['n_callable']:2d} MAE={a['mae_pp']:.1f} bias={a['bias']:.1f} "
                  f"CCC={a['lins_ccc']:.2f} ICC={a['icc_a1']:.2f} rho={a['spearman']:.2f}")


if __name__ == "__main__":
    main()
