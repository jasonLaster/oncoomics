"""Artifact-aware tile sampling for the modular H&E pipeline; writes private tiles and review maps.

Reads whole-slide images with OpenSlide, builds a tissue / white / ink class map at
about 8 um per pixel, scores the legacy 1024-pixel grid and selects tiles by
farthest-point spread, every eligible cell (exhaustive) or a strided subset (dense),
optionally restricted to a level-0 ROI polygon. Use ``--maps-only`` to review sampling
before extracting any tile or spending GPU time.
"""

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, PngImagePlugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from diana_omics import stil_sampling as sampling  # noqa: E402

PngImagePlugin.MAX_TEXT_CHUNK = 1 << 30
TILE, HALO = 1024, 64
COLORS = {sampling.CLASS_TISSUE: (60, 170, 90), sampling.CLASS_WHITE: (240, 200, 40), sampling.CLASS_INK: (230, 40, 200)}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def working_level(wsi, target_downsample=16):
    return min(range(wsi.level_count), key=lambda i: abs(wsi.level_downsamples[i] - target_downsample))


def fine_check(wsi, candidates, glass):
    """Re-check map-eligible cells at level 0 with the same rule as the final tile QC.

    Thin inked margin rims on tissue are invisible at 8 um and under-counted at 2 um.
    """
    level = 0
    downsample = wsi.level_downsamples[level]
    size = int(math.ceil((TILE + 2 * HALO) / downsample))
    halo = int(round(HALO / downsample))
    for c in candidates:
        if not c["eligible"]:
            continue
        x, y = c["origin_level0_xy"]
        rgb = np.asarray(wsi.read_region((x - HALO, y - HALO), level, (size, size)).convert("RGB"))
        qc = sampling.tile_pixel_qc(rgb, halo, glass)
        c["fine_check"] = dict(qc, level=level)
        if qc["ink_tile"]:
            c["exclusion_reasons"].append("ink_fine")
        if qc["off_tissue_tile"]:
            c["exclusion_reasons"].append("off_tissue_fine")
        c["eligible"] = not c["exclusion_reasons"]


