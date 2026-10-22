"""Baseline the existing sTIL research runners on the TIGER development split.

The inference functions are not reimplemented. They are executed from frozen,
hash-pinned copies of the existing runners:

- ECTIL and MuTILs: `run_ectil` / `run_mutils` from scripts/modal/stil_batch.py
  (untracked research runner; SHA-256 pinned below).
- Modular VISTA-PATH -> Cellpose 3 -> CytoFormer: `segment` / `classify` from
  scripts/modal/stil_modular_execute.py at commit a1764b5a.

Only their storage bindings change: `/pilot` and `/data` are the private TIGER
benchmark volume, and `/raw` is a volume holding only development-split slides.
Model code, weights, preprocessing, sampling and aggregation are untouched. The
modular tile sampler mirrors .runs/stil-modular-20261022/prepare_tiles.py.

Place the frozen copies under .runs/stil-tiger-benchmark/frozen/ first:
  git show a1764b5a:scripts/modal/stil_modular_execute.py > .runs/stil-tiger-benchmark/frozen/stil_modular_execute_a1764b5a.py
  cp scripts/modal/stil_batch.py .runs/stil-tiger-benchmark/frozen/stil_batch.py

  modal run scripts/modal/stil_tiger_baselines.py --stage assets
  modal run scripts/modal/stil_tiger_baselines.py --stage probe --slides 104S
  modal run scripts/modal/stil_tiger_baselines.py --stage ectil --slides all
  modal run scripts/modal/stil_tiger_baselines.py --stage collect
"""

import ast
import hashlib
import json
from pathlib import Path

import modal

FROZEN_SHA256 = {
    "stil_batch.py": "3e8dcc8aaebb5e5be1ab61862470665b65b5b6eaf31d8f9bf3da67a829d7defb",
    "stil_modular_execute_a1764b5a.py": "e443489e76a3588dfc7788d6d1b81e60f14593828bcbe1030c1d737d28ad56fd",
}
FROZEN_DIR = (Path(__file__).resolve().parents[2] / ".runs/stil-tiger-benchmark/frozen") if modal.is_local() else Path("/opt/frozen")
SPLIT_PATH = Path(__file__).resolve().parents[2] / "manifests/stil_tiger_benchmark_split.json" if modal.is_local() else None
RUN_ID = "tiger-dev-baseline-v1"

app = modal.App("diana-stil-tiger-baselines")
volume = modal.Volume.from_name("diana-stil-tiger-benchmark", create_if_missing=False)
slides_volume = modal.Volume.from_name("diana-stil-tiger-slides-dev", create_if_missing=True)
pilot_volume = modal.Volume.from_name("diana-stil-pilot-20261021", create_if_missing=False)


def _exec_frozen(filename, assigns, functions, keep_if=False):
    """Execute selected top-level nodes of a pinned runner into this module."""
    source = (FROZEN_DIR / filename).read_bytes()
    actual = hashlib.sha256(source).hexdigest()
    if actual != FROZEN_SHA256[filename]:
        raise RuntimeError(f"frozen runner hash mismatch for {filename}: {actual}")
    tree = ast.parse(source.decode())
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) in assigns for t in node.targets):
            body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in functions:
            node.decorator_list = []
            body.append(node)
        elif keep_if and isinstance(node, ast.If):
            body.append(node)
    found = {getattr(t, "id", None) for n in body if isinstance(n, ast.Assign) for t in n.targets}
    found |= {n.name for n in body if isinstance(n, ast.FunctionDef)}
    missing = (set(assigns) | set(functions)) - found
    if missing:
        raise RuntimeError(f"{filename} lacks {sorted(missing)}")
    exec(compile(ast.Module(body=body, type_ignores=[]), str(FROZEN_DIR / filename), "exec"), globals())


# Images and inference functions, byte-for-byte from the frozen runners.
_exec_frozen("stil_batch.py", ("MUTILS_IMAGE", "mutils_image", "ectil_image"), ("sha256", "run_mutils", "run_ectil"))
_exec_frozen("stil_modular_execute_a1764b5a.py", ("image",), ("digest", "segment", "classify"), keep_if=True)
modular_image = image  # noqa: F821  (defined by the frozen modular runner)
if modal.is_local():
    mutils_image = mutils_image.add_local_dir(FROZEN_DIR, "/opt/frozen")  # noqa: F821
    ectil_image = ectil_image.add_local_dir(FROZEN_DIR, "/opt/frozen")  # noqa: F821
    modular_image = modular_image.add_local_dir(FROZEN_DIR, "/opt/frozen")
