# Modular H&E research execution and verification

The bounded runner in [stil_modular_execute.py](../../scripts/modal/stil_modular_execute.py) runs VISTA-PATH stromal segmentation, Cellpose 3 nucleus segmentation and CytoFormer cell classification on supplied image tiles in private Modal storage. The collector and verifier recover its artifacts and independently reconstruct the area calculations. This workflow supports development and error review; reviewed tumor-associated eligibility and clinical sTIL remain separate requirements.

The [candidate configuration](../../manifests/stil_modular_pipeline.json) describes the endpoint and review requirements. The [asset lock](../../manifests/stil_modular_assets.lock.json) records the exact upstream revisions, file sizes and SHA256 identities. It contains no weights or patient results. Code and weights have distinct terms; the upstream VISTA-PATH and CytoFormer research restrictions continue to apply.

## Runtime and asset preparation

Use the authenticated Modal workspace and existing private volume configured near the top of the runner. This prototype deliberately fixes its volume name and remote prefix; adapt those constants for another authorized environment. It never needs a patient-data credential or Hugging Face token inside a GPU worker.

The local directories used by the image builder are:

- `.runs/stil-modular-20261022/vendor/VISTA-PATH`, checked out at `88c0305af8593ed72d4641d7dc87822ec463035d`.
- `.runs/stil-modular-20261022/vendor/CytoFormer`, checked out at `36b667e40a440d0a8faea8296709aadfcffe6616`.

Obtain each asset in the lock from its recorded repository and revision through authorized access. Check its size and SHA256 before transfer. Arrange the base assets at their locked `relative_path` under a local assets directory and write the `base_assets` list as `asset_manifest.json` there. Place the CytoFormer checkpoint and matching `organ_celltype_map.json` under `CytoFormer/`. The taxonomy SHA256 must be `8dc8613c48f5fcad29b263f8c5e3e4a8e4588f2f94cef7c9628c738716eeea73`.

Upload those files to `/models/modular-20261022/` in the private volume. Run the provision stage once to obtain the Cellpose nuclei checkpoint and its version/hash receipt. Verify that receipt against the lock before segmentation. GPU workers run with Hugging Face offline mode and load assets from the volume. No separate UNI2-h foundation checkpoint is required: the complete CytoFormer checkpoint loads strictly over the model architecture.

The image pins the principal scientific dependencies, including torch 2.5.1, transformers 4.46.1, Cellpose 3.1.1.1, timm 1.0.9 and the effective NumPy 2.0.2. Runtime versions and actual GPU names are captured in stage receipts. Modal may provide an A100 with greater memory than the requested minimum.

## Input contract and sampling

Place `tile_manifest.json` and original RGB image tiles under `/modular-20261022/inputs/`. Keep an identical local copy for independent verification. A tile entry contains:

```json
{
  "tile_id": "s00_x001024_y002048",
  "slide_key": "s00",
  "slide": "operator-defined source label",
  "source_sha256": "SHA256 of the original whole-slide file",
  "image_path": "s00/s00_x001024_y002048.png",
  "image_sha256": "SHA256 of the extracted RGB tile",
  "origin_level0_xy": [1024, 2048],
  "mpp_xy": [0.5, 0.5],
  "halo_pixels": 64,
  "core_shape_yx": [1024, 1024],
  "candidate_tissue_group": "breast",
  "annotation_reviewed": false,
  "clinical_stil_percent": null
}
```

The manifest has top-level `tiles`, `slides` and `sampling` fields. SHA256 placeholders above must be replaced by actual digests. Each source image must be 1152 × 1152 pixels: a 1024-pixel core surrounded by a 64-pixel halo. The origin refers to the core in the original level-zero coordinate system. Preserve measured x/y MPP and the original unmasked RGB context. Source hashes must be verified against the original whole-slide files before tile extraction; verifying the extracted images alone cannot establish that upstream step.

The exercised development design uses 32 spatially distributed nonoverlapping cores per source slide. A thumbnail foreground rule selects candidates from a disjoint grid; deterministic farthest-point sampling spreads the selected cores over the slide. It is independent of TIL predictions but does not establish representative tumor-associated coverage. Related sections from one patient remain one patient for validation purposes.

The provisional `axillary_sentinel_node` group selects the `lymph_node` classification head. Other supplied groups use `breast`; an operator must confirm that assignment before interpretation. Nodal tissue requires separate review. The public author demo is a mechanical smoke input and may overlap model development data.

## Image quality before inference

Visual review exposed an upstream sampling defect: the simple color-foreground rule admitted blue annotation-like regions. Some became no-calls, while some flagged regions remained in the exploratory denominators. This limits the current sample's interpretation independently of successful file and arithmetic checks.

[stil_modular_image_qc.py](../../scripts/stil_modular_image_qc.py) provides a review flag that can run before inference:

```sh
python scripts/stil_modular_image_qc.py \
  --inputs private/stil/modular-execution-20261022/inputs \
  --out private/stil/new-image-review.json
```

The rule flags a core when at least 5% of pixels satisfy B−R>60, B−G>40 and B>120 on the RGB 0–255 scale. It was introduced after visual review of the development run and is an unvalidated heuristic. It neither identifies every artifact nor establishes assessable tissue. Review pen, blur and other artifacts and freeze revised sampling on annotated development tissue before another comparison. Do not silently discard cases or reinterpret the original ratios as corrected scores.

With `--run <collected-run>`, the tool also joins detected-nucleus and call status so a reviewer can see which flagged regions contributed to the preserved experimental ratios. The tool checks source tile hashes and never changes masks or scores. Its only additional dependency beyond NumPy is Pillow.

