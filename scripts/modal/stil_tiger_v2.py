"""Run the v2 modular pipeline (artifact-aware sampling, multi-class stroma) on the TIGER benchmark.

Development split only. Runs `segment_v2` / `classify_v2` from a hash-pinned copy of
scripts/modal/stil_modular_execute.py at commit d8eca7d4, with storage rebound to the
private TIGER volumes, as stil_tiger_baselines.py does for the committed runner.

Stages (local entrypoint `--stage`):

- rois-segment / rois-classify / rois-evaluate: v2 tissue labels on the wsirois ROI tiles
  prepared by stil_tiger_components.py, reusing every nucleus and CytoFormer class from
  run tiger-rois-baseline-v1, so only VISTA-PATH runs on GPU. Evaluation writes per-ROI
  stroma_mask.png / tumor_mask.png / cells.json and records scored with
  diana_omics.stil_benchmark (assessable stroma = labels {2, 3}).
- slides-v1tiles-segment / slides-v1tiles-classify: v2 labels on the 32 v1 cores per dev
  slide (run tiger-dev-baseline-v1), all nuclei reused; isolates the mask change.
- sample (CPU): v2 sampler (scripts/stil_sample_tiles.py) on dev slides, resampled to
  0.5 um/px, into inputs-v2; `--maps-only` writes sampling maps and counts only.
- slides-segment / slides-classify: full v2 chain on inputs-v2 (new Cellpose + CytoFormer).
- collect: slide-level rows [{image_id, status, value_percent, endpoint, n_tiles_scored,
  n_tiles_no_call, qc_gates}] for stil_tiger_evaluate.py.

VISTA-PATH was trained on TIGER wsirois/wsibulk and BCSS: its ROI stroma Dice is
contaminated (best case only). Every GPU stage needs the user's budget approval.
"""

import ast
import hashlib
import json
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else None
FROZEN_DIR = (ROOT / ".runs/stil-tiger-benchmark/frozen") if modal.is_local() else Path("/opt/frozen")
FROZEN_NAME = "stil_modular_execute_d8eca7d4.py"
PINNED_SHA256 = {
    FROZEN_NAME: "539498c177a7acfbae33d7a88d525192f247c69305f580b5b06de27c04e2b54b",
    # Mounted by the frozen runner's image block from this checkout; pinned here.
    "src/diana_omics/stil_tissue.py": "8526c8b5ac3e2921b0cf6541fcc0b2c034862ab9003679cd7c2e5d50f871d4cb",
    "src/diana_omics/stil_sampling.py": "fb6187d5a50556e82a49cde8a49ca56bda777047a1fdc26854291d920d4d80dc",
    "scripts/stil_sample_tiles.py": "a0fc631d42eed25eec8826e819424485be343c4bd93eeb63606021d3277b58aa",
}
ROI_DIR = "/bench/source/wsirois/roi-level-annotations/tissue-cells"
ROI_V1_RUN, SLIDE_V1_RUN = "tiger-rois-baseline-v1", "tiger-dev-baseline-v1"
ROI_RUN, SLIDE_V1TILES_RUN, SLIDE_RUN = "tiger-rois-v2masks-v1", "tiger-dev-v2masks-v1tiles", "tiger-dev-v2-v1"

app = modal.App("diana-stil-tiger-v2")
bench = modal.Volume.from_name("diana-stil-tiger-benchmark", create_if_missing=False)
components = modal.Volume.from_name("diana-stil-tiger-components", create_if_missing=False)
slides_volume = modal.Volume.from_name("diana-stil-tiger-slides-dev", create_if_missing=False)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _exec_frozen():
    """Execute the v2 stage functions and their helpers from the pinned runner into this module."""
    if modal.is_local():
        for name, expected in PINNED_SHA256.items():
            path = FROZEN_DIR / name if name == FROZEN_NAME else ROOT / name
            if _sha(path) != expected:
                raise RuntimeError(f"pinned file changed: {name}")
    source = (FROZEN_DIR / FROZEN_NAME).read_bytes()
    if hashlib.sha256(source).hexdigest() != PINNED_SHA256[FROZEN_NAME]:
        raise RuntimeError("frozen v2 runner hash mismatch")
    wanted_assigns = {"image", "V2_SEGMENTED", "V2_CLASSIFIED", "REUSED_NUCLEUS_FILES", "REUSED_CLASS_FILES"}
    wanted_functions = {"digest", "reusable_tiles", "segment_v2", "classify_v2"}
    body, found = [], set()
    for node in ast.parse(source.decode()).body:
        if isinstance(node, ast.Assign):
            names = {e.id for t in node.targets for e in (t.elts if isinstance(t, ast.Tuple) else [t]) if isinstance(e, ast.Name)}
            if names & wanted_assigns:
                body.append(node)
                found |= names
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            node.decorator_list = []
            body.append(node)
            found.add(node.name)
        elif isinstance(node, ast.If):  # the local-only image mounts
            body.append(node)
    missing = (wanted_assigns | wanted_functions) - found
    if missing:
        raise RuntimeError(f"frozen runner lacks {sorted(missing)}")
    # The image block resolves the project from __file__ (parents[2]); this file is also in scripts/modal.
    exec(compile(ast.Module(body=body, type_ignores=[]), str(FROZEN_DIR / FROZEN_NAME), "exec"), globals())


