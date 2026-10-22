"""Step-10 HoVer-Net nuclear-area sTIL approximation on TIGER development slides.

Port of the private step-10 H&E scripts (01 tissue, 02 HoVer-Net x2, 04 colour,
05 aggregate, 06 sTIL) to a Modal GPU worker. The rules and constants are the
step-10 ones; only physical scale is generalized from the hard-coded 0.263089
um/px. Tiles stay 164 um (624 px at 0.263 um/px), HoVer-Net still runs at 0.25
um/px, the tissue mask uses the pyramid level nearest step 10's ~4.2 um/px and
the colour step the level nearest ~1.05 um/px. StarDist is not run; it was a
cross-check, not an input to sTIL. Each slide uses a seeded random sample of at
most 300 tissue tiles (step 10 sampled 325 tiles on one slide).

Endpoint (step-10 `sTIL_pct`): within tumour-bed tiles (>=5 consensus tumour
nuclei), excluding necrosis-suspect and haemorrhage tiles,
100 * 1.5 * sum(lymphocyte nuclear area outside tumour nests) / sum(stromal area).

  modal run scripts/modal/stil_tiger_hovernet.py --slides 129S
  modal run scripts/modal/stil_tiger_hovernet.py --slides all
"""

import json
from pathlib import Path

import modal

app = modal.App("diana-stil-tiger-hovernet")
volume = modal.Volume.from_name("diana-stil-tiger-benchmark", create_if_missing=False)
slides_volume = modal.Volume.from_name("diana-stil-tiger-slides-dev", create_if_missing=False)
image = (modal.Image.debian_slim(python_version="3.11")
         .apt_install("libopenslide0", "libgl1", "libglib2.0-0")
         .pip_install("tiatoolbox==2.1.3", "torch==2.5.1", "torchvision==0.20.1"))
ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else None
roi_image = image.pip_install("pillow==11.1.0")
if modal.is_local():
    roi_image = roi_image.add_local_file(ROOT / "src/diana_omics/stil_benchmark.py", "/opt/helpers/stil_benchmark.py")
ROI_DIR = Path("/tiger/source/wsirois/roi-level-annotations/tissue-cells")
RUN_ID = "tiger-dev-baseline-v2"  # v1 had a centroid-scaling port bug; superseded
MAX_TILES = 300
TILE_UM = 624 * 0.263089


MPP_T, OUTSZ, MARGIN = 0.25, 656, 46


def infer(model, im, dev="cuda"):
    """Step-10 HoVer-Net tile inference: 16 overlapping 256-px patches over a 656-px core (0.25 um/px)."""
    import numpy as np
    import torch
    from scipy import ndimage as ndi
    from tiatoolbox.models.architecture.hovernet import HoVerNet
    patches, pos = [], []
    for py in range(0, OUTSZ, 164):
        for px in range(0, OUTSZ, 164):
            patches.append(im[py:py + 256, px:px + 256])
            pos.append((py, px))
    npm, hv, tp = HoVerNet.infer_batch(model, torch.from_numpy(np.stack(patches)), device=dev)
    NP = np.zeros((OUTSZ, OUTSZ), np.float32)
    HV = np.zeros((OUTSZ, OUTSZ, 2), np.float32)
    TP = np.zeros((OUTSZ, OUTSZ), np.int16)
    for i, (py, px) in enumerate(pos):
        NP[py:py + 164, px:px + 164] = npm[i][..., 0]
        HV[py:py + 164, px:px + 164] = hv[i]
        TP[py:py + 164, px:px + 164] = tp[i][..., 0]
    inst = HoVerNet._proc_np_hv(NP[..., None], HV)
    ids = np.unique(inst)
    ids = ids[ids > 0]
    edge = np.unique(np.concatenate([inst[:, -1], inst[-1, :]]))
    ids = np.setdiff1d(ids, edge)
    if not len(ids):
        return inst, ids, np.zeros((0, 2)), np.zeros(0), np.zeros(0, int)
    area = ndi.sum(np.ones_like(inst), inst, ids) * MPP_T ** 2
    cen = np.array(ndi.center_of_mass(np.ones_like(inst), inst, ids))[:, ::-1]
    mask = np.isin(inst, ids) & (TP > 0)
    lut = np.zeros(inst.max() + 1, int)
    lut[ids] = np.arange(len(ids))
    cnt = np.zeros((len(ids), 7), int)
    np.add.at(cnt, (lut[inst[mask]], TP[mask]), 1)
    typ = np.where(cnt.sum(1) > 0, cnt.argmax(1), 0)
    return inst, ids, cen, area, typ


