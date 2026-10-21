# Breast H&E stromal TIL scoring plan and Rosalind capabilities

Prepared October 21, 2026. Scope: research assessment of stromal tumor-infiltrating lymphocytes in breast-cancer H&E whole-slide images, including a separate validation path for post-treatment residual disease.

The recommended pilot pairs **MuTILs for inspectable tissue and nucleus predictions with ECTIL for a separate slide-level sTIL estimate**, reviewed against breast-pathologist scores. Rosalind can coordinate the scientific workflow, and the installed Slide Viewer can support image inspection and bounded analyses. A complete whole-slide scoring runner, output adapter, and validation dataset still need to be assembled. This is a research plan; no patient slides were scored.

**The most consequential issue is measurement equivalence:** neither a lymphocyte count nor a model output named “TIL score” automatically measures the percentage of tumor-associated stromal area occupied by mononuclear inflammatory cells.

# Decision and measurement definition

The initial decision is whether an automated score is reliable enough to include beside a pathologist score in a research reviewer packet. Treatment selection, prognosis for an individual patient, and trial eligibility are separate questions.

The intended visual endpoint is:

**sTIL percentage = stromal area occupied by mononuclear inflammatory cells, including lymphocytes and plasma cells, divided by total assessable intratumoral stromal area, multiplied by 100.**

