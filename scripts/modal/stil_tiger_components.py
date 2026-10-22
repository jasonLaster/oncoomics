"""Component checks of the committed modular runner on TIGER wsirois ROIs.

Runs the frozen `segment` / `classify` stages from scripts/modal/stil_modular_execute.py
(commit a1764b5a) on 1152-px tiles cut from the selected ROIs (all RUMC/JB plus a
seeded TCGA sample; see diana_omics.stil_benchmark.select_component_rois), then
scores per ROI:

- VISTA-PATH tumor/stroma Dice against TIGER labels. VISTA-PATH was trained on TIGER
  wsirois, so these values are reported as contaminated and excluded from metrics.
- Lymphocyte + plasma-cell detection (Cellpose 3 + CytoFormer) against TIGER box
  centers at 4 um (primary) and 8 um.
- Immune nuclear area in reference stroma, and reference cell density, to separate
  conversion from detection error.

ROI pixels outside the ROI are white; inference context near ROI edges is reduced.

  modal run scripts/modal/stil_tiger_components.py --stage prepare
  modal run scripts/modal/stil_tiger_components.py --stage run
  modal run scripts/modal/stil_tiger_components.py --stage evaluate
"""

import ast
import hashlib
import json
from pathlib import Path

import modal

FROZEN_NAME = "stil_modular_execute_a1764b5a.py"
FROZEN_SHA256 = "e443489e76a3588dfc7788d6d1b81e60f14593828bcbe1030c1d737d28ad56fd"
ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else None
FROZEN_DIR = (ROOT / ".runs/stil-tiger-benchmark/frozen") if modal.is_local() else Path("/opt/frozen")
RUN_ID = "tiger-rois-baseline-v1"
ROI_DIR = "/bench/source/wsirois/roi-level-annotations/tissue-cells"
TILES_PER_KEY = 40

app = modal.App("diana-stil-tiger-components")
volume = modal.Volume.from_name("diana-stil-tiger-components", create_if_missing=True)
bench = modal.Volume.from_name("diana-stil-tiger-benchmark", create_if_missing=False)


def _exec_frozen():
    source = (FROZEN_DIR / FROZEN_NAME).read_bytes()
    if hashlib.sha256(source).hexdigest() != FROZEN_SHA256:
        raise RuntimeError("frozen modular runner hash mismatch")
    tree = ast.parse(source.decode())
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "image" for t in node.targets) or isinstance(node, ast.If):
            body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in ("digest", "segment", "classify"):
            node.decorator_list = []
            body.append(node)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(FROZEN_DIR / FROZEN_NAME), "exec"), globals())


_exec_frozen()
modular_image = image  # noqa: F821
helper_image = modal.Image.debian_slim(python_version="3.11").pip_install("numpy==1.26.4", "pillow==11.1.0")
if modal.is_local():
    modular_image = modular_image.add_local_dir(FROZEN_DIR, "/opt/frozen").add_local_file(
        ROOT / "src/diana_omics/stil_benchmark.py", "/opt/helpers/stil_benchmark.py")
    helper_image = helper_image.add_local_dir(FROZEN_DIR, "/opt/frozen").add_local_file(
        ROOT / "src/diana_omics/stil_benchmark.py", "/opt/helpers/stil_benchmark.py")

segment = app.function(image=modular_image, volumes={"/data": volume}, gpu="A10G", cpu=4, memory=32768,
                       timeout=7200, max_containers=4)(segment)  # noqa: F821