def consensus(P, Mm):
    import numpy as np
    c = np.full(len(P), "other", dtype=object)
    c[(P == -1) & (Mm == 1)] = "epi_unassigned"
    c[P == 5] = "benign_epi"
    c[P == 1] = "tumor"
    c[P == 2] = "lymph"
    c[P == 4] = "dead"
    c[P == 3] = "stromal"
    c[np.isin(Mm, [3, 4])] = "other_inflam"
    c[Mm == 2] = "lymph"
    return c


def tile_nuclei(models, im_native, mpp):
    """Merged PanNuke x MoNuSAC nuclei for one tile read with margin at native mpp.

    Returns rows (x, y in native core pixels; area um2; PanNuke type; MoNuSAC type).
    0.25-um/px output coordinates map to native pixels by multiplying by MPP_T / mpp.
    """
    import cv2
    import numpy as np
    from scipy.spatial import cKDTree
    sc = MPP_T / mpp
    im = cv2.resize(im_native, (OUTSZ + 2 * MARGIN, OUTSZ + 2 * MARGIN), interpolation=cv2.INTER_AREA)
    instP, idsP, cP, aP, tP = infer(models["pannuke"], im)
    instM, idsM, cM, aM, tM = infer(models["monusac"], im)
    rows = []
    mt = np.full(len(cP), -1)
    usedM = set()
    if len(cP) and len(cM):
        d, j = cKDTree(cM).query(cP, distance_upper_bound=3 / MPP_T)
        ok = np.isfinite(d)
        mt[ok] = tM[j[ok]]
        usedM = set(j[ok])
    for i in range(len(cP)):
        rows.append((cP[i, 0] * sc, cP[i, 1] * sc, aP[i], tP[i], mt[i]))
    for i in range(len(cM)):
        if i in usedM:
            continue
        xx, yy = int(cM[i, 0]), int(cM[i, 1])
        if instP[min(yy, OUTSZ - 1), min(xx, OUTSZ - 1)] > 0:
            continue
        rows.append((cM[i, 0] * sc, cM[i, 1] * sc, aM[i], -1, tM[i]))
    return np.array(rows, np.float32) if rows else np.zeros((0, 5), np.float32)


def load_models(dev="cuda"):
    from tiatoolbox.models.architecture import get_pretrained_model
    return {k: get_pretrained_model(f"hovernet_fast-{k}")[0].to(dev).eval() for k in ("pannuke", "monusac")}


@app.function(image=image, gpu="A10G", cpu=4, memory=24576, timeout=7200,
              volumes={"/tiger": volume, "/raw": slides_volume}, max_containers=6)