_exec_frozen()
modular_image = image  # noqa: F821  (defined by the frozen runner, with VISTA, CytoFormer and shared modules)
helper_image = modal.Image.debian_slim(python_version="3.11").pip_install("numpy==1.26.4", "pillow==11.1.0")
if modal.is_local():
    modular_image = (modular_image.add_local_dir(FROZEN_DIR, "/opt/frozen")
                     .add_local_file(ROOT / "scripts/stil_sample_tiles.py", "/opt/repo/scripts/stil_sample_tiles.py")
                     .add_local_file(ROOT / "src/diana_omics/stil_sampling.py", "/opt/repo/src/diana_omics/stil_sampling.py")
                     .add_local_file(ROOT / "src/diana_omics/__init__.py", "/opt/repo/src/diana_omics/__init__.py"))
    helper_image = (helper_image.add_local_dir(FROZEN_DIR, "/opt/frozen")
                    .add_local_file(ROOT / "src/diana_omics/stil_benchmark.py", "/opt/helpers/stil_benchmark.py"))
_frozen_segment_v2, _frozen_classify_v2 = segment_v2, classify_v2  # noqa: F821
GPU_SEGMENT = dict(image=modular_image, gpu="A10G", cpu=4, memory=32768, timeout=7200, max_containers=3)
GPU_CLASSIFY = dict(image=modular_image, gpu="A100-40GB", cpu=4, memory=32768, timeout=14400, max_containers=2)
CPU_CLASSIFY = dict(image=modular_image, cpu=4, memory=16384, timeout=7200, max_containers=4)


def _bind(target):
    """The frozen stages commit through the module-global `volume`; point it at this container's mount."""
    globals()["volume"] = target


# ROI component check: components volume at /data. Classification only copies reused files, so CPU suffices.
@app.function(volumes={"/data": components}, **GPU_SEGMENT)
def roi_segment(slide_key: str, run_id: str = ROI_RUN):
    _bind(components)
    return _frozen_segment_v2(slide_key, run_id, "inputs", ROI_V1_RUN)


@app.function(volumes={"/data": components}, **CPU_CLASSIFY)
def roi_classify(slide_key: str, run_id: str = ROI_RUN):
    _bind(components)
    return _frozen_classify_v2(slide_key, run_id, ROI_V1_RUN)


# Slide-level runs: benchmark volume at /data.
@app.function(volumes={"/data": bench}, **GPU_SEGMENT)
def slide_segment(slide_key: str, run_id: str, inputs: str, reuse_run: str):
    _bind(bench)
    return _frozen_segment_v2(slide_key, run_id, inputs, reuse_run)


@app.function(volumes={"/data": bench}, **CPU_CLASSIFY)
def slide_classify_reused(slide_key: str, run_id: str, reuse_run: str):
    _bind(bench)
    return _frozen_classify_v2(slide_key, run_id, reuse_run)


@app.function(volumes={"/data": bench}, **GPU_CLASSIFY)
def slide_classify(slide_key: str, run_id: str, reuse_run: str):
    _bind(bench)
    return _frozen_classify_v2(slide_key, run_id, reuse_run)


@app.function(image=modular_image, volumes={"/data": bench, "/raw": slides_volume.read_only()}, cpu=4, memory=16384,
              timeout=7200, max_containers=8)
