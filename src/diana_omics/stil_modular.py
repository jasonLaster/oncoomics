"""Offline mask arithmetic for a modular H&E research comparison, not clinical sTIL.

Model inference, license acceptance, downloads and patient-image transfer are outside
this module. Inputs must already share a source-bound, reviewed coordinate frame.
"""

import math
import re

BREAST_CLASSES = {"Endothelium", "Epithelium", "Lymphocyte", "Macrophage", "Plasma_cell", "Stroma", "tumor", "Unknown"}
IMMUNE_CLASSES = {"Lymphocyte", "Plasma_cell"}
STROMA_DEFINITION = "total_stromal_compartment_including_immune_occupied_area"
GRID_KEYS = ("source_sha256", "origin_level0_xy", "mpp_xy", "shape_yx")
MASK_NAMES = ("approved_region", "stroma", "exclusions", "assessed_region", "instances")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def score_masks(masks, cells, contract):
    """Return an ROI nuclear-area proxy, retaining unknowns in the denominator.

    Every layer's grid must be explicitly declared, with x/y MPP, level-0 origin
    and source SHA-256. Instance 0 is background. Classifier probabilities are
    only a development-frozen rejection rule, never calibrated uncertainty.
    """
    import numpy as np

    _require(set(masks) == set(MASK_NAMES), "five named mask layers are required")
    _require(contract.get("scope") == "roi", "this adapter supports ROI arithmetic only")
    _require(contract.get("stroma_definition") == STROMA_DEFINITION, "stroma must include immune-occupied stromal area")
    grid = contract.get("grid", {})
    _require(all(k in grid for k in GRID_KEYS), "incomplete reference grid")
    _require(re.fullmatch(r"[0-9a-f]{64}", grid["source_sha256"]) is not None, "invalid source SHA-256")
    shape = grid["shape_yx"]
    _require(len(shape) == 2 and all(isinstance(v, int) and v > 0 for v in shape), "invalid grid shape")
    _require(len(grid["mpp_xy"]) == 2 and all(math.isfinite(v) and v > 0 for v in grid["mpp_xy"]), "invalid pixel calibration")
    _require(len(grid["origin_level0_xy"]) == 2 and all(math.isfinite(v) and v >= 0 for v in grid["origin_level0_xy"]), "invalid level-0 origin")
    for name in MASK_NAMES:
        _require(contract.get("layer_grids", {}).get(name) == grid, "layer coordinate/source mismatch: " + name)
        _require(masks[name].shape == tuple(shape), "mask shape mismatch: " + name)
    for name in MASK_NAMES[:-1]:
        _require(masks[name].dtype == np.bool_, "binary masks must have boolean dtype: " + name)
    instances = masks["instances"]
    _require(np.issubdtype(instances.dtype, np.integer) and (instances >= 0).all(), "instances must be nonnegative integers")
    instance_ids = set(np.unique(instances)) - {0}
    class_by_id = {}
    for cell in cells:
        cid = cell["instance_id"]
        _require(isinstance(cid, int) and not isinstance(cid, bool) and cid > 0, "invalid instance ID")
        _require(cid not in class_by_id, "duplicate cell classification")
        _require(cell["class_name"] in BREAST_CLASSES, "unsupported breast taxonomy")
        _require(math.isfinite(cell["probability"]) and 0 <= cell["probability"] <= 1, "invalid class probability")
        class_by_id[cid] = cell
    _require(set(class_by_id) == instance_ids, "instance/classification IDs do not match exactly")
    threshold = contract.get("probability_threshold")
    _require(isinstance(threshold, (int, float)) and math.isfinite(threshold) and 0 <= threshold <= 1, "explicit probability rejection threshold required")
    policy = contract.get("acceptance", {})
    for key in ("min_stromal_area_um2", "min_coverage_fraction", "max_unknown_nuclear_area_fraction"):
        _require(isinstance(policy.get(key), (int, float)) and math.isfinite(policy[key]), "prespecified acceptance value required: " + key)
    _require(policy["min_stromal_area_um2"] > 0, "minimum stromal area must be positive")
    _require(0 < policy["min_coverage_fraction"] <= 1, "invalid minimum coverage")
    _require(0 <= policy["max_unknown_nuclear_area_fraction"] <= 1, "invalid maximum unknown area")
    eligible = masks["approved_region"] & masks["stroma"] & ~masks["exclusions"]
    assessed = eligible & masks["assessed_region"]
    immune_ids, unknown_ids = [], []
    for cid, cell in class_by_id.items():
        if cell["class_name"] == "Unknown" or cell["probability"] < threshold:
            unknown_ids.append(cid)
        elif cell["class_name"] in IMMUNE_CLASSES:
            immune_ids.append(cid)
    n_eligible, n_assessed = int(eligible.sum()), int(assessed.sum())
    immune_pixels = int((np.isin(instances, immune_ids) & assessed).sum())
    unknown_pixels = int((np.isin(instances, unknown_ids) & assessed).sum())
    nuclear_pixels = int(((instances > 0) & assessed).sum())
    pixel_area = math.prod(grid["mpp_xy"])
    coverage = n_assessed / n_eligible if n_eligible else 0.0
    unknown_fraction = unknown_pixels / n_assessed if n_assessed else None
    unknown_nuclear_fraction = unknown_pixels / nuclear_pixels if nuclear_pixels else None
    reasons = []
    if contract.get("stain") != "H&E":
        reasons.append("unsupported_stain")
    if contract.get("specimen_type") not in ("breast", "breast_margin") or contract.get("organ_head") != "breast":
        reasons.append("unsupported_or_unconfirmed_specimen")
    if contract.get("source_identity_verified") is not True:
        reasons.append("unconfirmed_source_identity")
    if contract.get("annotation_reviewed") is not True or not contract.get("annotation_reference"):
        reasons.append("missing_reviewed_eligibility_annotation")
    setting = contract.get("treatment_timepoint")
    if setting not in ("pretreatment", "post_neoadjuvant") or not contract.get("scoring_protocol_reference"):
        reasons.append("unsupported_or_unreviewed_treatment_setting")
    if n_assessed == 0 or n_assessed * pixel_area < policy["min_stromal_area_um2"]:
        reasons.append("insufficient_assessed_stroma")
    if coverage < policy["min_coverage_fraction"]:
        reasons.append("insufficient_eligible_stroma_coverage")
    if not nuclear_pixels:
        reasons.append("no_assessable_nuclei_detected")
    if unknown_nuclear_fraction is not None and unknown_nuclear_fraction > policy["max_unknown_nuclear_area_fraction"]:
        reasons.append("excess_unresolved_nuclear_area")
    return {
        "schema_version": 1,
        "status": "no_call" if reasons else "research_proxy_computed",
        "no_call_reasons": reasons,
        "scope": "roi",
        "source_sha256": grid["source_sha256"],
        "clinical_stil_percent": None,
        "nuclear_area_proxy_percent": 100 * immune_pixels / n_assessed if n_assessed and not reasons else None,
        "immune_nuclear_area_um2": immune_pixels * pixel_area,
        "assessed_stromal_area_um2": n_assessed * pixel_area,
        "annotated_eligible_stromal_area_um2": n_eligible * pixel_area,
        "eligible_stroma_coverage_fraction": coverage,
        "unknown_nuclear_area_percent_of_stroma": 100 * unknown_fraction if unknown_fraction is not None else None,
        "unknown_fraction_of_assessed_nuclear_area": unknown_nuclear_fraction,
        "uncertainty_definition": "unknown or rejected nuclear area; not a confidence interval",
        "probability_threshold": threshold,
        "acceptance": policy,
        "evidence_classification": "internal_qc_only",
        "model_accuracy_validation": "not_established",
    }