util_image = modal.Image.debian_slim(python_version="3.11")
annotate_image = ectil_image  # noqa: F821  (OpenSlide 3.4 as used by the runners)
if modal.is_local():
    util_image = util_image.add_local_dir(FROZEN_DIR, "/opt/frozen")
    annotate_image = annotate_image.add_local_file(
        Path(__file__).resolve().parents[2] / "src/diana_omics/tiff_mpp.py", "/opt/helpers/tiff_mpp.py")

# Same resources as the original decorators; storage rebound to TIGER volumes.
_frozen_run_ectil = run_ectil  # noqa: F821


def run_ectil(row: dict, run_id: str):
    """Call the frozen ECTIL runner after loading OpenSlide's JPEG decoder first.

    In the ECTIL image, importing torch/torchvision and then dlup.data.dataset
    before OpenSlide's first decode makes JPEG-tables tiles (TIGER's encoding) fail
    with "Huffman table 0x00 was not defined". Decoding one tile first avoids the
    native-library clash; the runner's code and inputs are unchanged.
    """
    import pyvips
    pyvips.Image.openslideload(str(Path("/raw") / row["filename"]), level=3).crop(0, 0, 256, 256).write_to_memory()
    return _frozen_run_ectil(row, run_id)


run_ectil = app.function(image=ectil_image, gpu="A10G", cpu=4, memory=16384, timeout=7200,  # noqa: F821
                         volumes={"/pilot": volume, "/raw": slides_volume}, max_containers=4)(run_ectil)
_frozen_run_mutils = run_mutils  # noqa: F821
MUTILS_INFERENCE_SHA256 = "c6d3e484cff195fa8b5d0baefb497da3064471efa2c31e11546cefd65c9d780b"
MUTILS_LOG_BUG = '            self.logger.info(f"ROI {self._rid} has no nuclei!")'
MUTILS_LOG_FIX = '            __import__("logging").info(f"ROI {self._rid} has no nuclei!")'


def run_mutils(row: dict, run_id: str):
    """Frozen MuTILs runner; with `row["patch_no_nuclei_log"]`, first fix an upstream logging crash.

    In the pinned container, ROIPostProcessor.run_roi logs through `self.logger`,
    which is unset in the single-process path, so any ROI without nuclei aborts the
    slide. The fix replaces only that call with `logging.info`; the ROI is still
    skipped as upstream intends. The container image digest is unchanged (the edit
    is applied at run time); original/patched file hashes and the diff are recorded.
    """
    receipt = Path("/pilot") / run_id / "mutils" / Path(row["filename"]).stem / "run_manifest.json"
    if receipt.exists():
        prior = json.loads(receipt.read_text())
        if prior.get("status") == "completed" and prior.get("source_sha256") == row["sha256"]:
            return _frozen_run_mutils(row, run_id)  # returns the existing receipt; no patch applied or recorded
    if row.get("patch_no_nuclei_log"):
        import difflib
        import hashlib as _h
        path = Path("/home/MuTILs_Panoptic/mutils_panoptic/MuTILsInference.py")
        current = path.read_text()
        # A warm container may already hold the patch from an earlier slide.
        original = current.replace(MUTILS_LOG_FIX, MUTILS_LOG_BUG) if MUTILS_LOG_FIX in current else current
        assert original.count(MUTILS_LOG_BUG) == 1 and MUTILS_LOG_FIX not in original, "unexpected MuTILs source"
        assert _h.sha256(original.encode()).hexdigest() == MUTILS_INFERENCE_SHA256, "MuTILs source differs from the pinned image"
        patched = original.replace(MUTILS_LOG_BUG, MUTILS_LOG_FIX)
        if current != patched:
            path.write_text(patched)
        receipt_dir = Path("/pilot") / run_id / "mutils" / Path(row["filename"]).stem
        receipt_dir.mkdir(parents=True, exist_ok=True)
        (receipt_dir / "container_patch.json").write_text(json.dumps({
            "image": MUTILS_IMAGE, "image_digest_unchanged": True,  # noqa: F821
            "file": str(path), "original_sha256": _h.sha256(original.encode()).hexdigest(),
            "patched_sha256": _h.sha256(patched.encode()).hexdigest(),
            "diff": "".join(difflib.unified_diff(original.splitlines(True), patched.splitlines(True),
                                                 "MuTILsInference.py (pinned image)", "MuTILsInference.py (patched)")),
            "change": "self.logger.info -> logging.info on the no-nuclei ROI path only"}, indent=2) + "\n")
        volume.commit()
    return _frozen_run_mutils(row, run_id)


