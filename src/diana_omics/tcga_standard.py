"""Canonical TCGA-common data standard and normalization rules.

The phase-1 HRD analysis (`analyze_hrd`, `build_reference_panel`) consumes
cBioPortal-derived TCGA-BRCA records with a fixed shape:

- mutation records with HUGO gene symbols, MAF `mutationType` (Variant_Classification)
  vocabulary, `proteinChange`, tumor/normal allele counts, and `ncbiBuild`;
- GISTIC discrete copy-number records with a `value` in {-2, -1, 0, 1, 2};
- sample clinical attributes such as FRACTION_GENOME_ALTERED, MUTATION_COUNT,
  TMB_NONSYNONYMOUS, and ANEUPLOIDY_SCORE.

Vendor WES/WGS deliverables (Personalis, Natera, ...) do not arrive in this shape.
This module defines the target schema plus the deterministic mapping and filtering
rules used to bring vendor data up to the same standard the TCGA samples already meet.
"""

from __future__ import annotations

import re
from typing import Optional

# Genes fetched for the TCGA HRR mutation/CNA tables. Kept in sync with
# `commands.fetch_phase1.HRR_GENES`; the canonical definition lives here so the
# vendor normalizer and the TCGA fetch agree on the gene set.
HRR_GENES = [
    "BRCA1",
    "BRCA2",
    "PALB2",
    "RAD51",
    "RAD51B",
    "RAD51C",
    "RAD51D",
    "ATM",
    "CHEK2",
    "BARD1",
    "BRIP1",
    "FANCA",
    "RAD50",
    "MRE11",
    "NBN",
]
HRR_GENE_SET = set(HRR_GENES)

# Vendor callers and older annotation sets use legacy symbols. Map them to the
# HUGO symbol the TCGA tables use so HRR membership and gene joins line up.
GENE_ALIASES = {
    "MRE11A": "MRE11",
    "NBS1": "NBN",
    "FANCD1": "BRCA2",
    "FANCS": "BRCA1",
    "FANCJ": "BRIP1",
    "BACH1": "BRIP1",
    "FANCN": "PALB2",
    "FANCO": "RAD51C",
    "RAD51L1": "RAD51B",
    "RAD51L3": "RAD51D",
    "RNF53": "BRCA1",
    "PPP1R53": "RAD51",
}

# MAF Variant_Classification values that the downstream domain logic recognizes.
MAF_VARIANT_CLASSIFICATIONS = {
    "Nonsense_Mutation",
    "Frame_Shift_Del",
    "Frame_Shift_Ins",
    "Splice_Site",
    "Translation_Start_Site",
    "Nonstop_Mutation",
    "Missense_Mutation",
    "In_Frame_Del",
    "In_Frame_Ins",
    "Silent",
    "Splice_Region",
    "3'UTR",
    "5'UTR",
    "Intron",
    "RNA",
    "IGR",
}

# Sequence Ontology / VEP / SnpEff consequence terms mapped to MAF classes.
# Frameshift and inframe indels resolve direction from ref/alt length later.
_CONSEQUENCE_TO_MAF = {
    "transcript_ablation": "Nonsense_Mutation",
    "stop_gained": "Nonsense_Mutation",
    "stop_lost": "Nonstop_Mutation",
    "start_lost": "Translation_Start_Site",
    "initiator_codon_variant": "Translation_Start_Site",
    "splice_acceptor_variant": "Splice_Site",
    "splice_donor_variant": "Splice_Site",
    "splice_region_variant": "Splice_Region",
    "missense_variant": "Missense_Mutation",
    "protein_altering_variant": "Missense_Mutation",
    "coding_sequence_variant": "Missense_Mutation",
    "frameshift_variant": "Frame_Shift_Del",
    "inframe_deletion": "In_Frame_Del",
    "inframe_insertion": "In_Frame_Ins",
    "synonymous_variant": "Silent",
    "stop_retained_variant": "Silent",
    "start_retained_variant": "Silent",
    "5_prime_utr_variant": "5'UTR",
    "3_prime_utr_variant": "3'UTR",
    "intron_variant": "Intron",
    "non_coding_transcript_exon_variant": "RNA",
    "intergenic_variant": "IGR",
    "upstream_gene_variant": "IGR",
    "downstream_gene_variant": "IGR",
}