def run_slide(row: dict, run_id: str = RUN_ID):
    import time
    import traceback
    import warnings

    import numpy as np
    import openslide
    import pandas as pd
    import torch
    from scipy import ndimage as ndi
    from skimage import color, filters, measure, morphology
    from skimage.transform import resize
    warnings.filterwarnings("ignore")

    out = Path("/tiger/hovernet") / run_id / row["image_id"]
    out.mkdir(parents=True, exist_ok=True)
    receipt_path = out / "run_manifest.json"
    if receipt_path.exists():
        old = json.loads(receipt_path.read_text())
        if old.get("status") == "completed" and old.get("source_sha256") == row["sha256"]:
            return old
    receipt = {"image_id": row["image_id"], "source_sha256": row["sha256"], "status": "running", "started": time.time(),
               "endpoint": "step-10 sTIL_pct: 1.5 x lymphocyte nuclear area outside tumour nests / stromal area, tumour-bed tiles",
               "max_tiles": MAX_TILES, "seed": 20261022}
    try:
        dev = "cuda"
        models = load_models(dev)
        o = openslide.OpenSlide(str(Path("/raw") / row["filename"]))
        mpp = float(o.properties["openslide.mpp-x"])
        T = int(round(TILE_UM / mpp))
        # --- 01 tissue (level nearest 4.21 um/px)
        lvl = int(np.argmin([abs(mpp * d - 0.263089 * 16) for d in o.level_downsamples]))
        ds = o.level_downsamples[lvl]
        img = np.asarray(o.read_region((0, 0), lvl, o.level_dimensions[lvl]).convert("RGB"))
        hsv = color.rgb2hsv(img)
        sat, val = hsv[..., 1], hsv[..., 2]
        t = filters.threshold_otsu(sat[sat > 0.02])
        t = float(max(min(t, 0.15), 0.06))
        m = (sat > t) & (val > 0.15)
        m = morphology.remove_small_objects(morphology.binary_closing(m, morphology.disk(3)), 200)
        m = morphology.remove_small_holes(m, 400)
        lab = measure.label(m, connectivity=2)
        for p in measure.regionprops(lab):
            c = p.coords
            if np.median(val[c[:, 0], c[:, 1]]) < 0.35:
                m[c[:, 0], c[:, 1]] = False
        env = ndi.binary_fill_holes(morphology.binary_closing(m, morphology.disk(6)))
        env = morphology.remove_small_objects(env, 200)
        W, H = o.level_dimensions[0]
        tiles = []
        for y in range(0, H - T, T):
            for x in range(0, W - T, T):
                ys, xs, ye, xe = int(y / ds), int(x / ds), int((y + T) / ds), int((x + T) / ds)
                sub = m[ys:ye, xs:xe]
                f = sub.mean() if sub.size else 0
                if f >= 0.25:
                    tiles.append(dict(tile_id=f"{x}_{y}", x=x, y=y, tissue_frac=float(f)))
        receipt.update(mpp=mpp, tile_px=T, tissue_level=lvl, tissue_level_mpp=mpp * ds, n_tissue_tiles=len(tiles))
        rng = np.random.default_rng(20261022)
        chosen = sorted(rng.choice(len(tiles), min(MAX_TILES, len(tiles)), replace=False)) if tiles else []
        tiles = [tiles[i] for i in chosen]
        # --- 04 colour (level nearest 1.05 um/px)
        lvl1 = int(np.argmin([abs(mpp * d - 0.263089 * 4) for d in o.level_downsamples]))
        ds1 = o.level_downsamples[lvl1]
        mpp1 = mpp * ds1
        recs = []
        sc = MPP_T / mpp
        for r in tiles:
            # colour composition
            sz = int(round(T / ds1))
            im1 = np.asarray(o.read_region((r["x"], r["y"]), lvl1, (sz, sz)).convert("RGB"))
            hsv1 = color.rgb2hsv(im1)
            hed1 = color.rgb2hed(im1)
            white = (hsv1[..., 2] > 0.86) & (hsv1[..., 1] < 0.08)
            h = hsv1[..., 0]
            rbc = (~white) & ((h < 0.03) | (h > 0.93)) & (hsv1[..., 1] > 0.40) & (hed1[..., 1] > 0.02) & (hed1[..., 0] < 0.02)
            e = env[int(r["y"] / ds):int((r["y"] + T) / ds), int(r["x"] / ds):int((r["x"] + T) / ds)]
            eup = resize(e.astype(float), (sz, sz), order=0) > 0.5 if e.size else np.zeros((sz, sz), bool)
            vac = 0.
            for p in measure.regionprops(measure.label(white)):
                a = p.area * mpp1 ** 2
                if 300 < a < 20000 and p.solidity > 0.85 and eup[p.coords[:, 0], p.coords[:, 1]].mean() > 0.9:
                    vac += p.area
            px_rbc, px_vac = rbc.sum() / white.size, vac / white.size
            # HoVer-Net x2 (02)
            m0 = int(round(MARGIN * sc))
            rd = T + 2 * m0
            im = np.asarray(o.read_region((r["x"] - m0, r["y"] - m0), 0, (rd, rd)).convert("RGB"))
            n = tile_nuclei(models, im, mpp)
            np.save(out / f"nuclei_{r['tile_id']}.npy", n)
            # aggregate (05): tumour-nest mask on a 2-um grid, lymphocytes outside nests
            P, Mm = n[:, 3].astype(int), n[:, 4].astype(int)
            c = consensus(P, Mm)
            g = 2.0
            G = int(T * mpp / g)
            xy = n[:, :2] * mpp / g
            tum = np.zeros((G, G), bool)
            tx = xy[c == "tumor"]
            if len(tx):
                ii = np.clip(tx.astype(int), 0, G - 1)
                tum[ii[:, 1], ii[:, 0]] = True
                tum = ndi.binary_dilation(tum, iterations=5)
                tum = ndi.binary_closing(tum, iterations=3)
            lx, la = xy[c == "lymph"], n[c == "lymph", 2]
            if len(lx):
                ii = np.clip(lx.astype(int), 0, G - 1)
                outside = ~tum[ii[:, 1], ii[:, 0]]
                lymph_n, lymph_area = int(outside.sum()), float(la[outside].sum())
            else:
                lymph_n, lymph_area = 0, 0.
            tissue_um2 = r["tissue_frac"] * (T * mpp) ** 2
            counts = {k: int((c == k).sum()) for k in ("tumor", "lymph", "stromal", "other_inflam", "dead", "benign_epi", "epi_unassigned", "other")}
            recs.append(dict(r, px_rbc=float(px_rbc), px_adipocyte_vac=float(px_vac), hv_n=len(n), **{"hv_" + k: v for k, v in counts.items()},
                             tumor_nest_frac=float(tum.mean()), lymph_stromal_n=lymph_n, lymph_stromal_nuc_area_um2=lymph_area,
                             tissue_um2=tissue_um2,
                             stroma_um2=max(tissue_um2 * (1 - float(tum.mean())) - px_vac * (T * mpp) ** 2, 0)))
        tm = pd.DataFrame(recs)
        tm.to_csv(out / "tile_metrics.csv", index=False)
        result = {}
        if len(tm):
            tm["tumor_bed"] = tm.hv_tumor >= 5
            tm["necrosis_suspect"] = (tm.hv_dead >= 10) & (tm.hv_dead / tm.hv_n.clip(lower=1) >= 0.2)
            tm["hemorrhage"] = tm.px_rbc >= 0.3
            bedc = tm[tm.tumor_bed & ~tm.necrosis_suspect & ~tm.hemorrhage]
            for fac, tag in ((1.0, "stil_nuclear_area_only_percent"), (1.5, "stil_nuclear_area_percent"), (2.0, "stil_upper_percent")):
                if len(bedc) and bedc.stroma_um2.sum() > 0:
                    result[tag] = 100 * min(bedc.lymph_stromal_nuc_area_um2.sum() * fac / bedc.stroma_um2.sum(), 1)
            result.update(n_analyzed_tiles=len(tm), n_tumor_bed_tiles=int(tm.tumor_bed.sum()), n_scored_tiles=len(bedc),
                          lymph_nuclei_fraction=float(tm.hv_lymph.sum() / max(tm.hv_n.sum(), 1)))
        status = "completed" if result.get("stil_nuclear_area_percent") is not None else "no_call_no_tumor_bed"
        import importlib.metadata
        versions = {k: importlib.metadata.version(k) for k in ("tiatoolbox", "torch", "numpy", "scipy", "scikit-image", "openslide-python")}
        receipt.update(result, status=status, finished=time.time(), gpu=torch.cuda.get_device_name(0), versions=versions)
    except Exception:
        receipt.update(status="failed", error=traceback.format_exc(), finished=time.time())
    receipt = json.loads(json.dumps(receipt, default=lambda v: v.item() if hasattr(v, "item") else str(v)))
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    volume.commit()
    return receipt