run_mutils = app.function(image=mutils_image, gpu="A10G", cpu=4, memory=24576, timeout=7200,  # noqa: F821
                          volumes={"/pilot": volume, "/raw": slides_volume}, max_containers=6)(run_mutils)
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


@app.function(image=util_image, volumes={"/tiger": volume, "/src": pilot_volume.read_only()}, timeout=3600)
def copy_assets():
    """Copy pinned model assets from the pilot volume (read-only) to the TIGER volume."""
    import shutil
    out = {}
    for name in ("mutils_06022021_fold1.pt", "epoch_065_step_858_weights_only.ckpt", "retccl_best_ckpt.pth"):
        src, dst = Path("/src/models") / name, Path("/tiger/models") / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copyfile(src, dst)
        out[name] = _sha(dst)
    src, dst = Path("/src/models/modular-20261022"), Path("/tiger/models/modular-20261022")
    if not dst.exists():
        shutil.copytree(src, dst)
    files = sorted(p for p in dst.rglob("*") if p.is_file())
    out["modular_files"] = len(files)
    out["modular_bytes"] = sum(p.stat().st_size for p in files)
    volume.commit()
    return out


@app.function(image=util_image, volumes={"/tiger": volume, "/slides": slides_volume}, timeout=3600, max_containers=8)
def link_slide(image_id: str):
    """Place one staged development slide at the root of the slides-only volume."""
    import shutil
    src = Path("/tiger/source/wsitils/images") / (image_id + ".tif")
    dst = Path("/slides") / (image_id + ".tif")
    if not (dst.exists() and dst.stat().st_size == src.stat().st_size):
        shutil.copyfile(src, dst)
    slides_volume.commit()
    return {"image_id": image_id, "filename": dst.name, "size": dst.stat().st_size, "sha256": _sha(dst)}


@app.function(image=annotate_image, volumes={"/tiger": volume, "/slides": slides_volume}, timeout=3600, max_containers=8)
def annotate_slide(row: dict):
    """Expose MPP to OpenSlide 3.4 via a metadata-only Aperio description; verify pixels are unchanged."""
    import sys

    import numpy as np
    import openslide
    sys.path.insert(0, "/opt/helpers")
    import tiff_mpp
    path = Path("/slides") / row["filename"]
    original = Path("/tiger/source/wsitils/images") / row["filename"]
    with openslide.OpenSlide(str(path)) as s:
        vendor = s.properties.get("openslide.vendor")
    if vendor != "aperio":
        assert _sha(path) == _sha(original), "slide copy differs from staged original"
        tiff_mpp.add_aperio_description(path)
        slides_volume.commit()
    with openslide.OpenSlide(str(path)) as a, openslide.OpenSlide(str(original)) as o:
        assert a.properties["openslide.vendor"] == "aperio" and o.properties["openslide.vendor"] == "generic-tiff"
        assert a.dimensions == o.dimensions and a.level_count == o.level_count
        rng = np.random.default_rng(0)
        checked = 0
        for _ in range(6):
            x = int(rng.integers(0, max(1, a.dimensions[0] - 512)))
            y = int(rng.integers(0, max(1, a.dimensions[1] - 512)))
            assert np.array_equal(np.asarray(a.read_region((x, y), 0, (512, 512))), np.asarray(o.read_region((x, y), 0, (512, 512))))
            checked += 1
        assert np.array_equal(np.asarray(a.get_thumbnail((1024, 1024))), np.asarray(o.get_thumbnail((1024, 1024))))
        return dict(row, sha256=_sha(path), original_sha256=_sha(original), mpp_x=float(a.properties["openslide.mpp-x"]),
                    mpp_y=float(a.properties["openslide.mpp-y"]), objective_power=a.properties.get("openslide.objective-power"),
                    pixel_regions_verified=checked, thumbnail_verified=True,
                    metadata_adapter="Aperio-style ImageDescription with MPP from TIFF resolution tags; pixels unchanged")