# Severity rank (lower is more severe) for picking one class from a compound
# consequence string such as "missense_variant&splice_region_variant".
_CONSEQUENCE_SEVERITY = [
    "transcript_ablation",
    "splice_acceptor_variant",
    "splice_donor_variant",
    "stop_gained",
    "frameshift_variant",
    "stop_lost",
    "start_lost",
    "initiator_codon_variant",
    "missense_variant",
    "protein_altering_variant",
    "inframe_insertion",
    "inframe_deletion",
    "coding_sequence_variant",
    "splice_region_variant",
    "synonymous_variant",
    "stop_retained_variant",
    "start_retained_variant",
    "5_prime_utr_variant",
    "3_prime_utr_variant",
    "non_coding_transcript_exon_variant",
    "intron_variant",
    "upstream_gene_variant",
    "downstream_gene_variant",
    "intergenic_variant",
]
_SEVERITY_RANK = {term: index for index, term in enumerate(_CONSEQUENCE_SEVERITY)}

# Variant classes counted as nonsynonymous for MUTATION_COUNT / TMB parity with
# the TCGA "TMB_NONSYNONYMOUS" definition (silent and non-coding excluded).
NONSYNONYMOUS_CLASSES = {
    "Nonsense_Mutation",
    "Frame_Shift_Del",
    "Frame_Shift_Ins",
    "Splice_Site",
    "Translation_Start_Site",
    "Nonstop_Mutation",
    "Missense_Mutation",
    "In_Frame_Del",
    "In_Frame_Ins",
}

# The TCGA-BRCA PanCancer tables are on GRCh37/hg19. We record this so vendor
# data on a different build is flagged for position-level incompatibility.
TCGA_REFERENCE_BUILD = "GRCh37"

# TCGA-equivalent somatic small-variant acceptance thresholds. These mirror the
# spirit of the MC3 / PanCancer somatic filters: PASS-only, adequate tumor depth,
# supporting reads, a minimum VAF, and a clean (low-evidence) matched normal.
MIN_TUMOR_DEPTH = 14
MIN_TUMOR_ALT_COUNT = 3
MIN_TUMOR_VAF = 0.05
MAX_NORMAL_VAF = 0.02

# Copy-number discretization. GISTIC-style {-2,-1,0,1,2} from absolute copy
# number (ploidy-relative) or from a log2 ratio. Thresholds are documented in
# `gistic_rules()` and surfaced in the normalization report.
FGA_ALTERED_LOG2 = 0.2


def normalize_build(raw: str) -> str:
    """Map assorted build labels onto canonical GRCh37/GRCh38 names."""
    value = (raw or "").strip().lower().replace(" ", "")
    if value in {"grch38", "hg38", "38", "grch38.p13", "grch38.p14", "hs38d1", "hg38_analysis_set"}:
        return "GRCh38"
    if value in {"grch37", "hg19", "37", "b37", "hs37d5", "grch37-lite"}:
        return "GRCh37"
    if value.startswith("grch38") or value.startswith("hg38"):
        return "GRCh38"
    if value.startswith("grch37") or value.startswith("hg19") or value.startswith("b37") or value.startswith("hs37"):
        return "GRCh37"
    return raw or ""


def position_compatible_with_tcga(build: str) -> bool:
    """True only when positions can be compared to TCGA without liftover."""
    return normalize_build(build) == TCGA_REFERENCE_BUILD


def normalize_gene_symbol(symbol: str) -> str:
    cleaned = (symbol or "").strip().upper()
    return GENE_ALIASES.get(cleaned, cleaned)


def is_hrr_gene(symbol: str) -> bool:
    return normalize_gene_symbol(symbol) in HRR_GENE_SET


def most_severe_consequence(raw: str) -> str:
    terms = [term.strip().lower() for term in re.split(r"[&,;|+]", raw or "") if term.strip()]
    if not terms:
        return ""
    ranked = sorted(terms, key=lambda term: _SEVERITY_RANK.get(term, len(_SEVERITY_RANK)))
    return ranked[0]


def variant_classification(consequence: str, ref: str = "", alt: str = "") -> str:
    """Resolve a vendor/VEP consequence to a MAF Variant_Classification.

    Accepts an already-MAF value (passed through) or a SO/VEP/SnpEff term.
    Frameshift and inframe indels resolve Del vs Ins from ref/alt length.
    """
    value = (consequence or "").strip()
    if value in MAF_VARIANT_CLASSIFICATIONS:
        return value
    term = most_severe_consequence(value)
    mapped = _CONSEQUENCE_TO_MAF.get(term, "")
    if mapped in {"Frame_Shift_Del", "Frame_Shift_Ins"}:
        return "Frame_Shift_Ins" if len(alt) > len(ref) else "Frame_Shift_Del"
    if mapped in {"In_Frame_Del", "In_Frame_Ins"}:
        return "In_Frame_Ins" if len(alt) > len(ref) else "In_Frame_Del"
    return mapped