def prepare_review_queue(rows, protocol):
    """Turn existing native outputs into a source-bound development review queue."""
    queue = []
    for row in rows:
        if row["stain"] != "H&E":
            continue
        group = row.get("candidate_tissue_group", "unconfirmed")
        reasons = ["source_identity_and_eligible_stroma_review", "treatment_setting_and_protocol_review"]
        lane = "breast_development_review"
        if group == "axillary_sentinel_node":
            lane = "separate_nodal_review_not_primary_breast_stil"
            reasons.append("nodal_tissue_and_organ_head_review")
        elif group not in ("breast", "breast_margin"):
            lane = "specimen_identity_review"
        admitted = row.get("mutils_admitted_rois")
        candidates = row.get("mutils_candidate_rois")
        if row.get("mutils_status") == "no_call":
            reasons.append("native_filter_no_call_recovery")
        elif admitted is not None and candidates and admitted / candidates < 0.25:
            reasons.append("sparse_native_admission_sampling_review")
        if row.get("mutils_salient_til_region_to_stroma_percent", 0) > 2 * row.get("mutils_til_region_to_stroma_percent", math.inf):
            reasons.append("pooled_vs_salient_spatial_review")
        queue.append({
            "slide": row["slide"], "source_sha256": row["source_sha256"],
            "candidate_tissue_group": group, "review_lane": lane,
            "review_reasons": ";".join(reasons),
            "native_admission_fraction": admitted / candidates if admitted is not None and candidates else None,
            "selection_role": "diagnostic_development_only_not_unbiased_validation",
            "annotation_status": "not_reviewed", "new_modular_score_percent": None,
        })
    readiness = {
        "schema_version": 1, "status": "not_ready_for_new_model_inference",
        "strategy_verdict": "promising_with_gaps", "validation_verdict": "partial",
        "existing_results_modified": False, "new_models_executed": False,
        "clinical_stil_percent": None, "he_slides": len(queue),
        "breast_review_slides": sum(r["review_lane"] == "breast_development_review" for r in queue),
        "separate_nodal_review_slides": sum(r["candidate_tissue_group"] == "axillary_sentinel_node" for r in queue),
        "component_gaps": {name: {
            "checkpoint_sha256": component["checkpoint_sha256"],
            "license_review_status": component["license_review_status"],
            "configuration_status": component["configuration_status"],
        } for name, component in protocol["components"].items()},
        "required_before_inference": protocol["validation"]["required_before_inference"],
        "required_before_interpretation": protocol["validation"]["required_before_interpretation"],
        "acceptance_thresholds_status": protocol["validation"]["acceptance_thresholds_status"],
    }
    return queue, readiness
