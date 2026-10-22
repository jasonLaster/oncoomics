"""Artifact-aware tile sampling for the modular H&E research pipeline, not clinical sTIL.

Every rule here works on RGB arrays (0..255) already read from a slide, so it can be
tested without OpenSlide. The CLI in ``scripts/stil_sample_tiles.py`` reads slides and
writes tiles. Thresholds are development heuristics frozen after visual review of the
2026-10-22 sampling failure; they are not validated artifact segmentation.

Pixel classes on the working map (``CLASS_*``):
- background: glass, slide label area or anything outside the tissue mask;
- tissue: stained, non-white tissue that a tile may sample;
- white_in_tissue: white pixels inside the tissue envelope, mostly adipocyte lumens
  and tears; a tile dominated by them is excluded as fat or white space;
- ink: pathologist marker (blue, green or black), including margin ink, dilated by a
  safety margin so tiles cannot graze handwriting.
"""

import math

CLASS_BACKGROUND, CLASS_TISSUE, CLASS_WHITE, CLASS_INK = 0, 1, 2, 3
CLASS_NAMES = {CLASS_BACKGROUND: "background", CLASS_TISSUE: "tissue", CLASS_WHITE: "white_in_tissue", CLASS_INK: "ink"}

DEFAULT_RULES = {
    "white_max_optical_density": 0.08,
    "tissue_min_optical_density": 0.08,
    "blue_ink": "B-R>40 and G-R>8 and B>110",
    "green_ink": "G-R>20 and G>=B-10 and G>90",
    "black_ink": "max channel <90 and saturation <0.2",
    "ink_min_component_um2": 2500.0,
    "ink_dilation_um": 150.0,
    "tissue_min_component_um2": 40000.0,
    "tissue_close_um": 60.0,
    "min_assessable_tissue_fraction": 0.5,
    "max_ink_fraction": 0.0,
    "max_white_fraction": 0.5,
    "lumen_rule": "optical density <0.08, or saturation <0.07 and optical density <0.2",
    "max_core_lumen_fraction": 0.8,
}


def _np():
    import numpy as np

    return np


def saturation(rgb):
    np = _np()
    rgb = rgb.astype(np.float32)
    high, low = rgb.max(2), rgb.min(2)
    return np.where(high > 0, (high - low) / np.maximum(high, 1e-6), 0.)


def glass_rgb(rgb):
    """Per-channel glass brightness: median of bright, unsaturated pixels (fallback 250)."""
    np = _np()
    bright = (rgb.min(2) >= 200) & (saturation(rgb) < .05)
    if bright.sum() < 100:
        return [250., 250., 250.]
    return [float(v) for v in np.median(rgb[bright].reshape(-1, 3), 0)]


def optical_density(rgb, glass=(250., 250., 250.)):
    """Largest per-channel optical density relative to glass; glass and fat lumens are near 0.

    Pale post-treatment collagen still absorbs strongly in one channel (green for
    eosin), so the maximum channel separates it from adipocyte lumens far better
    than brightness or saturation.
    """
    np = _np()
    ratio = np.clip(rgb.astype(np.float32), 1., None) / np.asarray(glass, np.float32)
    return np.clip(-np.log(ratio), 0., None).max(2)


def ink_pixels(rgb):
    """Pixel rule for blue, green and black marker.

    Hematoxylin is purple (green below red); blue and green marker have green
    at or above red. Black marker is darker than any H&E stain at working scale.
    """
    np = _np()
    r, g, b = (rgb[..., i].astype(np.int16) for i in range(3))
    blue = (b - r > 40) & (g - r > 8) & (b > 110)
    green = (g - r > 20) & (g >= b - 10) & (g > 90)
    black = (rgb.max(2) < 90) & (saturation(rgb) < .2)
    return blue | green | black


def white_pixels(rgb, glass=(250., 250., 250.), rules=DEFAULT_RULES):
    return optical_density(rgb, glass) < rules["white_max_optical_density"]


def lumen_pixels(rgb, glass=(250., 250., 250.)):
    """Adipocyte lumens and glass at full resolution, including grey-hazed lumens."""
    od = optical_density(rgb, glass)
    return (od < .08) | ((saturation(rgb) < .07) & (od < .2))


def _disk(radius):
    np = _np()
    radius = max(int(round(radius)), 1)
    y, x = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    return x * x + y * y <= radius * radius


def _drop_small(mask, min_pixels):
    from scipy import ndimage

    np = _np()
    labels, count = ndimage.label(mask)
    if not count:
        return mask
    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    keep = np.zeros(count + 1, bool)
    keep[1:] = sizes >= min_pixels
    return keep[labels]


def ink_mask(rgb, um_per_pixel, rules=DEFAULT_RULES):
    """Ink components above a minimum area, dilated by a safety margin."""
    from scipy import ndimage

    raw = ink_pixels(rgb)
    raw = ndimage.binary_opening(raw, structure=_disk(1))
    raw = _drop_small(raw, rules["ink_min_component_um2"] / um_per_pixel ** 2)
    radius = rules["ink_dilation_um"] / um_per_pixel
    return ndimage.binary_dilation(raw, structure=_disk(radius)) if raw.any() else raw


