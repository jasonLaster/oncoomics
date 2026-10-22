"""Pinned modular H&E research pilot on private Modal storage."""

from pathlib import Path

import modal

app = modal.App("diana-stil-modular-20261022")
volume = modal.Volume.from_name("diana-stil-pilot-20261021", create_if_missing=False)
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libopenslide0", "libvips-dev", "git", "build-essential")
    .pip_install("torch==2.5.1", "torchvision==0.20.1", "openslide-python==1.4.2",
                 "pillow==11.1.0", "numpy==1.26.4", "scipy==1.14.1",
                 "scikit-image==0.24.0", "dlup==0.3.23", "pyvips==2.2.3")
    .pip_install("transformers==4.46.1", "tokenizers==0.20.3", "huggingface-hub==0.36.2",
                 "accelerate==0.26.0", "safetensors==0.4.5", "timm==1.0.9",
                 "cellpose==3.1.1.1", "opencv-python-headless==4.10.0.84",
                 "pandas==2.2.3", "pyarrow==19.0.1", "numba==0.61.2", "numpy==2.0.2")
    .env({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
          "CELLPOSE_LOCAL_MODELS_PATH": "/data/models/modular-20261022/cellpose",
          "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"})
)
if modal.is_local():
    project = Path(__file__).resolve().parents[2]
    image = image.add_local_dir(
        project / ".runs/stil-modular-20261022/vendor/VISTA-PATH", "/opt/vista",
        ignore=[".git", "figures", "examples", "VISTA-PATH_data", "notebook", "checkpoints"],
    ).add_local_dir(
        project / ".runs/stil-modular-20261022/vendor/CytoFormer/cytoformer", "/opt/cytoformer/cytoformer",
    )


