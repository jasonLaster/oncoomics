# TIGER sTIL benchmark runbook

How to reproduce the development-split baselines defined in the [benchmark specification](stil-tiger-benchmark.md). All storage is private Modal volumes; the public repository holds code, the frozen split and metric definitions only. Results go under `private/stil/benchmark-<date>/`.

## Volumes

| Volume | Contents |
| --- | --- |
| `diana-stil-tiger-benchmark` | `source/` staged TIGER files (development wsitils slides and masks, wsirois tissue-cells ROIs), `models/` pinned weights copied from the pilot volume, run outputs |
| `diana-stil-tiger-slides-dev` | The 40 development slides only, flat, with the MPP metadata adapter applied. Runners mount it at `/raw` |
| `diana-stil-tiger-components` | ROI tiles and modular-runner outputs for the component checks |

Locked-test slides are not staged. The stager and every adapter refuse locked-test IDs.

## Steps

```sh
# 0. Freeze check
python scripts/stil_tiger_split.py --scores <dir>/tiger-til-scores-wsitils.csv --check

# 1. Stage development inputs (CPU)
modal run scripts/modal/stil_tiger_stage.py --part wsitils-dev
modal run scripts/modal/stil_tiger_stage.py --part rois

# 2. Frozen runner copies (hash-pinned in the adapter)
mkdir -p .runs/stil-tiger-benchmark/frozen
git show a1764b5a:scripts/modal/stil_modular_execute.py > .runs/stil-tiger-benchmark/frozen/stil_modular_execute_a1764b5a.py
cp scripts/modal/stil_batch.py .runs/stil-tiger-benchmark/frozen/stil_batch.py

# 3. Assets, slide copies, MPP metadata adapter, modular tiles
modal run scripts/modal/stil_tiger_baselines.py --stage assets
modal run scripts/modal/stil_tiger_baselines.py --stage annotate --slides all
modal run scripts/modal/stil_tiger_baselines.py --stage tiles --slides all

# 4. Slide-level baselines (GPU)
modal run scripts/modal/stil_tiger_baselines.py --stage ectil --slides all
modal run scripts/modal/stil_tiger_baselines.py --stage modular --slides all
modal run scripts/modal/stil_tiger_baselines.py --stage mutils-patched --slides all
modal run scripts/modal/stil_tiger_hovernet.py --slides all
modal run scripts/modal/stil_tiger_baselines.py --stage collect

# 5. Component checks on wsirois ROIs (GPU)
modal run scripts/modal/stil_tiger_components.py --stage prepare
modal run scripts/modal/stil_tiger_components.py --stage run
modal run scripts/modal/stil_tiger_components.py --stage evaluate
modal run scripts/modal/stil_tiger_hovernet.py --rois   # needs components/tiger-coco.json locally

# 6. Metrics and plots (local)
python scripts/stil_tiger_evaluate.py --scores <dir>/tiger-til-scores-wsitils.csv \
  --collected private/stil/benchmark-<date>/baselines/collected_tiger-dev-baseline-v1.json \
  --hovernet private/stil/benchmark-<date>/baselines/hovernet_slides.json --out private/stil/benchmark-<date>
python scripts/stil_tiger_components_summary.py --dir private/stil/benchmark-<date>/components
```

## What the adapters change, and what they do not

The ECTIL, MuTILs and modular inference functions run from hash-pinned copies of the existing runners: [`stil_batch.py`](../../scripts/modal/stil_batch.py) and `stil_modular_execute.py` at commit `a1764b5a`. [`stil_tiger_baselines.py`](../../scripts/modal/stil_tiger_baselines.py) parses those files and executes the selected functions unchanged. It rebinds only their storage: `/pilot` and `/data` to the benchmark volume, and `/raw` to the slides-only volume. The modular core sampler mirrors the existing `prepare_tiles.py` rule.

Input and runtime accommodations, each recorded in receipts:

- **MPP metadata.** TIGER TIFFs store pixel size only in TIFF resolution tags, which OpenSlide 3.4 does not report. [`diana_omics.tiff_mpp`](../../src/diana_omics/tiff_mpp.py) appends an Aperio-style ImageDescription to IFD 0 and leaves all original bytes in place. The `annotate` stage checks that OpenSlide level-0 regions and thumbnails are pixel-identical to the original file. Actual MPP is 0.4567 (JB) and 0.4851 (RUMC), not the nominal 0.5.
- **ECTIL JPEG decoding.** In the ECTIL image, importing torch and then `dlup.data.dataset` before OpenSlide's first decode makes TIGER's JPEG-tables tiles fail ("Huffman table 0x00 was not defined"). The wrapper decodes one tile through pyvips before calling the frozen runner.
- **MuTILs no-nuclei crash** (opt-in `mutils-patched` stage). The pinned container's `ROIPostProcessor.run_roi` logs through an unset `self.logger` when an ROI has no nuclei, which aborts the slide. The patch changes only that log call and records file hashes in `container_patch.json`.
- **Step-10 HoVer-Net** is a port of private scripts, not a frozen import: [`stil_tiger_hovernet.py`](../../scripts/modal/stil_tiger_hovernet.py). It generalizes the hard-coded 0.263 µm/px scale, keeps 164-µm tiles, and samples at most 300 tissue tiles per slide. StarDist is omitted because it was not an sTIL input.

The modular runner samples 32 cores of 1024 px at level 0. At TIGER's ~0.46–0.49 µm/px, each core covers about 3× the tissue area it did on the 0.263 µm/px local slides. This is a property of the committed runner and is reported, not corrected.