@app.function(image=ectil_image, volumes={"/tiger": volume, "/raw": slides_volume}, timeout=1200)  # noqa: F821
def reader_check(filename: str):
    """Read a corner region of every level with OpenSlide and with pyvips (DLUP's backend)."""
    import openslide
    import pyvips
    out = []
    for path in ("/raw/" + filename, "/tiger/source/wsitils/images/" + filename):
        s = openslide.OpenSlide(path)
        for lvl in range(s.level_count):
            w, h = s.level_dimensions[lvl]
            r = {"path": path, "level": lvl, "dims": [w, h]}
            try:
                s.read_region((0, 0), lvl, (min(w, 600), min(h, 600)))
                r["openslide"] = "ok"
            except Exception as e:
                r["openslide"] = str(e)[:200]
            try:
                pyvips.Image.openslideload(path, level=lvl).crop(0, 0, min(w, 600), min(h, 600)).write_to_memory()
                r["vips_openslide"] = "ok"
            except Exception as e:
                r["vips_openslide"] = str(e)[:200]
            try:
                pyvips.Image.tiffload(path, page=lvl).crop(0, 0, min(w, 600), min(h, 600)).write_to_memory()
                r["vips_tiff"] = "ok"
            except Exception as e:
                r["vips_tiff"] = str(e)[:200]
            out.append(r)
    return {"vips": f"{pyvips.version(0)}.{pyvips.version(1)}", "openslide": openslide.__library_version__, "levels": out}


@app.function(image=ectil_image, volumes={"/tiger": volume, "/raw": slides_volume}, timeout=3600)  # noqa: F821
def full_level_check(filename: str, min_level: int = 3):
    """Decode whole pyramid levels with pyvips/OpenSlide; locate failing 512-px tiles."""
    import openslide
    import pyvips
    out = []
    s = openslide.OpenSlide("/raw/" + filename)
    for lvl in range(min_level, s.level_count):
        w, h = s.level_dimensions[lvl]
        r = {"level": lvl, "dims": [w, h]}
        try:
            pyvips.Image.openslideload("/raw/" + filename, level=lvl).write_to_memory()
            r["vips_full"] = "ok"
        except Exception as e:
            r["vips_full"] = str(e)[:200]
            bad = []
            for y in range(0, h, 512):
                for x in range(0, w, 512):
                    try:
                        s.read_region((int(x * s.level_downsamples[lvl]), int(y * s.level_downsamples[lvl])), lvl,
                                      (min(512, w - x), min(512, h - y)))
                    except Exception as e2:
                        bad.append([x, y, str(e2)[:80]])
                        s = openslide.OpenSlide("/raw/" + filename)
            r["openslide_bad_tiles"] = bad[:20]
            r["n_bad"] = len(bad)
        out.append(r)
    return out


@app.function(image=ectil_image, volumes={"/tiger": volume, "/raw": slides_volume}, timeout=3600)  # noqa: F821
def dlup_check(filename: str, mpp: float, torch_first: bool = False):
    """Reproduce ECTIL's DLUP thumbnail read on the adapted and the original slide."""
    import inspect
    import traceback
    if torch_first:
        import torch  # noqa: F401
        import torchvision  # noqa: F401

    from dlup import SlideImage
    sys_path = "/opt/ectil/ectil/utils/background.py"
    source = Path(sys_path).read_text()
    out = {"get_mask_source": source[source.find("def get_mask"):source.find("def get_mask") + 1500],
           "from_file_path_signature": str(inspect.signature(SlideImage.from_file_path))}
    for label, path, kwargs in (("adapted", "/raw/" + filename, {}),
                                ("original", "/tiger/source/wsitils/images/" + filename, {"overwrite_mpp": (mpp, mpp)})):
        r = {}
        try:
            slide = SlideImage.from_file_path(path, **kwargs)
            r["backend"] = type(slide._wsi).__name__
            r["mpp"] = slide.mpp
            r["level_dimensions"] = [list(d) for d in slide._wsi.level_dimensions]
            for size in (2048, 4096, 8192):
                try:
                    slide.get_thumbnail(size=(size, size))
                    r[f"thumb_{size}"] = "ok"
                except Exception as e:
                    r[f"thumb_{size}"] = str(e)[:300]
        except Exception:
            r["error"] = traceback.format_exc()[-1500:]
        out[label] = r
    return out


@app.function(image=ectil_image, gpu="A10G", cpu=4, memory=16384, timeout=3600,  # noqa: F821
              volumes={"/pilot": volume, "/raw": slides_volume})