def render_map(rgb, classes, selected, legacy, excluded_legacy, title, roi_polygons, downsample):
    overlay = rgb.copy()
    for code, color in COLORS.items():
        match = classes == code
        overlay[match] = (.6 * overlay[match] + .4 * np.array(color)).astype(np.uint8)
    image = Image.fromarray(np.concatenate([rgb, overlay], 0))
    draw = ImageDraw.Draw(image)
    height = rgb.shape[0]
    for panel in (0, height):
        for polygon in roi_polygons:
            draw.line([(x / downsample, y / downsample + panel) for x, y in polygon + polygon[:1]], fill=(255, 120, 0), width=3)
        for x, y in excluded_legacy:
            draw.rectangle([x / downsample, y / downsample + panel, (x + TILE) / downsample, (y + TILE) / downsample + panel],
                           outline=(0, 0, 0), width=2)
            draw.line([x / downsample, y / downsample + panel, (x + TILE) / downsample, (y + TILE) / downsample + panel], fill=(0, 0, 0), width=2)
        for x, y in selected:
            reused = (x, y) in legacy
            draw.rectangle([x / downsample, y / downsample + panel, (x + TILE) / downsample, (y + TILE) / downsample + panel],
                           outline=(0, 90, 255) if reused else (255, 0, 0), width=3)
    draw.rectangle([0, 0, 1500, 34], fill="white")
    draw.text((8, 8), title, fill="black")
    draw.text((8, height + 8), "overlay: green tissue, yellow white/fat, magenta ink (dilated); red new tile, blue reused tile, "
              "black X legacy tile now excluded; orange ROI", fill="black")
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-manifest", type=Path, required=True, help="Earlier tile_manifest.json supplying slide identities")
    parser.add_argument("--slides-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New private output directory")
    parser.add_argument("--keys", default="", help="Comma-separated slide keys; default all")
    parser.add_argument("--ectil-dir", type=Path, help="Optional ECTIL output directory with <slide stem>/native_fesi_mask.png, for agreement QC")
    parser.add_argument("--intersect-ectil", action="store_true",
                        help="Also veto tissue outside the ECTIL mask (it drops whole fragments on some slides; off by default)")
    parser.add_argument("--roi", action="append", default=[], help="key=path to a level-0 GeoJSON or {polygons: [...]} ROI")
    parser.add_argument("--mode", choices=("spread", "exhaustive", "dense"), default="spread")
    parser.add_argument("--count", type=int, default=32)
    parser.add_argument("--stride", type=int, default=2)
    parser.add_argument("--max-tiles", type=int, default=0, help="Refuse to extract more than this many tiles per slide (0 = no cap)")
    parser.add_argument("--maps-only", action="store_true")
    args = parser.parse_args()
    import openslide

    legacy_manifest = json.loads(args.legacy_manifest.read_text())
    legacy_inputs = args.legacy_manifest.parent
    legacy_tiles = {}
    for row in legacy_manifest["tiles"]:
        legacy_tiles.setdefault(row["slide_key"], {})[tuple(row["origin_level0_xy"])] = row
    keys = [k for k in args.keys.split(",") if k] or [s["slide_key"] for s in legacy_manifest["slides"]]
    rois = dict(item.split("=", 1) for item in args.roi)
    args.out.mkdir(parents=True, exist_ok=False)
    slides, tiles = [], []
    for key in keys:
        slide = next(s for s in legacy_manifest["slides"] if s["slide_key"] == key)
        path = args.slides_dir / slide["slide"]
        if digest(path) != slide["source_sha256"]:
            raise ValueError("source hash mismatch for " + slide["slide"])
        example = next(iter(legacy_tiles[key].values()))
        mpp = example["mpp_xy"]
        folder = args.out / key
        folder.mkdir()
        with openslide.OpenSlide(str(path)) as wsi:
            level = working_level(wsi)
            downsample = wsi.level_downsamples[level]
            rgb = np.asarray(wsi.read_region((0, 0), level, wsi.level_dimensions[level]).convert("RGB"))
            external = None
            if args.ectil_dir:
                mask_path = args.ectil_dir / Path(slide["slide"]).stem / "native_fesi_mask.png"
                external = np.asarray(Image.open(mask_path).convert("L").resize((rgb.shape[1], rgb.shape[0]), Image.NEAREST)) > 0
            um = mpp[0] * downsample
            classes = sampling.class_map(rgb, um, external if args.intersect_ectil else None)
            roi_polygons = sampling.load_roi_polygons(json.loads(Path(rois[key]).read_text())) if key in rois else []
            roi = sampling.polygon_mask(roi_polygons, classes.shape, downsample) if roi_polygons else None
            candidates = sampling.grid_candidates(classes, downsample, wsi.dimensions, TILE, HALO, roi)
            glass = sampling.glass_rgb(rgb)
            fine_check(wsi, candidates, glass)
            chosen = sampling.select(candidates, args.mode, args.count, args.stride)
            if args.max_tiles and len(chosen) > args.max_tiles:
                raise ValueError(f"{key}: {len(chosen)} tiles exceed --max-tiles {args.max_tiles}")
            by_origin = {tuple(c["origin_level0_xy"]): c for c in candidates}
            legacy = set(legacy_tiles.get(key, {}))
            excluded_legacy = [xy for xy in legacy if not by_origin.get(xy, {}).get("eligible")]
            legacy_reasons = {f"x{x:06d}_y{y:06d}": by_origin.get((x, y), {}).get("exclusion_reasons", ["no_tissue_in_cell"])
                              for x, y in sorted(legacy)}
            selected = [tuple(c["origin_level0_xy"]) for c in chosen]
            title = (f"{key} {slide['slide']}  mode={args.mode}  selected={len(chosen)}  eligible={sum(c['eligible'] for c in candidates)}"
                     f"  legacy excluded={len(excluded_legacy)}/{len(legacy)}")
            render_map(rgb, classes, selected, legacy, excluded_legacy, title, roi_polygons, downsample).save(folder / "sampling_map.png")
            Image.fromarray(classes * 80).save(folder / "class_map.png")
            counts = {name: int((classes == code).sum()) for code, name in sampling.CLASS_NAMES.items()}
            reasons = {}
            for c in candidates:
                for reason in c["exclusion_reasons"]:
                    reasons[reason] = reasons.get(reason, 0) + 1
            (folder / "candidates.json").write_text(json.dumps(candidates, indent=1) + "\n")
            record = {"slide": slide["slide"], "slide_key": key, "source_sha256": slide["source_sha256"],
                      "candidate_tissue_group": example["candidate_tissue_group"], "working_level": level,
                      "working_downsample": downsample, "working_um_per_pixel": um, "glass_rgb": glass, "class_pixel_counts": counts,
                      "grid_cells_with_tissue": len(candidates), "eligible_cells": sum(c["eligible"] for c in candidates),
                      "exclusion_reason_counts": reasons, "sampled_tiles": len(chosen),
                      "reused_legacy_tiles": sum(xy in legacy for xy in selected),
                      "legacy_tiles_excluded_by_new_rule": len(excluded_legacy), "legacy_exclusion_reasons": legacy_reasons,
                      "roi": rois.get(key), "roi_polygons": len(roi_polygons),
                      "sampled_core_area_mm2": len(chosen) * TILE ** 2 * math.prod(mpp) / 1e6,
                      "eligible_tumor_coverage": "unknown" if not roi_polygons else "restricted_to_supplied_roi"}
            if external is not None:
                own = classes != sampling.CLASS_BACKGROUND
                own_tissue = classes == sampling.CLASS_TISSUE
                record["ectil_fesi_agreement"] = {
                    "ectil_fraction_of_slide": float(external.mean()), "own_envelope_fraction_of_slide": float(own.mean()),
                    "own_tissue_outside_ectil_fraction": float((own_tissue & ~external).sum() / max(own_tissue.sum(), 1)),
                    "ectil_outside_own_envelope_fraction": float((external & ~own).sum() / max(external.sum(), 1)),
                    "ink_pixels_inside_ectil": int(((classes == sampling.CLASS_INK) & external).sum())}
            slides.append(record)
            print(key, slide["slide"], json.dumps({k: record[k] for k in ("eligible_cells", "sampled_tiles", "reused_legacy_tiles",
                                                                           "legacy_tiles_excluded_by_new_rule", "exclusion_reason_counts")}), flush=True)
            if args.maps_only:
                continue
            for c in chosen:
                x, y = c["origin_level0_xy"]
                tile_id = f"{key}_x{x:06d}_y{y:06d}"
                destination = folder / (tile_id + ".png")
                old = legacy_tiles.get(key, {}).get((x, y))
                if old and digest(legacy_inputs / old["image_path"]) == old["image_sha256"]:
                    shutil.copyfile(legacy_inputs / old["image_path"], destination)
                    provenance = "copied_from_legacy_inputs"
                else:
                    image = wsi.read_region((x - HALO, y - HALO), 0, (TILE + 2 * HALO,) * 2).convert("RGBA")
                    background = Image.new("RGBA", image.size, "white")
                    background.alpha_composite(image)
                    background.convert("RGB").save(destination)
                    provenance = "extracted_level0"
                pixel_qc = sampling.tile_pixel_qc(np.asarray(Image.open(destination).convert("RGB")), HALO, glass)
                tiles.append({"tile_id": tile_id, "slide_key": key, "slide": slide["slide"], "source_sha256": slide["source_sha256"],
                              "image_path": str(destination.relative_to(args.out)), "image_sha256": digest(destination),
                              "halo_pixels": HALO, "origin_level0_xy": [x, y], "mpp_xy": mpp, "core_shape_yx": [TILE, TILE],
                              "candidate_tissue_group": example["candidate_tissue_group"], "sampling_metrics": c,
                              "pixel_qc": pixel_qc, "provenance": provenance,
                              "annotation_reviewed": False, "clinical_stil_percent": None})
    sampling_block = {
        "method": {"spread": "deterministic farthest-point spatial sampling of eligible cells",
                   "exhaustive": "every eligible cell", "dense": f"every {args.stride}th eligible cell in x and y"}[args.mode],
        "mode": args.mode, "target_tiles_per_slide": args.count if args.mode == "spread" else None,
        "grid": "disjoint 1024-pixel level-0 grid aligned to 0, 64-pixel halo inside slide bounds",
        "tissue_rule": "FESI-style envelope (density/saturation or Laplacian structure, closed, hole-filled, small components dropped)"
                       + (" intersected with ECTIL native FESI mask" if args.intersect_ectil else "")
                       + "; ink removed by explicit marker rule and dilation",
        "rules": sampling.DEFAULT_RULES, "sampler_sha256": digest(Path(__file__)),
        "sampling_module_sha256": digest(Path(sampling.__file__)),
        "legacy_manifest_sha256": digest(args.legacy_manifest),
        "selection_independent_of_model_TIL_outputs": True,
        "purpose": "development feasibility and failure review, not unbiased patient validation",
        "eligible_tumor_coverage": "unknown unless an ROI is supplied", "original_slides_unchanged": True}
    manifest = {"schema_version": 2, "sampling": sampling_block, "slides": slides, "tiles": tiles,
                "maps_only": args.maps_only, "clinical_stil_percent": None}
    name = "sampling_plan.json" if args.maps_only else "tile_manifest.json"
    (args.out / name).write_text(json.dumps(manifest, indent=2) + "\n")
    flagged = [t["tile_id"] for t in tiles if t["pixel_qc"]["ink_tile"] or t["pixel_qc"]["off_tissue_tile"]]
    print(json.dumps({"slides": len(slides), "tiles": len(tiles), "pixel_qc_flagged_tiles": flagged}, indent=2))
    if flagged:
        raise SystemExit("pixel QC flagged sampled tiles; review before inference")


if __name__ == "__main__":
    main()