def sample_slide(row: dict, mode: str = "exhaustive", maps_only: bool = True, max_tiles: int = 0):
    """v2 sampler on one dev slide, resampled to 0.5 um/px; writes inputs-v2/<id>/ on the benchmark volume."""
    import shutil
    import subprocess
    import sys
    import tempfile

    stage = Path(tempfile.mkdtemp()) / "out"
    spec = stage.parent / "spec.json"
    spec.write_text(json.dumps([{"slide_key": row["image_id"], "slide": row["filename"], "source_sha256": row["sha256"],
                                 "candidate_tissue_group": "breast"}]))
    command = [sys.executable, "/opt/repo/scripts/stil_sample_tiles.py", "--slides-spec", str(spec), "--slides-dir", "/raw",
               "--out", str(stage), "--target-mpp", "0.5", "--mode", mode]
    if maps_only:
        command.append("--maps-only")
    if max_tiles:
        command += ["--max-tiles", str(max_tiles)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout[-2000:] + result.stderr[-4000:])
    plan = json.loads((stage / ("sampling_plan.json" if maps_only else "tile_manifest.json")).read_text())
    destination = Path("/data/modular-20261022") / ("sampling-v2-maps" if maps_only else "inputs-v2-staging") / row["image_id"]
    if destination.exists():
        raise FileExistsError(str(destination))
    shutil.copytree(stage, destination)
    bench.commit()
    return {"image_id": row["image_id"], "slide": plan["slides"][0], "tiles": plan["tiles"], "sampling": plan["sampling"]}