def tissue_envelope(rgb, um_per_pixel, glass=(250., 250., 250.), rules=DEFAULT_RULES):
    """FESI-style structure mask: stained or textured pixels, closed and hole-filled.

    Follows the FESI idea (Bándi et al. 2017) of combining a colour/density
    foreground with local structure (absolute Laplacian), then morphological
    closing, hole filling and removal of small components. Ink is removed before
    and after so marker strokes cannot seed or bridge tissue.
    """
    from scipy import ndimage

    np = _np()
    ink = ink_pixels(rgb)
    od = optical_density(rgb, glass)
    gray = rgb.astype(np.float32).mean(2)
    structure = ndimage.gaussian_filter(np.abs(ndimage.laplace(ndimage.gaussian_filter(gray, 1.))), 2.)
    seed = ((od >= rules["tissue_min_optical_density"]) & (saturation(rgb) > .05)) | (structure > max(float(structure.mean()), 1.))
    seed &= ~ink
    seed = ndimage.binary_closing(seed, structure=_disk(rules["tissue_close_um"] / um_per_pixel))
    seed = ndimage.binary_fill_holes(seed)
    seed = _drop_small(seed, rules["tissue_min_component_um2"] / um_per_pixel ** 2)
    return seed & ~ink


def class_map(rgb, um_per_pixel, external_tissue=None, rules=DEFAULT_RULES):
    """Return a uint8 map of CLASS_* codes for a downsampled slide image.

    ``external_tissue`` (e.g. ECTIL's native FESI mask resized to this grid) is
    intersected with the envelope, so either mask can veto tissue.
    """
    np = _np()
    glass = glass_rgb(rgb)
    envelope = tissue_envelope(rgb, um_per_pixel, glass, rules)
    if external_tissue is not None:
        if external_tissue.shape != envelope.shape:
            raise ValueError("external tissue mask must match the working grid")
        envelope &= external_tissue.astype(bool)
    out = np.zeros(rgb.shape[:2], np.uint8)
    out[envelope] = CLASS_TISSUE
    out[envelope & white_pixels(rgb, glass, rules)] = CLASS_WHITE
    out[ink_mask(rgb, um_per_pixel, rules)] = CLASS_INK
    return out


def polygon_mask(polygons_level0, shape_yx, downsample):
    """Rasterise level-0 polygons (lists of [x, y]; holes not supported) onto a grid."""
    from PIL import Image, ImageDraw

    np = _np()
    canvas = Image.new("L", (shape_yx[1], shape_yx[0]), 0)
    draw = ImageDraw.Draw(canvas)
    for polygon in polygons_level0:
        if len(polygon) < 3:
            raise ValueError("ROI polygon needs at least three vertices")
        draw.polygon([(x / downsample, y / downsample) for x, y in polygon], fill=1)
    return np.asarray(canvas, bool)


def load_roi_polygons(document):
    """Accept GeoJSON (Feature, FeatureCollection, Polygon, MultiPolygon) or {"polygons": [...]}.

    Coordinates must be level-0 pixels of the source slide, as exported by QuPath.
    Interior rings are rejected rather than silently ignored.
    """
    if "polygons" in document:
        return [list(map(list, p)) for p in document["polygons"]]
    if document.get("type") == "FeatureCollection":
        return [p for feature in document["features"] for p in load_roi_polygons(feature)]
    if document.get("type") == "Feature":
        return load_roi_polygons(document["geometry"])
    rings = {"Polygon": [document.get("coordinates")], "MultiPolygon": document.get("coordinates")}.get(document.get("type"))
    if rings is None:
        raise ValueError("unsupported ROI document")
    polygons = []
    for polygon in rings:
        if len(polygon) != 1:
            raise ValueError("ROI polygons with holes are not supported; split them first")
        polygons.append([list(map(float, point[:2])) for point in polygon[0]])
    return polygons