## Execute the stages

Use a new immutable run ID for a new configuration. The runner returns an existing completed stage only when its input-manifest identity and output hashes match. Incomplete or failed paths require a new run ID; retain their artifacts.

```sh
modal run scripts/modal/stil_modular_execute.py --stage provision
modal run scripts/modal/stil_modular_execute.py --stage segment --slide-key public-smoke --run-id public-smoke-v1
modal run scripts/modal/stil_modular_execute.py --stage classify --slide-key public-smoke --run-id public-smoke-v1
```

Inspect terminal manifests and a small private pilot before the larger sample. For the nine-source prototype, `batch` and `classify-batch` dispatch keys `s00` through `s08`. Other inputs can use the single-key stages. Keep the local controller alive during mapped batches, including when using Modal's detached option.

```sh
modal run scripts/modal/stil_modular_execute.py --stage batch --run-id development-v1
modal run scripts/modal/stil_modular_execute.py --stage classify-batch --run-id development-v1
modal run scripts/modal/stil_modular_execute.py --stage bundle --slide-key all --run-id development-v1
```

Check the stage receipt's actual status rather than relying only on the controller exit code. A successful classification receipt has `status: completed_experimental_comparison`; a successful segmentation receipt has `status: completed_two_components`. The bundle requires both. The bundle's default `all` also refers to the prototype's nine keys; pass a single key for another source or the public demo.

## Preserve and compare both stromal masks

The ROI adapter uses ordered Tumor and Stroma text prompts, 512-pixel model input and no boxes. It preserves independent class probabilities and a per-ROI Otsu threshold for each class, followed by the upstream area-ordered mask merge. It does not reproduce a whole-slide global-Otsu workflow.

During development, a weak tumor probability map could become a large binary region under per-ROI Otsu and overwrite stronger stroma. The diagnostic comparison therefore retains the original `tissue_labels.npy` and adds `tissue_labels_competition.npy`: the class with larger probability wins, the larger probability must be at least 0.5, and exact ties remain unassigned. It operates on saved float16 probability maps, so rounding ties also remain unassigned. This alternative was selected from mask/probability behavior before the cell-based ratios. It is a sensitivity analysis, not a validated anatomical correction.

Cellpose runs on normalized hematoxylin optical density over the full halo tile, using an assumed 8 µm nuclear diameter, flow threshold 0.4 and cell probability threshold 0. Its integer instance masks are then cropped to the disjoint core. CytoFormer receives approximately 56 µm of original RGB around the halo centroid, resized to 224 × 224 with ImageNet normalization. A nucleus whose context exceeds the saved halo remains Unknown.

For each mask variant, the raw diagnostic is:

`100 × lymphocyte and plasma-cell nuclear area in predicted stroma / predicted stromal area`.

The classifier also saves probabilities and sensitivity calculations at 0, 0.5, 0.7 and 0.9. These thresholds are development heuristics, not calibrated confidence. Low-probability cells stay in the stromal denominator, and unresolved nuclear area is retained. No detected nuclei or no predicted stroma produces a tile no-call; such a tile is excluded from that mask's aggregate rather than assigned zero. Sum physical areas before dividing. Objects crossing adjacent cores may appear in both instance counts, while pixel-area ownership stays disjoint.

The diagnostic fields `exploratory_model_stroma_nuclear_area_percent` and `competition_model_stroma_nuclear_area_percent` explicitly use **predicted** stroma. The reviewed `nuclear_area_proxy_percent` and `clinical_stil_percent` fields remain null. The separate [reviewed-mask adapter](../../src/diana_omics/stil_modular.py) continues to require real eligibility annotations and its declared acceptance gates.

## Collect and independently verify

The bundle compresses all masks, probabilities, nucleus metadata, classification records, review images and terminal receipts with a member-level manifest. Download it through the collector using a new local destination:

```sh
python scripts/stil_modular_collect.py \
  --volume diana-stil-pilot-20261021 \
  --receipt /modular-20261022/archives/development-v1-all-full.receipt.json \
  --out private/stil/new-collection
python scripts/stil_modular_verify.py \
  --run private/stil/new-collection \
  --inputs private/stil/modular-execution-20261022/inputs \
  --expected-slides 9
```

The collector needs the Modal SDK. The verifier needs NumPy and can run independently of the model runtime. The collector checks the archive SHA256 and every member's size/hash before accepting the collection. The verifier checks source and tile joins, disjoint ownership, halo/core consistency, exact nucleus/classification IDs, finite normalized probabilities, organ assignment, both mask calculations, all probability thresholds and area aggregation. The public demo uses `--expected-slides 1`.

These checks establish artifact custody and arithmetic, not model accuracy. The first segmentation batch omitted its runner-source hash, although asset and output hashes and settings were captured; the current runner records the script hash for future segmentation. Classification receipts record their exact executed-source hash. Keep those receipts with the private packet rather than substituting the latest repository code for the code actually executed.

## Interpretation boundary

A development packet should show both mask variants, threshold sensitivity, no-calls, unresolved nuclear area, sampling maps and source-bound overlays. Keep MuTILs TIL-rich-region ratios, ECTIL regression predictions and the modular nuclear-area proxy in distinct columns. Do not average them into a patient score.

The next evidence starts with reviewed artifact-aware tissue sampling, then blinded annotation of stromal eligibility, nucleus instances and cell identities on the same coordinates, followed by an evaluation on independent patients with prespecified acceptance criteria. Post-treatment breast tissue and nodal tissue need their own eligibility review. Private patient results, original correspondence, model binaries and vendored upstream code remain outside the public repository.