def ectil_bisect(filename: str):
    """Replay run_ectil's setup steps in order, testing ECTIL's thumbnail read after each."""
    import importlib.util
    import traceback
    log = []

    def attempt(step):
        from dlup import SlideImage
        try:
            slide = SlideImage.from_file_path(Path("/raw") / filename)
            size = 4096
            slide.get_thumbnail(size=(size, size))
            log.append([step, "ok"])
        except Exception as e:
            log.append([step, str(e)[:160]])
    attempt("fresh")
    import torch
    from torch import nn
    from torchvision import models
    attempt("imports")
    torch.manual_seed(0)
    torch.set_num_threads(4)
    attempt("threads")
    sha256(Path("/raw") / filename)  # noqa: F821
    attempt("sha256")

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    prefix = "/opt/ectil/ectil/"
    load("mean_mil", prefix + "models/components/mean_mil.py")
    load("attention", prefix + "models/components/attention.py")
    background = load("background", prefix + "utils/background.py")
    attempt("ectil_modules")
    encoder = models.resnet50(weights=None)
    encoder.fc = nn.Identity()
    encoder.load_state_dict(torch.load("/pilot/models/retccl_best_ckpt.pth", map_location="cpu", weights_only=True), strict=True)
    encoder.eval().cuda()
    attempt("cuda_model")
    from dlup import SlideImage
    try:
        background.get_mask(SlideImage.from_file_path(Path("/raw") / filename), background.AvailableMaskFunctions.fesi)
        log.append(["get_mask_fesi", "ok"])
    except Exception:
        log.append(["get_mask_fesi", traceback.format_exc()[-800:]])
    return log


@app.function(image=ectil_image, gpu="A10G", cpu=4, memory=16384, timeout=3600,  # noqa: F821
              volumes={"/pilot": volume, "/raw": slides_volume})
def ectil_import_order(filename: str, variant: str):
    """Thumbnail read after run_ectil's exact import sequence (variant 'exact') or subsets."""
    if variant == "preload_exact":
        import pyvips
        pyvips.Image.openslideload(str(Path("/raw") / filename), level=3).crop(0, 0, 512, 512).write_to_memory()
        variant = "exact"
    if variant in ("exact", "no_pil"):
        import numpy as np  # noqa: F401
        import torch  # noqa: F401
        from torch import nn  # noqa: F401
        from torchvision import models, transforms  # noqa: F401
    if variant in ("exact", "no_pil", "dlup_dataset_only"):
        from dlup import SlideImage  # noqa: F401
        from dlup.data.dataset import TiledROIsSlideImageDataset  # noqa: F401
        from dlup.tiling import GridOrder, TilingMode  # noqa: F401
    if variant in ("exact", "pil_only"):
        from PIL import Image  # noqa: F401
    from dlup import SlideImage
    try:
        SlideImage.from_file_path(Path("/raw") / filename).get_thumbnail(size=(4096, 4096))
        return [variant, "ok"]
    except Exception as e:
        return [variant, str(e)[:200]]