@app.function(image=roi_image, gpu="A10G", cpu=4, memory=24576, timeout=7200, volumes={"/tiger": volume}, max_containers=4)
def run_rois(rois: list, run_id: str = "tiger-rois-baseline-v1"):
    """Step-10 HoVer-Net components on TIGER ROIs: lymphocyte detection and tumour-nest / stroma Dice.

    Each ROI is tiled into 164-um tiles with the step-10 46-px (0.25 um/px) margin;
    pixels outside the ROI are white. Nuclei are kept where their centroid falls in
    the tile core. The tumour-nest mask follows step 05 (2-um grid, 10-um dilation,
    closing); predicted stroma is annotated tissue outside nests.
    """
    import sys

    import numpy as np
    from PIL import Image
    from scipy import ndimage as ndi
    sys.path.insert(0, "/opt/helpers")
    from stil_benchmark import TIGER_STROMA_LABELS, match_points, tissue_component_dice
    models = load_models("cuda")
    records = []
    for roi in rois:
        rgb = np.asarray(Image.open(ROI_DIR / "images" / roi["file_name"]).convert("RGB"))
        ref = np.asarray(Image.open(ROI_DIR / "masks" / roi["file_name"]))
        if ref.ndim == 3:
            ref = ref[..., 0]
        h, w = ref.shape
        mpp = roi["mpp"]
        T = int(round(TILE_UM / mpp))
        m0 = int(round(MARGIN * MPP_T / mpp))
        pad = T + m0
        padded = np.full((h + 2 * pad, w + 2 * pad, 3), 255, np.uint8)
        padded[pad:pad + h, pad:pad + w] = rgb
        nuclei = []
        for y in range(0, h, T):
            for x in range(0, w, T):
                crop = padded[pad + y - m0:pad + y + T + m0, pad + x - m0:pad + x + T + m0]
                n = tile_nuclei(models, crop, mpp)
                for row in n:
                    if 0 <= row[0] < T and 0 <= row[1] < T and x + row[0] < w and y + row[1] < h:
                        nuclei.append((x + row[0], y + row[1], row[2], row[3], row[4]))
        n = np.array(nuclei, np.float32) if nuclei else np.zeros((0, 5), np.float32)
        c = consensus(n[:, 3].astype(int), n[:, 4].astype(int))
        g = 2.0
        gh, gw = int(np.ceil(h * mpp / g)), int(np.ceil(w * mpp / g))
        tum = np.zeros((gh, gw), bool)
        tx = n[c == "tumor", :2] * mpp / g
        if len(tx):
            tum[np.clip(tx[:, 1].astype(int), 0, gh - 1), np.clip(tx[:, 0].astype(int), 0, gw - 1)] = True
            tum = ndi.binary_dilation(tum, iterations=5)
            tum = ndi.binary_closing(tum, iterations=3)
        yy = np.clip((np.arange(h) * mpp / g).astype(int), 0, gh - 1)
        xx = np.clip((np.arange(w) * mpp / g).astype(int), 0, gw - 1)
        nest = tum[yy][:, xx]
        labels = np.where(nest, 1, 2).astype(np.uint8)
        lymph = n[c == "lymph"]
        pts = [(float(a), float(b)) for a, b in lymph[:, :2]]
        stroma = np.isin(ref, TIGER_STROMA_LABELS)
        rec = {"image_id": roi["image_id"], "file_name": roi["file_name"], "source": roi["source"], "status": "ok",
               "n_ref_cells": len(roi["box_centers"]), "n_nuclei": len(n), "annotated_pixels": int((ref > 0).sum()),
               "dice": tissue_component_dice(labels, ref, pred_stroma=(2,), pred_tumor=(1,)),
               "detection_lymph": {f"{d}um": match_points(pts, roi["box_centers"], d / mpp) for d in (4, 8)}}
        in_stroma = [stroma[int(b), int(a)] for a, b in lymph[:, :2]] if len(lymph) else []
        rec["endpoint"] = {"ref_stroma_um2": float(stroma.sum() * mpp ** 2),
                           "ref_cells_in_ref_stroma": sum(1 for a, b in roi["box_centers"] if 0 <= int(b) < h and 0 <= int(a) < w and stroma[int(b), int(a)]),
                           "pred_cells_in_ref_stroma": int(sum(in_stroma)),
                           "pred_lymph_nuclear_um2_in_ref_stroma": float(lymph[np.array(in_stroma, bool), 2].sum()) if len(lymph) else 0.,
                           "median_lymph_nuclear_um2": float(np.median(lymph[:, 2])) if len(lymph) else None}
        records.append(rec)
    out = Path("/tiger/hovernet") / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / f"rois_{rois[0]['image_id']:05d}.json").write_text(json.dumps(records) + "\n")
    volume.commit()
    return records