def digest(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@app.function(image=image, volumes={"/data": volume}, timeout=1800, memory=8192)
def provision():
    import importlib.metadata
    import json

    from cellpose import models

    root = Path("/data/models/modular-20261022")
    root.mkdir(parents=True, exist_ok=True)
    model = models.CellposeModel(gpu=False, model_type="nuclei")
    receipt = {
        "status": "cellpose_asset_prepared", "checkpoint": model.pretrained_model,
        "checkpoint_sha256": digest(model.pretrained_model),
        "versions": {name: importlib.metadata.version(name) for name in
                     ("torch", "torchvision", "transformers", "cellpose", "timm", "numpy", "scikit-image")},
    }
    (root / "cellpose_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    volume.commit()
    return receipt


@app.function(image=image, volumes={"/data": volume}, gpu="A10G", cpu=4, memory=32768,
              timeout=7200, max_containers=2)
def segment(slide_key: str, limit: int = 0, run_id: str = "development-v1"):
    import gc
    import json
    import sys
    import time
    import traceback
    from types import SimpleNamespace

    import cv2
    import numpy as np
    import torch
    from PIL import Image, ImageDraw
    from skimage.color import rgb2hed
    from skimage.filters import threshold_otsu
    from skimage.measure import regionprops
    from skimage.segmentation import find_boundaries
    from transformers import AutoImageProcessor, CLIPProcessor

    base = Path("/data/modular-20261022")
    asset_root = Path("/data/models/modular-20261022")
    source = json.loads((base / "inputs/tile_manifest.json").read_text())
    rows = [row for row in source["tiles"] if row["slide_key"] == slide_key]
    if limit:
        rows = rows[:limit]
    if not rows:
        raise ValueError("no input tiles for " + slide_key)
    destination = base / run_id / slide_key
    destination.mkdir(parents=True, exist_ok=True)
    receipt_path = destination / "run_manifest.json"
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text())
        if (previous.get("status") == "completed_two_components"
                and previous.get("requested_tiles") == len(rows)
                and previous.get("tile_manifest_sha256") == digest(base / "inputs/tile_manifest.json")
                and all(digest(destination / a["path"]) == a["sha256"] for a in previous["artifacts"])):
            return {k: v for k, v in previous.items() if k not in ("tiles", "artifacts")}
        raise FileExistsError("existing segmentation run; use a new run ID")
    receipt = {
        "status": "running", "stage": "preflight", "slide_key": slide_key,
        "source_sha256": rows[0]["source_sha256"], "tile_manifest_sha256": digest(base / "inputs/tile_manifest.json"),
        "requested_tiles": len(rows), "processed_tiles": 0, "started_utc_seconds": time.time(),
        "clinical_stil_percent": None, "pathologist_score": None,
        "eligibility_annotation_status": "not_reviewed", "CytoFormer_status": "not_run_in_segmentation_stage",
        "sampling": source["sampling"], "tiles": [],
    }
    def save():
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        volume.commit()
    try:
        lock = json.loads((asset_root / "asset_manifest.json").read_text())
        for asset in lock:
            path = asset_root / asset["relative_path"]
            if digest(path) != asset["sha256"]:
                raise ValueError("model asset hash mismatch: " + str(path))
        cp_receipt = json.loads((asset_root / "cellpose_receipt.json").read_text())
        if digest(cp_receipt["checkpoint"]) != cp_receipt["checkpoint_sha256"]:
            raise ValueError("Cellpose asset hash mismatch")
        receipt["cellpose"] = cp_receipt
        receipt["asset_manifest_sha256"] = digest(asset_root / "asset_manifest.json")
        receipt["execution_script_sha256"] = digest(__file__)
        sys.path.insert(0, "/opt/vista")
        import inference_utils as vista
        vista.BASE_MODEL_NAME = str(asset_root / "vinid--plip")
        vista.MASK2FORMER_NAME = str(asset_root / "facebook--mask2former-swin-small-ade-semantic")
        vista.SAM_PRETRAINED = str(asset_root / "facebook--sam-vit-base")
        vista.set_seed(42)
        torch.set_num_threads(4)
        device = torch.device("cuda")
        args = SimpleNamespace(checkpoint_file=str(asset_root / "VISTA-PATH/pytorch_model.bin"),
                               d_model=512, nhead=8, num_layers=4, bbx_random=1., tune_mode="freeze",
                               num_queries=20, m2f_image_size=512)
        model = vista.load_model(args, device)
        processor = CLIPProcessor.from_pretrained(vista.BASE_MODEL_NAME)
        m2f_processor = AutoImageProcessor.from_pretrained(vista.MASK2FORMER_NAME,
                        do_resize=False, do_reduce_labels=False, ignore_index=255)
        prompts = vista.encode_class_texts(processor, {1: "Tumor", 2: "Stroma"}, [1, 2])
        receipt.update(stage="stroma", VISTA_checkpoint_strict_load=True,
                       adapter_configuration={"class_names": ["Tumor", "Stroma"], "text_template": vista.TEXT_TEMPLATE,
                       "input_size": 512, "core_pixels": 1024, "box_prompt": False,
                       "threshold": "native Otsu per class on each ROI; not global whole-slide Otsu",
                       "merge": "native larger-area-first and smaller-area-last",
                       "nucleus_preprocessing": "hematoxylin optical density, percentile 1 to 99.8, clipped [0,1]",
                       "nucleus_diameter_um": 8, "nucleus_halo_pixels": 64,
                       "scope": "sampled unreviewed ROIs; not whole slide"})
        save()
        for row in rows:
            tile_dir = destination / row["tile_id"]
            tile_dir.mkdir(exist_ok=True)
            image_path = base / "inputs" / row["image_path"]
            if digest(image_path) != row["image_sha256"]:
                raise ValueError("input image hash mismatch")
            rgb = np.asarray(Image.open(image_path).convert("RGB"))
            halo = row["halo_pixels"]
            core = rgb[halo:halo+1024, halo:halo+1024]
            foreground = (core.max(2).astype(float) - core.min(2) > 20) & (core.mean(2) < 235)
            pixel = m2f_processor(images=cv2.resize(core, (512, 512), interpolation=cv2.INTER_LINEAR),
                                  return_tensors="pt")["pixel_values"].to(device)
            probabilities, components, thresholds = {}, [], {}
            with torch.inference_mode():
                for idx, name in ((1, "Tumor"), (2, "Stroma")):
                    ids, attention = prompts[idx]
                    output = model(pixel, ids.unsqueeze(0).to(device), attention.unsqueeze(0).to(device), box=None)
                    probability = torch.softmax(output["logits"], 1)[0, 1].cpu().numpy()
                    probability = cv2.resize(probability, (1024, 1024), interpolation=cv2.INTER_LINEAR)
                    probability[~foreground] = 0
                    threshold = float(threshold_otsu(probability[::2, ::2])) if np.ptp(probability) > 0 else .5
                    binary = (probability >= threshold) & foreground
                    probabilities[name] = probability.astype(np.float16)
                    components.append((idx, binary, int(binary.sum())))
                    thresholds[name] = threshold
            merged = np.zeros((1024, 1024), np.uint8)
            for idx, binary, _ in sorted(components, key=lambda item: -item[2]):
                merged[binary] = idx
            np.save(tile_dir / "tissue_labels.npy", merged)
            np.savez_compressed(tile_dir / "tissue_probabilities.npz", **probabilities)
            summary = dict(row, thresholds=thresholds, predicted_stromal_pixels=int((merged == 2).sum()),
                           predicted_tumor_pixels=int((merged == 1).sum()), eligibility_reviewed=False)
            (tile_dir / "tile_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            receipt["tiles"].append(summary)
        del model, pixel, output
        gc.collect()
        torch.cuda.empty_cache()
        from cellpose import models
        nuclei_model = models.CellposeModel(gpu=True, pretrained_model=cp_receipt["checkpoint"])
        receipt["stage"] = "nuclei"
        save()
        for summary in receipt["tiles"]:
            tile_dir = destination / summary["tile_id"]
            rgb = np.asarray(Image.open(base / "inputs" / summary["image_path"]).convert("RGB"))
            hema = rgb2hed(rgb)[..., 0]
            low, high = np.percentile(hema, [1, 99.8])
            hema = np.clip((hema-low) / max(high-low, 1e-8), 0, 1).astype(np.float32)
            masks, _, _ = nuclei_model.eval(hema, diameter=8 / summary["mpp_xy"][0], channels=[0, 0],
                                           normalize=False, flow_threshold=.4, cellprob_threshold=0.)
            halo = summary["halo_pixels"]
            core_masks = masks[halo:halo+1024, halo:halo+1024].astype(np.int32)
            np.save(tile_dir / "nucleus_instances_halo.npy", masks.astype(np.int32))
            np.save(tile_dir / "nucleus_instances_core.npy", core_masks)
            core_ids = set(np.unique(core_masks)) - {0}
            cells = []
            for prop in regionprops(masks):
                if prop.label not in core_ids:
                    continue
                y, x = prop.centroid
                cells.append({"instance_id": int(prop.label), "centroid_halo_xy": [float(x), float(y)],
                              "centroid_level0_xy": [summary["origin_level0_xy"][0]+x-halo,
                                                       summary["origin_level0_xy"][1]+y-halo],
                              "nuclear_area_pixels_halo": int(prop.area),
                              "classification_status": "not_run_in_segmentation_stage"})
            (tile_dir / "nuclei.json").write_text(json.dumps(cells, indent=2) + "\n")
            labels = np.load(tile_dir / "tissue_labels.npy")
            core = rgb[halo:halo+1024, halo:halo+1024].copy()
            colored = core.copy()
            for label, color in ((1, np.array([220, 100, 90])), (2, np.array([70, 170, 190]))):
                match = labels == label
                colored[match] = (.55 * colored[match] + .45 * color).astype(np.uint8)
            boundaries = core.copy()
            boundaries[find_boundaries(core_masks)] = [40, 210, 100]
            canvas = Image.new("RGB", (1152, 414), "white")
            for i, (array, name) in enumerate(((core, "Source H&E"), (colored, "Predicted tumor / stroma"), (boundaries, "Nucleus boundaries"))):
                canvas.paste(Image.fromarray(array).resize((384, 384)), (i*384, 30))
                ImageDraw.Draw(canvas).text((i*384+8, 8), name, fill="black")
            canvas.save(tile_dir / "review.png")
            summary.update(nuclei_intersecting_core=len(cells), nuclear_pixels_in_predicted_stroma=int(((core_masks > 0) & (labels == 2)).sum()))
            (tile_dir / "tile_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            receipt["processed_tiles"] += 1
            print(slide_key, receipt["processed_tiles"], "/", len(rows), "tiles;", len(cells), "nuclei", flush=True)
            save()
        receipt.update(status="completed_two_components", stage="awaiting_cell_classification",
                       finished_utc_seconds=time.time(),
                       total_nuclei=sum(t["nuclei_intersecting_core"] for t in receipt["tiles"]),
                       clinical_stil_percent=None, immune_nuclear_area_proxy_percent=None,
                       artifacts=[{"path": str(p.relative_to(destination)), "bytes": p.stat().st_size, "sha256": digest(p)}
                                  for p in sorted(destination.rglob("*")) if p.is_file() and p != receipt_path])
    except Exception:
        receipt.update(status="failed", error=traceback.format_exc(), finished_utc_seconds=time.time())
    save()
    return {k: v for k, v in receipt.items() if k not in ("tiles", "artifacts")}


@app.function(image=image, volumes={"/data": volume}, gpu="A100-40GB", cpu=4, memory=32768,
              timeout=14400, max_containers=2)
def classify(slide_key: str, run_id: str = "development-v1", batch_size: int = 64):
    import importlib.metadata
    import json
    import sys
    import time
    import traceback

    import cv2
    import numpy as np
    import torch
    from PIL import Image

    base = Path("/data/modular-20261022")
    root = base / run_id / slide_key
    assets = Path("/data/models/modular-20261022/CytoFormer")
    receipt = {"status": "running", "stage": "cell_classification", "slide_key": slide_key,
               "started_utc_seconds": time.time(), "clinical_stil_percent": None,
               "eligibility_annotation_status": "not_reviewed", "processed_tiles": 0, "tiles": []}
    receipt_path = root / "classification_manifest.json"
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text())
        if (previous.get("status") == "completed_experimental_comparison"
                and previous.get("segmentation_manifest_sha256") == digest(root / "run_manifest.json")
                and all(digest(root / a["path"]) == a["sha256"] for a in previous["artifacts"])):
            return {k: v for k, v in previous.items() if k not in ("tiles", "artifacts")}
        raise FileExistsError("existing classification run; use a new run ID")
    def save():
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        volume.commit()
    try:
        segmentation = json.loads((root / "run_manifest.json").read_text())
        if segmentation["status"] != "completed_two_components":
            raise ValueError("segmentation not complete")
        for artifact in segmentation["artifacts"]:
            if digest(root / artifact["path"]) != artifact["sha256"]:
                raise ValueError("segmentation artifact changed: " + artifact["path"])
        if digest(assets / "checkpoint.pth") != "e93362f4e894cad5d02cf72d944702f7fd9b95b5fc25eedf01406adf1c7b7ead":
            raise ValueError("CytoFormer checkpoint hash mismatch")
        receipt.update(source_sha256=segmentation["source_sha256"],
                       execution_script_sha256=digest(__file__),
                       segmentation_manifest_sha256=digest(root / "run_manifest.json"),
                       checkpoint_sha256=digest(assets / "checkpoint.pth"),
                       taxonomy_sha256=digest(assets / "organ_celltype_map.json"),
                       field_of_view_um=56, input_pixels=224, probability_rejection_threshold=.7,
                       probability_threshold_status="development_heuristic_not_calibrated",
                       organ_head="lymph_node" if segmentation["tiles"][0]["candidate_tissue_group"] == "axillary_sentinel_node" else "breast",
                       organ_assignment_status="provisional_specimen_mapping")
        receipt["runtime_versions"] = {name: importlib.metadata.version(name) for name in
                                      ("torch", "torchvision", "transformers", "timm", "numpy", "pillow", "opencv-python-headless")}
        receipt["upstream_code_sha256"] = {name: digest(Path("/opt/cytoformer/cytoformer") / name)
                                          for name in ("model.py", "common.py", "organ_celltype_map.json")}
        import os
        os.environ["CYTOFORMER_ORGAN_MAP"] = str(assets / "organ_celltype_map.json")
        sys.path.insert(0, "/opt/cytoformer")
        from cytoformer import common
        from cytoformer.model import CellClassifier
        torch.set_num_threads(4)
        net = CellClassifier()
        checkpoint = torch.load(assets / "checkpoint.pth", map_location="cpu", weights_only=True)
        net.load_state_dict(checkpoint, strict=True)
        del checkpoint
        device = torch.device("cuda")
        receipt["gpu"] = torch.cuda.get_device_name(0)
        net.eval().to(device)
        receipt["checkpoint_strict_load"] = True
        mean = torch.tensor(common.IMAGENET_NORM[0], device=device).view(1, 3, 1, 1)
        std = torch.tensor(common.IMAGENET_NORM[1], device=device).view(1, 3, 1, 1)
        organ = common.ORGAN_IDX[receipt["organ_head"]]
        immune_indices = [common.CLASS_IDX[name] for name in ("Lymphocyte", "Plasma_cell")]
        save()
        for tile in segmentation["tiles"]:
            tile_dir = root / tile["tile_id"]
            rgb = np.asarray(Image.open(base / "inputs" / tile["image_path"]).convert("RGB"))
            if digest(base / "inputs" / tile["image_path"]) != tile["image_sha256"]:
                raise ValueError("classification input image changed")
            cells = json.loads((tile_dir / "nuclei.json").read_text())
            half = max(8, int(round(28 / tile["mpp_xy"][0])))
            rows, crops = [], []
            for cell in cells:
                x, y = [int(round(v)) for v in cell["centroid_halo_xy"]]
                entry = {"instance_id": cell["instance_id"], "centroid_level0_xy": cell["centroid_level0_xy"]}
                if x-half < 0 or y-half < 0 or x+half > rgb.shape[1] or y+half > rgb.shape[0]:
                    entry.update(class_name="Unknown", probability=0., rejection_reason="context_exceeds_saved_halo")
                else:
                    entry["inference_index"] = len(crops)
                    crops.append(cv2.resize(rgb[y-half:y+half, x-half:x+half], (224, 224), interpolation=cv2.INTER_AREA))
                rows.append(entry)
            probabilities = []
            with torch.inference_mode():
                for start in range(0, len(crops), batch_size):
                    array = np.stack(crops[start:start+batch_size])
                    tensor = torch.from_numpy(array).to(device).permute(0, 3, 1, 2).float().div_(255)
                    tensor = (tensor-mean) / std
                    ids = torch.full((len(array),), organ, dtype=torch.long, device=device)
                    with torch.autocast("cuda", dtype=torch.bfloat16):
                        logits = net(tensor, ids).float()
                    probabilities.append(torch.softmax(logits, 1).cpu().numpy())
            values = np.concatenate(probabilities) if probabilities else np.empty((0, len(common.GLOBAL_CLASSES)))
            if not np.isfinite(values).all():
                raise ValueError("nonfinite classification probabilities")
            for entry in rows:
                if "inference_index" in entry:
                    p = values[entry.pop("inference_index")]
                    idx = int(p.argmax())
                    entry.update(class_name=common.GLOBAL_CLASSES[idx], probability=float(p[idx]),
                                 immune_probability=float(p[immune_indices].sum()))
            labels = np.load(tile_dir / "tissue_labels.npy")
            native_probabilities = np.load(tile_dir / "tissue_probabilities.npz")
            tumor_probability, stroma_probability = native_probabilities["Tumor"], native_probabilities["Stroma"]
            competition = np.where(stroma_probability > tumor_probability, 2,
                                   np.where(tumor_probability > stroma_probability, 1, 0)).astype(np.uint8)
            competition[np.maximum(tumor_probability, stroma_probability) < .5] = 0
            np.save(tile_dir / "tissue_labels_competition.npy", competition)
            instances = np.load(tile_dir / "nucleus_instances_core.npy")
            stroma = labels == 2
            stromal_pixels = int(stroma.sum())
            immune_ids = [r["instance_id"] for r in rows if r["class_name"] in ("Lymphocyte", "Plasma_cell")]
            raw_immune = int((np.isin(instances, immune_ids) & stroma).sum())
            sensitivity = {}
            for threshold in (0., .5, .7, .9):
                accepted = [r["instance_id"] for r in rows if r["class_name"] in ("Lymphocyte", "Plasma_cell") and r["probability"] >= threshold]
                rejected = [r["instance_id"] for r in rows if r["class_name"] == "Unknown" or r["probability"] < threshold]
                sensitivity[str(threshold)] = {
                    "immune_nuclear_pixels": int((np.isin(instances, accepted) & stroma).sum()),
                    "unresolved_nuclear_pixels": int((np.isin(instances, rejected) & stroma).sum()),
                }
            (tile_dir / "cell_classifications.json").write_text(json.dumps(rows, indent=2) + "\n")
            np.savez_compressed(tile_dir / "class_probabilities.npz", probabilities=values,
                                instance_ids=np.array([r["instance_id"] for r in rows if r["class_name"] != "Unknown"]),
                                classes=np.array(common.GLOBAL_CLASSES))
            summary = {"tile_id": tile["tile_id"], "predicted_stromal_pixels": stromal_pixels,
                       "raw_immune_nuclear_pixels": raw_immune, "classified_nuclei": len(rows),
                       "sensitivity": sensitivity, "clinical_stil_percent": None,
                       "pixel_area_um2": float(np.prod(tile["mpp_xy"])), "eligibility_reviewed": False}
            summary["included_in_exploratory_aggregate"] = bool(stromal_pixels and rows)
            summary["tile_status"] = ("no_call_no_detected_nuclei" if not rows else
                                      "no_call_no_predicted_stroma" if not stromal_pixels else "experimental_components_complete")
            competition_stroma = competition == 2
            summary["competition"] = {
                "predicted_stromal_pixels": int(competition_stroma.sum()),
                "raw_immune_nuclear_pixels": int((np.isin(instances, immune_ids) & competition_stroma).sum()),
                "included_in_exploratory_aggregate": bool(competition_stroma.any() and rows),
                "sensitivity": {},
            }
            for threshold in (0., .5, .7, .9):
                accepted = [r["instance_id"] for r in rows if r["class_name"] in ("Lymphocyte", "Plasma_cell") and r["probability"] >= threshold]
                rejected = [r["instance_id"] for r in rows if r["class_name"] == "Unknown" or r["probability"] < threshold]
                summary["competition"]["sensitivity"][str(threshold)] = {
                    "immune_nuclear_pixels": int((np.isin(instances, accepted) & competition_stroma).sum()),
                    "unresolved_nuclear_pixels": int((np.isin(instances, rejected) & competition_stroma).sum()),
                }
            (tile_dir / "classification_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            receipt["tiles"].append(summary)
            receipt["processed_tiles"] += 1
            print(slide_key, "classified", receipt["processed_tiles"], "/", len(segmentation["tiles"]), "tiles;", len(rows), "nuclei", flush=True)
            save()
        callable_tiles = [t for t in receipt["tiles"] if t["included_in_exploratory_aggregate"]]
        denominator = sum(t["predicted_stromal_pixels"] * t["pixel_area_um2"] for t in callable_tiles)
        numerator = sum(t["raw_immune_nuclear_pixels"] * t["pixel_area_um2"] for t in callable_tiles)
        competition_tiles = [t for t in receipt["tiles"] if t["competition"]["included_in_exploratory_aggregate"]]
        competition_denominator = sum(t["competition"]["predicted_stromal_pixels"] * t["pixel_area_um2"] for t in competition_tiles)
        competition_numerator = sum(t["competition"]["raw_immune_nuclear_pixels"] * t["pixel_area_um2"] for t in competition_tiles)
        receipt.update(status="completed_experimental_comparison", stage="completed", finished_utc_seconds=time.time(),
                       sampled_predicted_stroma_um2=denominator, raw_immune_nuclear_area_um2=numerator,
                       exploratory_model_stroma_nuclear_area_percent=100*numerator/denominator if denominator else None,
                       endpoint="sampled nuclear area in callable model-predicted stroma; not reviewed visual sTIL",
                       callable_tiles=len(callable_tiles), tile_no_calls=len(receipt["tiles"])-len(callable_tiles),
                       competition_model_stroma_nuclear_area_percent=100*competition_numerator/competition_denominator if competition_denominator else None,
                       competition_callable_tiles=len(competition_tiles),
                       competition_mask_method="larger independent class probability wins; maximum must be >=0.5; ties unassigned",
                       competition_mask_status="development diagnostic; selected before TIL ratios; not validated semantic segmentation",
                       nuclear_area_proxy_percent=None, clinical_stil_percent=None,
                       total_nuclei=sum(t["classified_nuclei"] for t in receipt["tiles"]),
                       artifacts=[{"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": digest(p)}
                                  for p in sorted(root.rglob("*")) if p.is_file() and p.name in
                                  ("cell_classifications.json", "class_probabilities.npz", "classification_summary.json", "tissue_labels_competition.npy")])
    except Exception:
        receipt.update(status="failed", error=traceback.format_exc(), finished_utc_seconds=time.time())
    save()
    return {k: v for k, v in receipt.items() if k not in ("tiles", "artifacts")}


@app.function(image=modal.Image.debian_slim(python_version="3.11"), volumes={"/data": volume},
              cpu=4, memory=8192, timeout=1800)
def bundle(run_id: str, slide_key: str = "all", require_classification: bool = True):
    import json
    import zipfile
    from concurrent.futures import ThreadPoolExecutor, as_completed

    base = Path("/data/modular-20261022")
    root = base / run_id
    keys = [slide_key] if slide_key != "all" else [f"s{i:02d}" for i in range(9)]
    files = []
    for key in keys:
        segment_receipt = json.loads((root / key / "run_manifest.json").read_text())
        if segment_receipt["status"] != "completed_two_components":
            raise ValueError("segmentation is not complete for " + key)
        if require_classification:
            classification = json.loads((root / key / "classification_manifest.json").read_text())
            if classification["status"] != "completed_experimental_comparison":
                raise ValueError("classification is not complete for " + key)
        files.extend(p for p in sorted((root / key).rglob("*")) if p.is_file())
    def identify(p):
        return {"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": digest(p)}

    entries = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for index, future in enumerate(as_completed([pool.submit(identify, p) for p in files]), 1):
            entries.append(future.result())
            if index % 100 == 0:
                print("bundle hashed", index, "/", len(files), "files", flush=True)
    entries.sort(key=lambda item: item["path"])
    manifest = {"run_id": run_id, "classification_required": require_classification, "slide_keys": keys,
                "files": entries, "clinical_stil_percent": None}
    archives = base / "archives"
    archives.mkdir(exist_ok=True)
    suffix = "full" if require_classification else "segmentation"
    path = archives / f"{run_id}-{slide_key}-{suffix}.zip"
    if path.exists():
        raise FileExistsError("archive already exists")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as archive:
        for index, p in enumerate(files, 1):
            archive.write(p, str(p.relative_to(root)))
            if index % 100 == 0:
                print("bundle compressed", index, "/", len(files), "files", flush=True)
        archive.writestr("bundle_manifest.json", json.dumps(manifest, indent=2) + "\n")
    result = {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path), "files": len(files)}
    path.with_suffix(".receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    volume.commit()
    return result


@app.local_entrypoint()
def main(stage: str = "provision", slide_key: str = "s03", limit: int = 0,
         run_id: str = "development-v1"):
    import json

    def emit(result):
        print(json.dumps(result, indent=2))
        rows = result if isinstance(result, list) else [result]
        if any(row.get("status") == "failed" for row in rows):
            raise RuntimeError("a model stage failed; inspect its retained manifest and use a new run ID")

    if stage == "provision":
        emit(provision.remote())
    elif stage == "segment":
        emit(segment.remote(slide_key, limit, run_id))
    elif stage == "batch":
        emit(list(segment.starmap([(f"s{i:02d}", limit, run_id) for i in range(9)])))
    elif stage == "classify":
        emit(classify.remote(slide_key, run_id))
    elif stage == "classify-batch":
        emit(list(classify.starmap([(f"s{i:02d}", run_id) for i in range(9)])))
    elif stage == "bundle":
        emit(bundle.remote(run_id, slide_key))
    else:
        raise ValueError("unsupported stage")