@app.function(image=helper_image, volumes={"/data": bench}, timeout=600)
def write_inputs_v2(results: list):
    """Merge per-slide staging folders into inputs-v2/ with one tile manifest."""
    import shutil

    base = Path("/data/modular-20261022")
    out = base / "inputs-v2"
    if (out / "tile_manifest.json").exists():
        raise FileExistsError("inputs-v2 already exists; use a new layout")
    tiles, slides = [], []
    for r in results:
        shutil.copytree(base / "inputs-v2-staging" / r["image_id"] / r["image_id"], out / r["image_id"])
        tiles += r["tiles"]
        slides.append(r["slide"])
    manifest = {"schema_version": 2, "sampling": results[0]["sampling"], "slides": slides, "tiles": tiles, "clinical_stil_percent": None}
    (out / "tile_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    bench.commit()
    return {"slides": len(slides), "tiles": len(tiles), "manifest_sha256": _sha(out / "tile_manifest.json")}


@app.function(image=helper_image, volumes={"/data": components, "/bench": bench.read_only()}, timeout=3600, memory=16384)
def roi_evaluate(run_id: str = ROI_RUN):
    """Stitch v2 ROI outputs, write the agreed per-ROI files, and score them like stil_tiger_components.evaluate."""
    import sys

    import numpy as np
    from PIL import Image
    sys.path.insert(0, "/opt/helpers")
    from stil_benchmark import TIGER_STROMA_LABELS, match_points, tissue_component_dice
    components.reload()
    base = Path("/data/modular-20261022")
    manifest = json.loads((base / "inputs/tile_manifest.json").read_text())
    rois = {r["image_id"]: r for r in json.loads((base / "inputs/rois.json").read_text())}
    by_roi = {}
    for t in manifest["tiles"]:
        by_roi.setdefault(t["roi_image_id"], []).append(t)
    records = []
    for rid, tiles in sorted(by_roi.items()):
        roi = rois[rid]
        ref = np.asarray(Image.open(Path(ROI_DIR, "masks", roi["file_name"])))
        ref = ref[..., 0] if ref.ndim == 3 else ref
        h, w = ref.shape
        labels = np.zeros((h, w), np.uint8)
        immune_pix = np.zeros((h, w), bool)
        cells_out, pts_raw, pts_acc = [], [], []
        status = "ok"
        for t in tiles:
            tdir = base / run_id / t["slide_key"] / t["tile_id"]
            if not (tdir / "classification_summary_v2.json").exists():
                status = "missing_outputs"
                continue
            cx, cy = t["origin_level0_xy"]
            vw, vh = t["core_valid_wh"]
            labels[cy:cy + vh, cx:cx + vw] = np.load(tdir / "tissue_labels_v2.npy")[:vh, :vw]
            inst = np.load(tdir / "nucleus_instances_core.npy")[:vh, :vw]
            immune_ids = []
            for c in json.loads((tdir / "cell_classifications.json").read_text()):
                x, y = c["centroid_level0_xy"]
                if not (cx <= x < cx + vw and cy <= y < cy + vh):
                    continue
                cells_out.append({"x": x, "y": y, "class_name": c["class_name"], "probability": c.get("probability", 0.)})
                if c["class_name"] in ("Lymphocyte", "Plasma_cell"):
                    pts_raw.append((x, y))
                    immune_ids.append(c["instance_id"])
                    if c.get("probability", 0) >= .7:
                        pts_acc.append((x, y))
            immune_pix[cy:cy + vh, cx:cx + vw] |= np.isin(inst, immune_ids)
        rec = {"image_id": rid, "file_name": roi["file_name"], "source": roi["source"], "status": status,
               "n_ref_cells": len(roi["box_centers"]), "annotated_pixels": int((ref > 0).sum())}
        if status == "ok":
            folder = base / run_id / "rois" / str(rid)
            folder.mkdir(parents=True, exist_ok=True)
            Image.fromarray(np.isin(labels, (2, 3)).astype(np.uint8)).save(folder / "stroma_mask.png")
            Image.fromarray((labels == 1).astype(np.uint8)).save(folder / "tumor_mask.png")
            (folder / "cells.json").write_text(json.dumps(cells_out) + "\n")
            rec["dice"] = tissue_component_dice(labels, ref, pred_stroma=(2, 3), pred_tumor=(1,))
            rec["dice_stroma_label_only"] = tissue_component_dice(labels, ref, pred_stroma=(2,), pred_tumor=(1,))["stroma"]
            mpp = roi["mpp"]
            for tag, pts in (("raw", pts_raw), ("accepted_p0.7", pts_acc)):
                rec["detection_" + tag] = {f"{d}um": match_points(pts, roi["box_centers"], d / mpp) for d in (4, 8)}
            stroma = np.isin(ref, TIGER_STROMA_LABELS)
            assessable = np.isin(labels, (2, 3))
            ref_in = sum(1 for x, y in roi["box_centers"] if 0 <= int(y) < h and 0 <= int(x) < w and stroma[int(y), int(x)])
            rec["endpoint"] = {"ref_stroma_um2": float(stroma.sum() * mpp ** 2), "ref_cells_in_ref_stroma": ref_in,
                               "pred_cells_in_ref_stroma": sum(1 for x, y in pts_raw if stroma[int(y), int(x)]),
                               "pred_cells_in_pred_assessable": sum(1 for x, y in pts_raw if assessable[int(y), int(x)]),
                               "pred_immune_nuclear_um2_in_ref_stroma": float((immune_pix & stroma).sum() * mpp ** 2),
                               "pred_immune_nuclear_um2_in_pred_assessable": float((immune_pix & assessable).sum() * mpp ** 2),
                               "pred_assessable_um2": float(assessable.sum() * mpp ** 2)}
        records.append(rec)
    (base / run_id / "component_records.json").write_text(json.dumps(records) + "\n")
    components.commit()
    return records


@app.function(image=helper_image, volumes={"/data": bench}, timeout=600)
def collect(run_id: str):
    """Slide-level rows in the benchmark's schema; no-calls stay as rows."""
    bench.reload()
    rows = []
    for seg in sorted((Path("/data/modular-20261022") / run_id).glob("*/run_manifest.json")):
        s = json.loads(seg.read_text())
        receipt = seg.parent / "classification_manifest.json"
        c = json.loads(receipt.read_text()) if receipt.exists() else {}
        tiles = c.get("tiles", [])
        scored = [t for t in tiles if t["assessable_stroma_pixels"] and t["nuclei"]]
        aggregate = c.get("aggregate") or {}
        value = aggregate.get("assessable_stroma_immune_nuclear_area_percent")
        status = c.get("status") or s.get("status")
        if status == "completed_assessable_stroma_v2" and value is None:
            status = "no_call"
        rows.append({"image_id": s["slide_key"], "status": status,
                     "value_percent": value, "endpoint": "immune (lymphocyte+plasma) nuclear area in VISTA-PATH assessable stroma "
                     "(stroma+immune labels), summed over sampled tiles; not visual sTIL",
                     "n_tiles_scored": len(scored), "n_tiles_no_call": len(tiles) - len(scored),
                     "qc_gates": c.get("qc_gates"), "immune_in_assessable_fraction": aggregate.get("immune_in_assessable_fraction"),
                     "tumor_mask_fraction": aggregate.get("tumor_mask_fraction"),
                     "tumor_nucleus_fraction": aggregate.get("tumor_nucleus_fraction"), "error": c.get("error") or s.get("error")})
    return rows


def _private():
    """private/ is git-ignored, so a worktree has none; use the main checkout's."""
    import subprocess
    if (ROOT / "private").exists():
        return ROOT / "private"
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent / "private"


def _dev_rows(slides):
    split = json.loads((ROOT / "manifests/stil_tiger_benchmark_split.json").read_text())
    dev = {s["image_id"] for s in split["slides"] if s["split"] == "development"}
    locked = {s["image_id"] for s in split["slides"] if s["split"] == "locked_test"}
    rows = json.loads((_private() / "stil/benchmark-20261022/baselines/slide_rows.json").read_text())
    chosen = sorted(dev) if slides == "all" else slides.split(",")
    if set(chosen) & locked or not set(chosen) <= dev:
        raise SystemExit("only development-split slides may be staged or scored")
    by_id = {r["image_id"]: r for r in rows}
    return [by_id[i] for i in chosen]


@app.local_entrypoint()
def main(stage: str = "rois-evaluate", slides: str = "all", mode: str = "exhaustive", maps_only: bool = True,
         max_tiles: int = 0, out: str = "stil/benchmark-20261022/modular-v2"):
    local = _private() / out
    local.mkdir(parents=True, exist_ok=True)

    def save(name, obj):
        (local / name).write_text(json.dumps(obj, indent=1) + "\n")
        print("wrote", local / name)

    def statuses(results):
        return [r.get("status") if isinstance(r, dict) else repr(r)[:200] for r in results]
    if stage.startswith("rois-"):
        keys = json.loads((_private() / "stil/benchmark-20261022/components/modular_prepare.json").read_text())["keys"]
        if stage == "rois-segment":
            print(statuses(roi_segment.map(keys, order_outputs=False, return_exceptions=True)))
        elif stage == "rois-classify":
            print(statuses(roi_classify.map(keys, order_outputs=False, return_exceptions=True)))
        elif stage == "rois-evaluate":
            records = roi_evaluate.remote()
            save("roi_component_records_v2.json", records)
            print(len(records), "ROIs;", sum(r["status"] == "ok" for r in records), "scored")
        else:
            raise SystemExit("unknown stage " + stage)
        return
    rows = _dev_rows(slides)
    if stage == "sample":
        results = list(sample_slide.starmap([(r, mode, maps_only, max_tiles) for r in rows], order_outputs=True))
        save(f"sampling_{'maps' if maps_only else 'tiles'}_{mode}.json",
             [{"image_id": r["image_id"], "tiles": len(r["tiles"]), **{k: r["slide"][k] for k in
              ("eligible_cells", "sampled_tiles", "exclusion_reason_counts", "tissue_mm2_at_map")}} for r in results])
        if not maps_only:
            print(write_inputs_v2.remote(results))
    elif stage == "slides-v1tiles-segment":
        print(statuses(slide_segment.starmap([(r["image_id"], SLIDE_V1TILES_RUN, "inputs", SLIDE_V1_RUN) for r in rows],
                                             order_outputs=False, return_exceptions=True)))
    elif stage == "slides-v1tiles-classify":
        print(statuses(slide_classify_reused.starmap([(r["image_id"], SLIDE_V1TILES_RUN, SLIDE_V1_RUN) for r in rows],
                                                     order_outputs=False, return_exceptions=True)))
    elif stage == "slides-segment":
        print(statuses(slide_segment.starmap([(r["image_id"], SLIDE_RUN, "inputs-v2", SLIDE_V1_RUN) for r in rows],
                                             order_outputs=False, return_exceptions=True)))
    elif stage == "slides-classify":
        print(statuses(slide_classify.starmap([(r["image_id"], SLIDE_RUN, SLIDE_V1_RUN) for r in rows],
                                              order_outputs=False, return_exceptions=True)))
    elif stage == "collect":
        for run_id in (SLIDE_V1TILES_RUN, SLIDE_RUN):
            save(f"collected_{run_id}.json", collect.remote(run_id))
    else:
        raise SystemExit("unknown stage " + stage)