@app.local_entrypoint()
def main(slides: str = "all", run_id: str = RUN_ID, out: str = "private/stil/benchmark-20261022/baselines", rois: bool = False):
    if rois:
        import random
        import sys
        sys.path.insert(0, str(ROOT / "src"))
        from diana_omics.stil_benchmark import select_component_rois
        coco_path = Path(out).parent / "components" / "tiger-coco.json"
        selected = select_component_rois(json.loads(coco_path.read_text()))
        random.Random(0).shuffle(selected)
        batches = [selected[i::12] for i in range(12)]
        records = [r for batch in run_rois.map(batches, order_outputs=False) for r in batch]
        Path(out).parent.joinpath("components", "hovernet_component_records.json").write_text(json.dumps(records, indent=1) + "\n")
        print(len(records), "ROIs scored")
        return
    split = json.loads((ROOT / "manifests/stil_tiger_benchmark_split.json").read_text())
    dev = sorted(s["image_id"] for s in split["slides"] if s["split"] == "development")
    chosen = dev if slides == "all" else slides.split(",")
    assert set(chosen) <= set(dev), "baselines run on development slides only"
    rows = {r["image_id"]: r for r in json.loads(Path(out, "slide_rows.json").read_text())}
    results = []
    for r in run_slide.map([rows[i] for i in chosen], [run_id] * len(chosen), order_outputs=False):
        results.append(r)
        print(r["image_id"], r["status"], r.get("stil_nuclear_area_percent"), flush=True)
    path = Path(out) / "hovernet_slides.json"
    existing = {r["image_id"]: r for r in json.loads(path.read_text())} if path.exists() else {}
    existing.update({r["image_id"]: r for r in results})
    path.write_text(json.dumps(sorted(existing.values(), key=lambda r: r["image_id"]), indent=2) + "\n")