def is_nonsynonymous(classification: str) -> bool:
    return classification in NONSYNONYMOUS_CLASSES


def gistic_from_copy_number(total_cn: float, ploidy: float = 2.0) -> int:
    """Discretize absolute (ploidy-relative) copy number to GISTIC {-2..2}."""
    base = ploidy if ploidy and ploidy > 0 else 2.0
    if total_cn <= 0.5:
        return -2
    if total_cn < base - 0.5:
        return -1
    if total_cn <= base + 0.5:
        return 0
    if total_cn >= 2 * base:
        return 2
    return 1


def gistic_from_log2(log2: float) -> int:
    """Discretize a copy-number log2 ratio to GISTIC {-2..2}."""
    if log2 <= -1.0:
        return -2
    if log2 <= -0.25:
        return -1
    if log2 < 0.2:
        return 0
    if log2 >= 0.9:
        return 2
    return 1


def segment_is_altered(*, log2: Optional[float] = None, gistic: Optional[int] = None) -> bool:
    if gistic is not None:
        return gistic != 0
    if log2 is not None:
        return abs(log2) >= FGA_ALTERED_LOG2
    return False


def somatic_filter_rules() -> list[dict[str, object]]:
    return [
        {"rule": "filter_pass", "detail": "Variant FILTER must be PASS or '.'; vendor-flagged calls are dropped."},
        {"rule": "min_tumor_depth", "threshold": MIN_TUMOR_DEPTH, "detail": "Minimum tumor total read depth."},
        {"rule": "min_tumor_alt_count", "threshold": MIN_TUMOR_ALT_COUNT, "detail": "Minimum tumor alternate-allele supporting reads."},
        {"rule": "min_tumor_vaf", "threshold": MIN_TUMOR_VAF, "detail": "Minimum tumor variant allele fraction."},
        {
            "rule": "max_normal_vaf",
            "threshold": MAX_NORMAL_VAF,
            "detail": "Matched-normal VAF must stay below this to keep a somatic call.",
        },
        {"rule": "standard_contig", "detail": "Only chr1-22, chrX, chrY are retained, matching TCGA autosome/allosome scope."},
        {"rule": "hrr_gene_scope", "detail": "Canonical HRR mutation/CNA tables keep only the TCGA HRR gene set."},
    ]


def gistic_rules() -> list[dict[str, object]]:
    return [
        {"input": "absolute_copy_number", "rule": "cn<=0.5 -> -2; cn<ploidy-0.5 -> -1; |cn-ploidy|<=0.5 -> 0; cn>=2*ploidy -> 2; else 1"},
        {"input": "log2_ratio", "rule": "log2<=-1 -> -2; log2<=-0.25 -> -1; log2<0.2 -> 0; log2>=0.9 -> 2; else 1"},
        {"input": "fraction_genome_altered", "rule": f"segment altered when |log2|>={FGA_ALTERED_LOG2} or GISTIC state != 0"},
    ]


def tcga_standard_contract() -> dict[str, object]:
    return {
        "referenceBuild": TCGA_REFERENCE_BUILD,
        "hrrGenes": HRR_GENES,
        "mutationSchema": [
            "sampleId",
            "patientId",
            "gene.hugoGeneSymbol",
            "entrezGeneId",
            "mutationType",
            "proteinChange",
            "tumorAltCount",
            "tumorRefCount",
            "ncbiBuild",
            "chr",
            "startPosition",
        ],
        "cnaSchema": ["sampleId", "patientId", "gene.hugoGeneSymbol", "value"],
        "clinicalAttributes": [
            "FRACTION_GENOME_ALTERED",
            "MUTATION_COUNT",
            "TMB_NONSYNONYMOUS",
            "ANEUPLOIDY_SCORE",
            "SAMPLE_TYPE",
            "CANCER_TYPE_DETAILED",
        ],
        "somaticFilters": somatic_filter_rules(),
        "copyNumberDiscretization": gistic_rules(),
        "buildPolicy": "Vendor data on a non-GRCh37 build keeps HUGO-level comparability; position-level joins are flagged until liftover.",
    }
