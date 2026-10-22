"""Build a private HTML reviewer packet comparing two-class and v2 assessable-stroma outputs.

Reads verifier outputs (``stil_modular_verify_v2.py``), sampling maps and per-tile
review overlays; writes a self-contained folder. The packet reports a model-derived
immune nuclear-area percentage in predicted assessable stroma. It carries no
clinical sTIL label and is not a pathologist score.
"""

import argparse
import html
import json
import shutil
from pathlib import Path

from PIL import Image, PngImagePlugin

PngImagePlugin.MAX_TEXT_CHUNK = 1 << 30
GATES = (("a_immune_in_assessable_stroma", "a"), ("b_tumor_mask_vs_nuclei", "b"), ("c_ink_and_off_tissue_tiles", "c"))


def pct(value, scale=1.):
    return "—" if value is None else f"{value * scale:.1f}"


def flags(gates):
    marks = [name for key, name in GATES if gates[key]["flag"]]
    return "pass" if not marks else "flag " + ",".join(marks)


def thumbnail(source, destination, width=1400, half=None):
    image = Image.open(source).convert("RGB")
    if half is not None:
        w, h = image.size
        image = image.crop((0, 0, w, h // 2) if half == "top" else (0, h // 2, w, h))
    image.thumbnail((width, width))
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, optimize=True)


def section(title, keys, results, args, out):
    rows, figures = [], []
    for key in keys:
        old = results["legacy"].get(key)
        new = results["v2"].get(key, {})
        legacy_tiles = results.get("legacy_same_tiles", {}).get(key)
        slide = (new or old or legacy_tiles)["slide"]
        cells = [html.escape(Path(slide).stem), key]
        sources = ((old and old["native"], old and old["reported_native_percent"]),
                   (old and old["competition"], old and old["reported_competition_percent"]),
                   (legacy_tiles, None), (new or None, None))
        for source, reported in sources:
            if not source:
                cells += ["—"] * 4
                continue
            # Legacy ratios are shown as originally reported (callable tiles only).
            value = reported if reported is not None else source["assessable_stroma_immune_nuclear_area_percent"]
            cells += [pct(value),
                      pct(source["immune_in_assessable_fraction"], 100),
                      f"{pct(source['tumor_mask_fraction'], 100)} / {pct(source['tumor_nucleus_fraction'], 100)}",
                      flags(source["qc_gates"])]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        map_path = args.inputs / key / "sampling_map.png"
        if map_path.exists():
            thumbnail(map_path, out / "maps" / f"{key}.png", half="bottom")
            figures.append(f"<figure><img src='maps/{key}.png'><figcaption>{key} {html.escape(Path(slide).stem)}: v2 sampling "
                           "(green tissue, yellow fat/white, magenta ink; red new tile, blue reused tile, black X legacy tile now excluded)</figcaption></figure>")
        for run, label in ((args.run, "v2 sampled tiles"), (args.legacy_tiles_run, "legacy tiles, v2 masks")):
            if not run or not (run / key).exists():
                continue
            overlays = sorted((run / key).glob("*/review_v2.png"))[:args.overlays]
            for overlay in overlays:
                name = f"{run.name}-{overlay.parent.name}.png"
                thumbnail(overlay, out / "overlays" / name, width=1152)
                figures.append(f"<figure><img src='overlays/{name}'><figcaption>{label}: {overlay.parent.name}</figcaption></figure>")
    header = ("<tr><th rowspan=2>Slide</th><th rowspan=2>Key</th><th colspan=4>Legacy two-class, native mask</th>"
              "<th colspan=4>Legacy two-class, competition mask</th><th colspan=4>v2 masks on legacy tiles</th>"
              "<th colspan=4>v2 masks on v2 sampling</th></tr><tr>" + "<th>Immune area % of stroma</th><th>Immune nuclei in stroma %</th>"
              "<th>Tumor mask / tumor nuclei %</th><th>Gates</th>" * 4 + "</tr>")
    return f"<h2>{title}</h2><table>{header}{''.join(rows)}</table>" + "".join(figures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verification", type=Path, required=True, help="verify_v2 JSON with v2 and legacy results")
    parser.add_argument("--legacy-tiles-verification", type=Path, help="verify_v2 JSON for v2 masks on the legacy tiles")
    parser.add_argument("--inputs", type=Path, required=True, help="v2 inputs with sampling maps")
    parser.add_argument("--run", type=Path, help="Collected v2 run with review_v2.png overlays")
    parser.add_argument("--legacy-tiles-run", type=Path, help="Collected v2-mask run on legacy tiles")
    parser.add_argument("--overlays", type=int, default=6)
    parser.add_argument("--notes", type=Path, help="Optional private HTML fragment with run notes, placed after the summary")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    results = json.loads(args.verification.read_text())
    results.setdefault("v2", {})
    if args.legacy_tiles_verification:
        results["legacy_same_tiles"] = json.loads(args.legacy_tiles_verification.read_text())["v2"]
    args.out.mkdir(parents=True, exist_ok=False)
    keys = sorted(set(results["legacy"]) | set(results["v2"]))
    groups = {k: (results["v2"].get(k) or results["legacy"][k])["candidate_tissue_group"] for k in keys}
    breast = [k for k in keys if groups[k].startswith("breast")]
    nodes = [k for k in keys if not groups[k].startswith("breast")]
    gates = results["gates"]
    body = [
        "<h1>Modular H&amp;E research packet: sampling and stroma-definition fix</h1>",
        "<p class=warn>Research diagnostic only. Values are model-derived immune (lymphocyte + plasma-cell) nuclear area as a "
        "percentage of model-predicted assessable stroma in sampled tiles. They are not pathologist sTIL scores, are not "
        "calibrated against one, and must not be reported as clinical sTIL.</p>",
        "<p>v2 changes: tiles sampled from an artifact-aware tissue map (explicit pen and margin-ink exclusion, fat and white "
        "space excluded, full-resolution recheck); VISTA-PATH prompted for background, tumor, stroma, immune infiltrate, fat "
        "and necrosis with an argmax instead of per-tile Otsu; assessable stroma = stroma + immune infiltrate (ITWG), "
        "excluding tumor, fat, necrosis, background and ink artifact.</p>",
        f"<p>Gates: (a) immune nuclei inside assessable stroma ≥ {gates['immune_in_assessable_minimum']:.0%} on breast slides; "
        f"(b) tumor-mask fraction of tissue vs CytoFormer tumor-nucleus fraction differ by ≤ "
        f"{gates['tumor_fraction_max_abs_difference']:.0%} absolute and ≤ {gates['tumor_fraction_max_ratio']:.0f}× when either "
        f"exceeds {gates['tumor_fraction_ratio_floor']:.0%}; (c) zero sampled tiles on ink or off tissue. Legacy columns show the "
        "ratio as originally reported (predicted stroma alone as denominator, tiles without nuclei skipped); their gates use "
        "tumor mask / (tumor + stroma) as the tumor fraction.</p>",
        args.notes.read_text() if args.notes else "",
        section("Breast slides", breast, results, args, args.out),
        section("Sentinel nodes (reported separately; gate a not applied)", nodes, results, args, args.out) if nodes else "",
    ]
    style = ("body{font:14px system-ui;margin:24px;max-width:1500px}table{border-collapse:collapse;margin:12px 0}"
             "td,th{border:1px solid #bbb;padding:4px 6px;text-align:center}figure{display:inline-block;margin:8px;max-width:720px}"
             "img{max-width:100%}.warn{background:#fff3cd;padding:8px;border:1px solid #e0c060}")
    (args.out / "index.html").write_text(f"<!doctype html><meta charset=utf-8><title>Modular H&amp;E research packet v2</title>"
                                         f"<style>{style}</style>{''.join(body)}\n")
    shutil.copyfile(args.verification, args.out / "verification.json")
    if args.legacy_tiles_verification:
        shutil.copyfile(args.legacy_tiles_verification, args.out / "verification_legacy_tiles.json")
    print(args.out / "index.html")


if __name__ == "__main__":
    main()