classify = app.function(image=modular_image, volumes={"/data": volume}, gpu="A100-40GB", cpu=4, memory=32768,
                        timeout=14400, max_containers=2)(classify)  # noqa: F821


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@app.function(image=helper_image, volumes={"/data": volume, "/bench": bench.read_only()}, timeout=3600, memory=8192)
def prepare(seed: int = 20261022, n_tcga: int = 200):
    import shutil
    import sys

    import numpy as np
    from PIL import Image
    sys.path.insert(0, "/opt/helpers")
    from stil_benchmark import select_component_rois
    src, dst = Path("/bench/models/modular-20261022"), Path("/data/models/modular-20261022")
    if not dst.exists():
        shutil.copytree(src, dst)
    coco = json.loads(Path(ROI_DIR, "tiger-coco.json").read_text())
    rois = select_component_rois(coco, seed=seed, n_tcga=n_tcga)
    out = Path("/data/modular-20261022/inputs")
    tiles, counters = [], {}
    for roi in rois:
        rgb = np.asarray(Image.open(Path(ROI_DIR, "images", roi["file_name"])).convert("RGB"))
        h, w = rgb.shape[:2]
        assert (w, h) == (roi["width"], roi["height"]), roi["file_name"]
        for cy in range(0, h, 1024):
            for cx in range(0, w, 1024):
                n = counters.get(roi["source"], 0)
                counters[roi["source"]] = n + 1
                key = f"roi_{roi['source']}_{n // TILES_PER_KEY:02d}"
                canvas = np.full((1152, 1152, 3), 255, np.uint8)
                x0, y0 = max(cx - 64, 0), max(cy - 64, 0)
                x1, y1 = min(cx + 1088, w), min(cy + 1088, h)
                canvas[y0 - (cy - 64):y1 - (cy - 64), x0 - (cx - 64):x1 - (cx - 64)] = rgb[y0:y1, x0:x1]
                tile_id = f"r{roi['image_id']:04d}_x{cx:05d}_y{cy:05d}"
                folder = out / key
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / (tile_id + ".png")
                Image.fromarray(canvas).save(path)
                tiles.append({"tile_id": tile_id, "slide_key": key, "slide": roi["file_name"], "roi_image_id": roi["image_id"],
                              "source_sha256": _sha(Path(ROI_DIR, "images", roi["file_name"])), "image_path": str(path.relative_to(out)),
                              "image_sha256": _sha(path), "halo_pixels": 64, "origin_level0_xy": [cx, cy],
                              "mpp_xy": [roi["mpp"], roi["mpp"]], "core_shape_yx": [1024, 1024],
                              "core_valid_wh": [min(1024, w - cx), min(1024, h - cy)], "candidate_tissue_group": "breast",
                              "roi_source": roi["source"], "annotation_reviewed": False, "clinical_stil_percent": None})
    manifest = {"schema_version": 1, "sampling": {"method": "all selected TIGER wsirois ROIs tiled into 1024-px cores, white outside ROI",
                                                   "seed": seed, "n_tcga": n_tcga}, "slides": [], "tiles": tiles}
    (out / "tile_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "rois.json").write_text(json.dumps(rois) + "\n")
    volume.commit()
    return {"rois": len(rois), "tiles": len(tiles), "keys": sorted({t["slide_key"] for t in tiles}),
            "by_source": {s: sum(r["source"] == s for r in rois) for s in ("TCGA", "RUMC", "JB")}}


@app.function(image=helper_image, volumes={"/data": volume, "/bench": bench.read_only()}, timeout=3600, memory=16384)
def evaluate(run_id: str = RUN_ID):
    import sys

    import numpy as np
    from PIL import Image
    sys.path.insert(0, "/opt/helpers")
    from stil_benchmark import TIGER_STROMA_LABELS, match_points, tissue_component_dice
    volume.reload()
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
        if ref.ndim == 3:
            ref = ref[..., 0]
        h, w = ref.shape
        labels = np.zeros((h, w), np.uint8)
        immune_pix = np.zeros((h, w), bool)
        pts_raw, pts_acc = [], []
        status = "ok"
        for t in tiles:
            tdir = base / run_id / t["slide_key"] / t["tile_id"]
            cls_path = tdir / "cell_classifications.json"
            if not cls_path.exists():
                status = "missing_outputs"
                continue
            cx, cy = t["origin_level0_xy"]
            vw, vh = t["core_valid_wh"]
            labels[cy:cy + vh, cx:cx + vw] = np.load(tdir / "tissue_labels.npy")[:vh, :vw]
            inst = np.load(tdir / "nucleus_instances_core.npy")[:vh, :vw]
            cells = json.loads(cls_path.read_text())
            immune_ids = []
            for c in cells:
                x, y = c["centroid_level0_xy"]
                if not (cx <= x < cx + vw and cy <= y < cy + vh):
                    continue
                if c.get("class_name") in ("Lymphocyte", "Plasma_cell"):
                    pts_raw.append((x, y))
                    immune_ids.append(c["instance_id"])
                    if c.get("probability", 0) >= .7:
                        pts_acc.append((x, y))
            immune_pix[cy:cy + vh, cx:cx + vw] |= np.isin(inst, immune_ids)
        rec = {"image_id": rid, "file_name": roi["file_name"], "source": roi["source"], "status": status,
               "n_ref_cells": len(roi["box_centers"]), "annotated_pixels": int((ref > 0).sum())}
        if status == "ok":
            rec["dice"] = tissue_component_dice(labels, ref, pred_stroma=(2,), pred_tumor=(1,))
            mpp = roi["mpp"]
            for tag, pts in (("raw", pts_raw), ("accepted_p0.7", pts_acc)):
                rec["detection_" + tag] = {f"{d}um": match_points(pts, roi["box_centers"], d / mpp) for d in (4, 8)}
            stroma = np.isin(ref, TIGER_STROMA_LABELS)
            ref_in_stroma = sum(1 for x, y in roi["box_centers"] if 0 <= int(y) < h and 0 <= int(x) < w and stroma[int(y), int(x)])
            pred_in_stroma = sum(1 for x, y in pts_raw if stroma[int(y), int(x)])
            rec["endpoint"] = {"ref_stroma_um2": float(stroma.sum() * mpp ** 2), "ref_cells_in_ref_stroma": ref_in_stroma,
                               "pred_cells_in_ref_stroma": pred_in_stroma,
                               "pred_immune_nuclear_um2_in_ref_stroma": float((immune_pix & stroma).sum() * mpp ** 2),
                               "pred_stroma_um2": float((labels == 2).sum() * mpp ** 2)}
        records.append(rec)
    (base / run_id / "component_records.json").write_text(json.dumps(records) + "\n")
    volume.commit()
    return records


@app.local_entrypoint()
def main(stage: str = "prepare", run_id: str = RUN_ID, out: str = "private/stil/benchmark-20261022/components"):
    local = Path(out)
    local.mkdir(parents=True, exist_ok=True)
    if stage == "prepare":
        result = prepare.remote()
        (local / "modular_prepare.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
    elif stage == "run":
        keys = json.loads((local / "modular_prepare.json").read_text())["keys"]
        seg = list(segment.starmap([(k, 0, run_id) for k in keys], order_outputs=False, return_exceptions=True))
        print("segmentation", [s.get("status") if isinstance(s, dict) else repr(s)[:200] for s in seg], flush=True)
        done = [s["slide_key"] for s in seg if isinstance(s, dict) and s.get("status") == "completed_two_components"]
        cls = list(classify.starmap([(k, run_id) for k in done], order_outputs=False, return_exceptions=True))
        print("classification", [c.get("status") if isinstance(c, dict) else repr(c)[:200] for c in cls], flush=True)
    elif stage == "evaluate":
        records = evaluate.remote(run_id)
        (local / "modular_component_records.json").write_text(json.dumps(records, indent=1) + "\n")
        print(len(records), "ROIs;", sum(r["status"] == "ok" for r in records), "scored")
    else:
        raise SystemExit("unknown stage")