A breast pathologist should define the invasive-tumor boundary and exclusions, including in-situ disease, necrosis, artifacts, and inflammation associated with unrelated structures. Average the eligible tumor region rather than selecting only inflammatory hotspots. Pretreatment and post-treatment specimens need separate identities and assessment rules. [International TILs Working Group recommendations](https://pmc.ncbi.nlm.nih.gov/articles/PMC6267863/)

Three endpoints must remain distinct: the pathologist’s visual sTIL percentage; a computational area or density measurement with an explicit formula; and a regressed prediction of a pathologist score. H&E sTIL, multiplex immune-cell fractions, and cells per square millimeter should be reported separately.

For an area-based aggregation, sum eligible immune-occupied area and eligible stromal area before dividing. Do not take an unweighted mean of tile percentages when tiles contain different amounts of stroma. This aggregation rule does not automatically reproduce a model’s native scoring algorithm.

# Open source model shortlist

| Option | Recommended role | Principal qualification |
| --- | --- | --- |
| MuTILs and PanopTILs | Primary explainable research pipeline | Joint tissue and nucleus segmentation supports review of why a score changes; choose and document the exact computational endpoint. |
| ECTIL | Independent slide-level score predictor | Predicts sTIL from image features; absolute score calibration and the exact released checkpoint matter. |
| Spotlight TIGER | Optional third comparator | Breast-specific segmentation and TIL detection; survival leaderboard performance is a different endpoint from percentage agreement. |
| HoVer-Net through TIAToolbox | Modular alternative for a custom pipeline | Nucleus segmentation and classification need a separately validated tumor/stroma component and scoring implementation. |
| CellViT or CellViT++ | Candidate cell segmentation and classification component | Does not by itself establish an sTIL scoring workflow; verify the chosen classifier, backbone, weights, and licenses. |

This ordering reflects suitability for the proposed pilot, not a head-to-head accuracy ranking. [MuTILs repository](https://github.com/PathologyDataScience/MuTILs_Panoptic), [ECTIL repository](https://github.com/NKI-AI/ectil), [Spotlight TIGER repository](https://github.com/Spotlight-Pathology/spotlight-tiger), [TIAToolbox](https://github.com/TissueImageAnalytics/tiatoolbox), [CellViT++](https://github.com/TIO-IKIM/CellViT-plus-plus).

## MuTILs

MuTILs jointly predicts tissue regions and nuclei. Its paper reports lymphocyte-detection AUROC of 0.93, tumor-associated-stroma Dice of 0.81, and Spearman correlation with two pathologists of 0.58–0.61. These are component and association metrics, not interchangeable measures of score accuracy. [Peer-reviewed MuTILs study](https://www.nature.com/articles/s41523-024-00663-1)

The repository provides an MIT code license, linked pretrained weights, a CUDA Docker workflow, masks, nucleus metadata, ROI summaries, and slide-level features. Preserve those native outputs. Before labeling a result “sTIL %,” inspect its formula, numerator, denominator, units, ROI selection, and plasma-cell handling. The publication evaluates several computational TIL measurements, including count-based ratios; a nuclear count or nuclear area is not automatically the visual immune-cell occupied area. [Implementation and outputs](https://github.com/PathologyDataScience/MuTILs_Panoptic)

Use MuTILs first when the practical priority is reviewing stroma segmentation, immune localization, and model errors. Validate native ROI sampling against the intended slide coverage; do not imply that every eligible pixel was scored unless the run establishes that coverage.

## ECTIL

ECTIL now has a peer-reviewed publication in The Lancet Digital Health, November 2025; the earlier characterization as preprint-only was outdated. It directly regresses a slide-level TIL score from pathology image features. The study includes 2,340 patients across six cohorts. [Published ECTIL study](https://doi.org/10.1016/j.landig.2025.100921)

The paper reports external-cohort Pearson correlations of 0.54–0.74 and documents score-range compression and discordant cases. Correlation therefore cannot establish that a raw prediction is an accurate absolute percentage. Calibration must be learned on development data and assessed on independent patients. [Published results and calibration](https://www.sciencedirect.com/science/article/pii/S2589750025001037)

The Apache-2.0 repository exposes feature extraction, pretrained-model retrieval instructions, and inference examples. Record whether the available checkpoint is TCGA-trained, TNBC-trained, or combined; do not attribute combined-model results to a different released checkpoint. Freeze the feature extractor together with the regression model. Its documented CPU path is useful for feasibility, but whole-slide feature extraction still requires a runtime and throughput check. [ECTIL implementation](https://github.com/NKI-AI/ectil)

## Alternatives and endpoint mismatches

Spotlight TIGER reports second place on the challenge survival leaderboard and tied fourth on the computer-vision leaderboard. Its Docker workflow expects a CUDA-compatible GPU and separately downloaded weights. Treat it as an optional comparator after reproducing its score definition and inputs. [Spotlight implementation](https://github.com/Spotlight-Pathology/spotlight-tiger)

TIAToolbox and CellViT++ are useful engineering foundations for a custom cell pipeline. They do not eliminate the need to delineate invasive tumor, distinguish eligible stroma, exclude confounding tissue, and validate the final score. Check code, pretrained weights, training-data terms, and backbone terms separately. [TIAToolbox](https://github.com/TissueImageAnalytics/tiatoolbox), [CellViT++](https://github.com/TIO-IKIM/CellViT-plus-plus)

TILScout computes the fraction of TIL-positive patches within tumor regions. Keep that as a separate immune-mapping endpoint rather than substituting it for breast sTIL percentage. [TILScout study](https://www.nature.com/articles/s41698-025-00866-0)

# Rosalind skills and current capabilities

“Rosalind skills” here includes the Rosalind orchestration skill, specialized installed scientific skills, and local audit skills that can support this workflow. They are not all native Rosalind algorithms. A skill supplies instructions; an executable model, a provisioned runtime, and an evaluated assay are separate assets.

The installed Rosalind skill routes microscopy and pathology to Slide Viewer. It can coordinate literature, methodology, code, and interpretation in the current chat. Invoking it does not select a particular scientific model or establish access to a separate GPT-Rosalind model.

| Skill | Role in this plan | Concrete output | Boundary |
| --- | --- | --- | --- |
| rosalind | Coordinate the question, methods, and evidence | Analysis brief and decision log | Not an H&E segmentation model |
| slide-viewer | Inspect slides, regions, annotations, and supported results | Reviewable views and source-bound annotations | No complete native whole-slide sTIL scoring pipeline |
| pipeline-strategy-sanity | Test method-to-question fit | Endpoint contract and strategy verdict | Does not execute or validate a pathology model |
| pipeline-data-custody-audit | Establish source and annotation trust | Input manifest and custody verdict | Metadata integrity does not prove accuracy |
| pipeline-validation-sanity | Evaluate the exact performance claim | Validation findings and bounded verdict | Requires actual reference scores and outputs |
| pipeline-deployment-governance | Define repeated-use controls | Review responsibilities and release gates | A reviewer packet is not clinical assay clearance |
| paperclip | Retrieve academic papers when its service is available | Methods and source evidence | Local skill exists; its tools are not exposed in this session |
| ngs-analysis-workbench | Optional later integration with sequencing evidence | Separate omics analysis context | H&E scoring is outside its sequencing workflow remit |

The four pipeline audit skills are available local review frameworks. Their existing sequencing-specific command examples should not be presented as pathology validation commands.

## Slide Viewer in detail

The installed Slide Viewer skill and PATHOLOGY.md describe useful but bounded research capabilities:

- Open compatible SVS, tiled TIFF, and supported DICOM whole-slide sources, with source identity and coordinate provenance.

- Inspect regions and annotation or segmentation overlays. Imported results need compatible formats and verified coordinate alignment.

- Measure supplied objects and boundaries; foreground connected components remain candidate regions rather than identified cells.

- Train and apply regularized object or pixel logistic classifiers from explicit labels and declared training and held-out sources.

- Predict nuclei with a pinned StarDist H&E model on regions of at most 512 by 512 pixels, after explicit runtime and model provisioning.

- Evaluate pixel or instance predictions against authorized reference annotations, with metrics limited by the declared annotation coverage.

The StarDist model predicts nuclei, not lymphocyte identity, plasma-cell identity, or whole-cell area. Partial annotations cannot establish whole-field precision or false-positive rates. Fluorescence watershed segmentation requires explicit DNA and cytoplasm channels and is not H&E cell segmentation.

The qualified optional local runtime described by the installed plugin is macOS arm64, CPU-only. The pathology jobs do not automatically install dependencies or fetch weights, and the plugin does not provide whole-slide model inference and stitching. There is no advertised native operation for running MuTILs, ECTIL, HoVer-Net, or CellViT end to end. Those models need a separate runner and an output adapter.

**Practical use:** inspect the input and tumor boundary, review representative error regions, and load aligned overlays from the external scoring pipeline. A successful small-region nucleus run establishes mechanics only; it does not validate slide-level sTIL.

## Audit skills in detail

**Strategy sanity:** establish the chain from research question to H&E input, model endpoint, validation reference, and intended decision. Require a simple baseline: independent pathologist scoring. The present strategy is promising with gaps because the endpoint is defined but local model readiness and target-setting validation remain untested.

**Data custody audit:** preserve the original slide hash; specimen, block, section and timepoint; scanner and staining context; physical pixel calibration; image transformations; and annotation author/version. Split development and testing by patient, keeping serial sections and repeated specimens together. Check overlap with public training cohorts before calling a public dataset external validation.

**Validation sanity:** distinguish a technical smoke run, ROI-level agreement, patient-level external evaluation, and clinical readiness. Require score agreement and failure review, not only association with outcomes. Preserve failed cases and no-calls in the denominator.

**Deployment governance:** initially classify use as research-only or a reviewer packet. Specify who reviews boundaries, adjudicates disagreements, releases the report, and can stop the workflow. Freeze weights, feature extractor, score formula, calibration, and report template. Revalidate consequential changes.

These are review procedures to apply to the proposed pipeline. No specimen custody pass, accuracy verdict, or deployment approval is established by this planning report.

## Literature and compute integrations

Primary-source web research is available now and supports the report. Paperclip has local instructions for paper retrieval, but no corresponding callable tools are exposed here. Rosalind also names Life Sciences Literature and Runpod as possible downstream integrations; that instruction alone does not establish a current connection.

A directory search did not return Runpod or the named Life Sciences Literature integration. It returned Scite as an optional literature integration, currently not installed. The directory results are bounded, so they do not prove those other integrations are unavailable everywhere. No new integration is necessary to complete this report.

For execution, use an approved local or remote environment with actual hardware, pinned dependencies, and verified model assets. A GPU provider is infrastructure rather than an sTIL method. Estimate memory and runtime using a representative public slide before selecting compute. Keep patient-image transfer as a separate, explicitly authorized operation.

# Proposed implementation and validation plan

## Phase 1 Define the endpoint and assemble the reference set

Create an analysis contract specifying breast-cancer setting, pretreatment versus residual disease, specimen type, intended slide coverage, and which outputs will be called visual sTIL percentage, computational density, or predicted sTIL percentage.

A breast pathologist annotates invasive-tumor boundaries and exclusions and scores slides independently of model output. Where feasible, use two readers with adjudication and retain their individual scores. A small development set can establish feasibility but cannot provide a reliable general accuracy estimate; size the independent validation set around the precision required for agreement and subgroup analyses.

Include low, intermediate, and high infiltration; low-stroma cases; necrosis; artifacts; and the scanner/stain variation expected in use. Post-treatment residual disease should have a distinct evaluation stratum and an appropriate scoring protocol.

Deliverables: endpoint contract, input manifest, annotation guide, patient-level split, and reference scores. Gate: identifiable specimens, reconstructable provenance, and enough eligible tissue to apply the defined endpoint.

## Phase 2 Reproduce the models

Start with public authorized inputs. Pin repository commits, container digest or environment lock, weight hashes, feature extractor, sampling, calibration, and score formula. Verify licensing for code and model assets separately.

Run MuTILs and ECTIL independently and preserve their native outputs. Do not average them into an ensemble before a development and validation study justifies that transformation. Confirm deterministic reruns or document reproducibility tolerances.

Deliverables: reproducible runners, logs, model manifests, native scores and masks, and a throughput estimate. Gate: successful completed inference with interpretable outputs and known coverage; a downloaded checkpoint alone is insufficient.

## Phase 3 Build a scoring and viewer adapter

Normalize units and coordinate frames without overwriting native results. Retain level-zero coordinates, image dimensions, physical calibration where verified, and the transform used for each mask or polygon.

Expose separate fields for native model score, endpoint definition, predicted or calibrated sTIL percentage where supported, eligible stromal area, analyzed coverage, exclusions, and QC status. An ECTIL regression does not supply a measured stromal-area denominator; that field should remain unavailable rather than being fabricated.

Import supported, aligned overlays into Slide Viewer and check landmarks at multiple regions. Where an output format is unsupported, convert it through a documented adapter and verify alignment independently.

Deliverables: output schema, overlay adapter, representative review views, and explicit partial-coverage flags. Gate: no unexplained coordinate shift, unit conversion, or score-definition substitution.

## Phase 4 Evaluate agreement and failure modes

For continuous scores, report absolute error in percentage points, bias and limits of agreement, concordance or an appropriate prespecified ICC, and correlation as a secondary metric. Confidence intervals should respect patient clustering. Review calibration across the score range.

For masks, evaluate stromal overlap and cell detection or classification against appropriate complete references. Nucleus segmentation performance alone does not validate lymphocyte classification or immune occupied area.

Review low-stroma slides, plasma-cell-rich regions, treatment effect, necrosis, inflammation near benign structures, artifacts, and scanner/stain subgroups. Compare models only on a common eligible set and show failures and no-calls.

If a threshold-based use is proposed, prespecify its purpose and evaluate errors near that threshold. Do not choose a threshold merely because it appears in a prognostic paper. Have the pathologist and study lead agree acceptable percentage-point error and no-call criteria before the test set is examined.

Deliverables: frozen evaluation, agreement plots, error atlas, subgroup results, and a validation verdict. Gate: independent performance meets the prespecified research-use criteria.

## Phase 5 Produce the reviewer packet

For each slide, present specimen/timepoint, reference pathologist score, each model’s distinct endpoint and score, analyzed coverage, QC and no-call status, and aligned images or overlays. Explain substantive discrepancies and preserve adjudication.

Do not turn model concordance into a treatment recommendation. If a model is not validated in the intended setting, label its score exploratory and keep it separate from the reported pathology assessment.

# Required no call states and output contract

No-call criteria should include unreadable input, unresolved source identity or calibration needed for the calculation, failed inference, absent assessable invasive-tumor stroma, insufficient coverage, severe artifacts, coordinate misalignment, and unsupported setting. Model disagreement is a review trigger, not automatically a reason to average scores.

Minimum output fields:

- Source and specimen identifiers, slide hash, specimen type, treatment timepoint, scanner and calibration.

- Model name, code and weight versions, feature extractor, preprocessing, coverage, and native score definition.

- Native score and units; calibration version and calibrated score only when applicable.

- Eligible stromal and immune areas only when the implementation actually measures them; otherwise mark unavailable.

- Pathologist scores, annotation version, adjudicated assessment, QC reasons, and no-call status.

- Run identity, output hashes, review identity/date, and claim supported by the evidence.

The first useful milestone is one reproducible public-slide run per model plus an aligned reviewer view and an explicit score-definition mapping. That establishes engineering feasibility. Independent patient-level comparison is the next milestone before trusting absolute percentages.

# Capability sources and selected references

Capability inventory: installed Rosalind Workbench skill version 0.2.10 research preview; Slide Viewer skill and PATHOLOGY.md version 0.1.67; local pipeline strategy, custody, validation, and deployment-governance skills; Paperclip instructions; NGS Analysis Workbench skill version 0.2.18. The inventory describes documented capabilities, not completed model execution.

1. [International TILs Working Group breast scoring recommendations](https://pmc.ncbi.nlm.nih.gov/articles/PMC6267863/).

2. [MuTILs peer-reviewed study](https://www.nature.com/articles/s41523-024-00663-1) and [implementation](https://github.com/PathologyDataScience/MuTILs_Panoptic).

3. [ECTIL peer-reviewed study](https://doi.org/10.1016/j.landig.2025.100921) and [implementation](https://github.com/NKI-AI/ectil).

4. [Spotlight TIGER implementation](https://github.com/Spotlight-Pathology/spotlight-tiger).

5. [TIAToolbox](https://github.com/TissueImageAnalytics/tiatoolbox) and [CellViT++](https://github.com/TIO-IKIM/CellViT-plus-plus).

6. [TILScout endpoint and study](https://www.nature.com/articles/s41698-025-00866-0).