def grid_candidates(classes, downsample, level0_size, tile=1024, halo=64, roi=None, rules=DEFAULT_RULES,
                    min_roi_fraction=0.5):
    """Score every disjoint ``tile`` grid cell; returns one dict per cell with tissue.

    A cell is eligible when its halo footprint contains no ink, its core has at
    least ``min_assessable_tissue_fraction`` tissue and at most
    ``max_white_fraction`` white-in-tissue, and (with an ROI) at least
    ``min_roi_fraction`` of its core lies inside the ROI.
    """
    width, height = level0_size
    rows = []
    # Cells stay on the legacy 0-aligned grid so earlier tiles keep their IDs.
    for y in range(0, height - tile + 1, tile):
        for x in range(0, width - tile + 1, tile):
            if x < halo or y < halo or x + tile + halo > width or y + tile + halo > height:
                continue
            def window(x0, y0, size):
                a, b = int(math.floor(x0 / downsample)), int(math.floor(y0 / downsample))
                c, d = int(math.ceil((x0 + size) / downsample)), int(math.ceil((y0 + size) / downsample))
                return slice(b, max(d, b + 1)), slice(a, max(c, a + 1))
            core = classes[window(x, y, tile)]
            if not core.size or not (core != CLASS_BACKGROUND).any():
                continue
            footprint = classes[window(x - halo, y - halo, tile + 2 * halo)]
            row = {"origin_level0_xy": [x, y],
                   "tissue_fraction": float((core == CLASS_TISSUE).mean()),
                   "white_fraction": float((core == CLASS_WHITE).mean()),
                   "background_fraction": float((core == CLASS_BACKGROUND).mean()),
                   "ink_fraction_halo": float((footprint == CLASS_INK).mean())}
            if roi is not None:
                row["roi_fraction"] = float(roi[window(x, y, tile)].mean())
            reasons = []
            if row["ink_fraction_halo"] > rules["max_ink_fraction"]:
                reasons.append("ink")
            if row["tissue_fraction"] < rules["min_assessable_tissue_fraction"]:
                reasons.append("off_tissue" if row["background_fraction"] > row["white_fraction"] else "fat_or_white")
            elif row["white_fraction"] > rules["max_white_fraction"]:
                reasons.append("fat_or_white")
            if roi is not None and row["roi_fraction"] < min_roi_fraction:
                reasons.append("outside_roi")
            row["exclusion_reasons"] = reasons
            row["eligible"] = not reasons
            rows.append(row)
    return rows


def farthest_point(points, count):
    """Deterministic farthest-point order starting nearest the centroid."""
    np = _np()
    points = np.asarray(points, float)
    if not len(points) or count <= 0:
        return []
    selected = [int(np.argmin(((points - points.mean(0)) ** 2).sum(1)))]
    distance = np.full(len(points), np.inf)
    while len(selected) < min(count, len(points)):
        distance = np.minimum(distance, ((points - points[selected[-1]]) ** 2).sum(1))
        distance[selected] = -1
        selected.append(int(np.argmax(distance)))
    return selected


def select(candidates, mode="spread", count=32, stride=1):
    """Pick eligible cells.

    ``spread``: ``count`` cells by farthest-point sampling (the legacy design);
    ``exhaustive``: every eligible cell (intended inside a reviewed ROI);
    ``dense``: every ``stride``-th eligible grid cell in x and y, a checkerboard-like
    subsample for large ROIs.
    """
    eligible = [c for c in candidates if c["eligible"]]
    if mode == "exhaustive":
        return sorted(eligible, key=lambda c: (c["origin_level0_xy"][1], c["origin_level0_xy"][0]))
    if mode == "dense":
        if stride < 1:
            raise ValueError("stride must be positive")
        xs = sorted({c["origin_level0_xy"][0] for c in eligible})
        ys = sorted({c["origin_level0_xy"][1] for c in eligible})
        if not eligible:
            return []
        step = xs[1] - xs[0] if len(xs) > 1 else (ys[1] - ys[0] if len(ys) > 1 else 1)
        x0, y0 = min(xs), min(ys)
        chosen = [c for c in eligible
                  if ((c["origin_level0_xy"][0] - x0) // step) % stride == 0 and ((c["origin_level0_xy"][1] - y0) // step) % stride == 0]
        return sorted(chosen, key=lambda c: (c["origin_level0_xy"][1], c["origin_level0_xy"][0]))
    if mode != "spread":
        raise ValueError("unsupported sampling mode")
    order = farthest_point([c["origin_level0_xy"] for c in eligible], count)
    return sorted((eligible[i] for i in order), key=lambda c: (c["origin_level0_xy"][1], c["origin_level0_xy"][0]))


def tile_pixel_qc(rgb, halo=64, glass=(250., 250., 250.), rules=DEFAULT_RULES):
    """Recheck an extracted full-resolution tile (core plus halo) independently of the map.

    Uses the legacy blue rule from ``stil_modular_image_qc.py`` and this module's
    marker rule. ``ink_tile`` is true if either rule exceeds 0.5% of the halo tile.
    ``off_tissue_tile`` is true for little stained core or a core that is mostly
    fat lumen or glass (grey-hazed fat passes the plain optical-density rule).
    """
    np = _np()
    core = rgb[halo:-halo, halo:-halo] if halo else rgb
    r, g, b = (rgb[..., i].astype(np.int16) for i in range(3))
    legacy_blue = float(((b - r > 60) & (b - g > 40) & (b > 120)).mean())
    marker = float(ink_pixels(rgb).mean())
    white = float(white_pixels(core, glass, rules).mean())
    tissue = float((optical_density(core, glass) >= rules["tissue_min_optical_density"]).mean())
    lumen = float(lumen_pixels(core, glass).mean())
    return {"legacy_blue_fraction": legacy_blue, "marker_fraction": marker, "core_white_fraction": white,
            "core_stained_fraction": tissue, "core_lumen_fraction": lumen, "ink_tile": max(legacy_blue, marker) > .005,
            "off_tissue_tile": tissue < .25 or lumen > rules["max_core_lumen_fraction"]}