@app.function(image=mutils_image, timeout=300)  # noqa: F821
def mutils_source(start: int = 360, end: int = 420):
    import hashlib as _h
    p = Path("/home/MuTILs_Panoptic/mutils_panoptic/MuTILsInference.py")
    text = p.read_text()
    lines = text.splitlines()
    return {"sha256": _h.sha256(text.encode()).hexdigest(), "n_logger_refs": text.count("self.logger"),
            "has_logging_import": "import logging" in text,
            "snippet": "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines[start:end], start))}


@app.function(image=ectil_image, volumes={"/raw": slides_volume}, timeout=600)  # noqa: F821
def probe(filename: str):
    import openslide
    with openslide.OpenSlide("/raw/" + filename) as s:
        props = {k: v for k, v in s.properties.items() if k.startswith(("openslide.", "tiff."))}
        return {"filename": filename, "dimensions": s.dimensions, "levels": s.level_count,
                "downsamples": s.level_downsamples, "properties": props}


@app.function(image=ectil_image, volumes={"/tiger": volume, "/raw": slides_volume}, timeout=1800, max_containers=8)  # noqa: F821
def prepare_tiles(row: dict):
    """Modular-runner core sampler, mirroring prepare_tiles.py (32 farthest-point 1024-px cores, 64-px halo)."""
    import math

    import numpy as np
    import openslide
    from PIL import Image, ImageDraw
    key = row["image_id"]
    out = Path("/tiger/modular-20261022/inputs")
    folder = out / key
    folder.mkdir(parents=True, exist_ok=True)
    path = Path("/raw") / row["filename"]
    assert _sha(path) == row["sha256"], key
    tiles = []
    with openslide.OpenSlide(str(path)) as wsi:
        mpp = [float(wsi.properties["openslide.mpp-x"]), float(wsi.properties["openslide.mpp-y"])]
        width, height = wsi.dimensions
        thumb = wsi.get_thumbnail((2048, 2048)).convert("RGB")
        a = np.asarray(thumb)
        fg = (a.max(2).astype(float) - a.min(2) > 20) & (a.mean(2) < 235)
        tw, th = thumb.size
        candidates = []
        for y in range(0, height - 1024 + 1, 1024):
            for x in range(0, width - 1024 + 1, 1024):
                x0, x1 = int(x * tw / width), max(int((x + 1024) * tw / width), int(x * tw / width) + 1)
                y0, y1 = int(y * th / height), max(int((y + 1024) * th / height), int(y * th / height) + 1)
                fraction = float(fg[y0:y1, x0:x1].mean())
                if fraction >= .35:
                    candidates.append((x, y, fraction))
        assert candidates, key
        points = np.array([[x / width, y / height] for x, y, f in candidates])
        selected = [int(np.argmin(((points - .5) ** 2).sum(1)))]
        distance = np.full(len(points), np.inf)
        while len(selected) < min(32, len(points)):
            distance = np.minimum(distance, ((points - points[selected[-1]]) ** 2).sum(1))
            distance[selected] = -1
            selected.append(int(np.argmax(distance)))
        draw = ImageDraw.Draw(thumb)
        for index in sorted(selected, key=lambda j: (candidates[j][1], candidates[j][0])):
            x, y, fraction = candidates[index]
            halo = 64
            tile_id = f"{key}_x{x:06d}_y{y:06d}"
            img = wsi.read_region((x - halo, y - halo), 0, (1152, 1152)).convert("RGBA")
            background = Image.new("RGBA", img.size, "white")
            background.alpha_composite(img)
            img = background.convert("RGB")
            destination = folder / (tile_id + ".png")
            img.save(destination)
            tiles.append({"tile_id": tile_id, "slide_key": key, "slide": row["filename"], "source_sha256": row["sha256"],
                          "image_path": str(destination.relative_to(out)), "image_sha256": _sha(destination),
                          "halo_pixels": 64, "origin_level0_xy": [x, y], "mpp_xy": mpp, "core_shape_yx": [1024, 1024],
                          "foreground_fraction_thumbnail": fraction, "candidate_tissue_group": "breast",
                          "annotation_reviewed": False, "clinical_stil_percent": None})
            draw.rectangle([x * tw / width, y * th / height, (x + 1024) * tw / width, (y + 1024) * th / height], outline="red", width=2)
        thumb.save(folder / "sampling_map.png")
    inventory = {"slide": row["filename"], "slide_key": key, "source_sha256": row["sha256"], "candidate_tiles": len(candidates),
                 "sampled_tiles": len(selected), "sampled_core_area_mm2": len(selected) * 1024 ** 2 * math.prod(mpp) / 1e6}
    volume.commit()
    return {"tiles": tiles, "inventory": inventory}


@app.function(image=util_image, volumes={"/tiger": volume}, timeout=600)
def write_tile_manifest(tiles: list, inventory: list):
    manifest = {"schema_version": 1, "sampling": {
        "method": "deterministic farthest-point spatial sampling from a disjoint 1024-pixel grid", "target_tiles_per_slide": 32,
        "thumbnail_tissue_fraction_minimum": .35, "tissue_rule": "RGB range >20 and mean<235",
        "selection_independent_of_model_TIL_outputs": True, "source": "TIGER wsitils development split, level 0 (0.5 um/px)",
        "purpose": "benchmark baseline of the committed modular runner", "eligible_tumor_coverage": "unknown"},
        "slides": inventory, "tiles": tiles}
    path = Path("/tiger/modular-20261022/inputs/tile_manifest.json")
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise FileExistsError("a different TIGER tile manifest already exists; use a new layout")
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    volume.commit()
    return _sha(path)


@app.function(image=util_image, volumes={"/tiger": volume}, timeout=600)
def collect(run_id: str = RUN_ID):
    """Compact terminal receipts for every pipeline (no large artifacts)."""
    volume.reload()
    out = {"ectil": [], "mutils": [], "modular": []}
    for model in ("ectil", "mutils"):
        for receipt in sorted((Path("/tiger") / run_id / model).glob("*/run_manifest.json")):
            r = json.loads(receipt.read_text())
            r.pop("runner_original_code", None)
            r.pop("artifacts", None)
            out[model].append(r)
    for receipt in sorted((Path("/tiger/modular-20261022") / run_id).glob("*/classification_manifest.json")):
        r = json.loads(receipt.read_text())
        seg = json.loads((receipt.parent / "run_manifest.json").read_text())
        r["segmentation_status"] = seg.get("status")
        r["tiles"] = [{k: v for k, v in t.items() if k != "thresholds"} for t in r.get("tiles", [])]
        r.pop("artifacts", None)
        out["modular"].append(r)
    for seg in sorted((Path("/tiger/modular-20261022") / run_id).glob("*/run_manifest.json")):
        if not (seg.parent / "classification_manifest.json").exists():
            s = json.loads(seg.read_text())
            out["modular"].append({"slide_key": s.get("slide_key"), "segmentation_status": s.get("status"),
                                   "status": "classification_not_run", "error": s.get("error")})
    return out


def _dev_ids(slides):
    split = json.loads(SPLIT_PATH.read_text())
    dev = sorted(s["image_id"] for s in split["slides"] if s["split"] == "development")
    locked = {s["image_id"] for s in split["slides"] if s["split"] == "locked_test"}
    chosen = dev if slides == "all" else slides.split(",")
    assert not set(chosen) & locked, "locked-test slides are not scored by baselines"
    assert set(chosen) <= set(dev), "unknown slide id"
    return chosen


def _benchmark_spend_today():
    """Today's Modal spend for this benchmark's apps (names diana-stil-tiger-* / tiger-*)."""
    import subprocess
    out = subprocess.run(["modal", "billing", "report", "--for", "today", "--json"], capture_output=True, text=True, check=True).stdout
    return sum(float(r["cost"]) for r in json.loads(out) if r["description"].startswith(("diana-stil-tiger", "tiger-")))


def _mutils_budget_run(rows, order, run_id, cap, rate_per_hour, reserve, max_concurrent, min_slide_minutes, log_path):
    """Run MuTILs slides in frozen order without letting projected spend pass `cap`.

    Committed spend = billed spend at launch + wall time of finished and running
    slides x `rate_per_hour` (A10G + 4 CPU + 24 GiB, rounded up). A slide starts only
    if committed spend plus one expected slide (max of `min_slide_minutes` and the
    median finished duration) plus `reserve` stays within the cap.
    """
    import statistics
    import time
    baseline = _benchmark_spend_today()
    queue = [i for i in order if i in rows]
    running, done = {}, {}
    state = {"cap": cap, "baseline_billed": baseline, "rate_per_hour": rate_per_hour, "reserve": reserve, "order": order}

    def committed(now):
        spent = sum(d["wall_minutes"] for d in done.values()) + sum((now - s) / 60 for _, s in running.values())
        return baseline + spent / 60 * rate_per_hour

    def write(now):
        state.update(committed_estimate=committed(now), done=done, running=sorted(running),
                     not_run=[i for i in queue if i not in done and i not in running])
        log_path.write_text(json.dumps(state, indent=2, default=str) + "\n")

    while queue or running:
        now = time.time()
        durations = [d["wall_minutes"] for d in done.values() if d["status"] != "returned_existing"]
        expected = max(min_slide_minutes, statistics.median(durations) if durations else 0) / 60 * rate_per_hour
        while queue and len(running) < max_concurrent and committed(now) + expected + reserve <= cap:
            image_id = queue.pop(0)
            running[image_id] = (run_mutils.spawn(dict(rows[image_id], patch_no_nuclei_log=True), run_id), now)
            print("start", image_id, f"committed ${committed(now):.2f}", flush=True)
        if not running:
            break
        time.sleep(30)
        for image_id, (call, started) in list(running.items()):
            try:
                result = call.get(timeout=0)
            except TimeoutError:
                continue
            except Exception as e:
                result = {"status": "failed", "error": repr(e)[:500]}
            wall = (time.time() - started) / 60
            status = result.get("status")
            if status == "completed" and wall < 2:
                status = "returned_existing"
            done[image_id] = {"status": status, "wall_minutes": wall, "n_analyzed_rois": result.get("n_analyzed_rois"),
                              "error": (result.get("error") or "")[-400:]}
            del running[image_id]
            print("done", image_id, status, f"{wall:.1f} min", f"committed ${committed(time.time()):.2f}", flush=True)
        write(time.time())
    state["not_run"] = queue
    state["billed_at_end"] = _benchmark_spend_today()
    write(time.time())
    return state


@app.local_entrypoint()
def main(stage: str = "assets", slides: str = "all", run_id: str = RUN_ID,
         out: str = "private/stil/benchmark-20261022/baselines"):
    local = Path(out)
    local.mkdir(parents=True, exist_ok=True)
    for name, digest_ in FROZEN_SHA256.items():
        assert _sha(FROZEN_DIR / name) == digest_, name

    def save(name, obj):
        (local / name).write_text(json.dumps(obj, indent=2, default=str) + "\n")
        print("wrote", local / name)

    ids = _dev_ids(slides)
    rows_path = local / "slide_rows.json"
    if stage == "assets":
        save("assets.json", copy_assets.remote())
        rows = list(link_slide.map(_dev_ids("all"), order_outputs=True))
        save("slide_rows.json", rows)
        return
    rows = {r["image_id"]: dict(r, stain="H&E") for r in json.loads(rows_path.read_text())}
    chosen = [rows[i] for i in ids]
    if stage == "mutils-source":
        save("mutils_source.json", mutils_source.remote())
        return
    if stage == "importorder":
        variants = ["preload_exact", "exact"]
        save("ectil_import_order.json", list(ectil_import_order.starmap([(chosen[0]["filename"], v) for v in variants])))
    elif stage == "bisect":
        save("ectil_bisect.json", [ectil_bisect.remote(r["filename"]) for r in chosen])
    elif stage == "dlupcheck":
        save("dlup_check.json", [dlup_check.with_options(cpu=4).remote(r["filename"], r["mpp_x"], tf) for r in chosen for tf in (False, True)])
    elif stage == "fullcheck":
        save("full_level_check.json", [full_level_check.remote(r["filename"]) for r in chosen])
    elif stage == "readers":
        save("reader_check.json", [reader_check.remote(r["filename"]) for r in chosen])
    elif stage == "probe":
        save("probe.json", [probe.remote(r["filename"]) for r in chosen])
    elif stage == "annotate":
        updated = {r["image_id"]: r for r in annotate_slide.map(chosen, order_outputs=True)}
        merged = [dict(updated.get(i, r)) for i, r in rows.items()]
        for r in merged:
            r.pop("stain", None)
        save("slide_rows.json", merged)
    elif stage == "mutils-budget":
        order_doc = json.loads((SPLIT_PATH.parent / "stil_tiger_mutils_order.json").read_text())
        order = order_doc["first_wave"] + order_doc["remaining"]
        assert set(order) == set(_dev_ids("all"))
        result = _mutils_budget_run(rows, order, run_id, cap=40.0, rate_per_hour=1.6, reserve=0.5, max_concurrent=4,
                                    min_slide_minutes=30, log_path=local / "mutils_budget_progress.json")
        print(json.dumps({k: result[k] for k in ("baseline_billed", "committed_estimate", "billed_at_end", "not_run")}, default=str))
    elif stage in ("ectil", "mutils", "mutils-patched"):
        fn = run_ectil if stage == "ectil" else run_mutils
        if stage == "mutils-patched":
            chosen = [dict(r, patch_no_nuclei_log=True) for r in chosen]
        results = []
        for result in fn.map(chosen, [run_id] * len(chosen), order_outputs=False):
            results.append({k: v for k, v in result.items() if k not in ("artifacts", "runner_original_code")})
            print(stage, result["filename"], result["status"], flush=True)
        save(f"{stage}_{run_id}_{slides.replace(',', '-')[:40]}.json", results)
    elif stage == "tiles":
        tiles, inventory = [], []
        for result in prepare_tiles.map(chosen, order_outputs=True):
            tiles += result["tiles"]
            inventory.append(result["inventory"])
        save("tile_inventory.json", inventory)
        print("tile manifest sha256", write_tile_manifest.remote(tiles, inventory))
    elif stage == "modular":
        seg = list(segment.starmap([(r["image_id"], 0, run_id) for r in chosen], order_outputs=False, return_exceptions=True))
        print("segmentation", [s.get("status") if isinstance(s, dict) else repr(s)[:200] for s in seg], flush=True)
        done = [s["slide_key"] for s in seg if isinstance(s, dict) and s.get("status") == "completed_two_components"]
        cls = list(classify.starmap([(k, run_id) for k in done], order_outputs=False, return_exceptions=True))
        print("classification", [c.get("status") if isinstance(c, dict) else repr(c)[:200] for c in cls], flush=True)
    elif stage == "collect":
        save(f"collected_{run_id}.json", collect.remote(run_id))
    else:
        raise SystemExit("unknown stage " + stage)
