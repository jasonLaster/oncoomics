"""Normalize vendor WES/WGS deliverables into the common TCGA format.

Personalis, Natera, and similar vendors ship somatic variant calls, copy-number
calls, and QC metrics in their own column layouts and on their own reference
build. This module maps those deliverables onto the canonical TCGA-BRCA schema
(`tcga_standard`) and applies the same somatic acceptance filters the TCGA
samples already passed, so a Diana sample can be analyzed beside the public
reference panel on equal footing.

It is intentionally dependency-free (stdlib parsing of VCF / MAF / delimited
tables). Heavier IO (`pysam`) can replace the parsers later without changing the
canonical output contract.
"""

from __future__ import annotations

import io
import re
from typing import Any, Iterable, Optional

from . import tcga_standard as tcga
from .utils import parse_delimited, standard_contig, to_number

VENDOR_MANIFEST_DEFAULT = "manifests/diana_vendor_inputs.csv"
VENDOR_MANIFEST_TEMPLATE = "manifests/diana_vendor_inputs.template.csv"
VENDOR_RESULTS = "results/diana_vendor_normalized"

VENDOR_MANIFEST_COLUMNS = [
    "sample_id",
    "patient_id",
    "vendor",
    "assay",
    "reference_build",
    "variant_file",
    "variant_format",
    "tumor_sample_column",
    "normal_sample_column",
    "cnv_gene_file",
    "cnv_seg_file",
    "ploidy",
    "tumor_purity",
    "capture_megabases",
    "mutation_count",
    "tmb_nonsynonymous",
    "aneuploidy_score",
    "sample_type",
    "cancer_type_detailed",
    "notes",
]

# Column aliases used to locate canonical fields in vendor delimited / MAF tables.
# Lower-cased on lookup; first match wins in declaration order.
_VARIANT_COLUMN_ALIASES = {
    "gene": ["hugo_symbol", "gene", "gene_symbol", "genesymbol", "symbol", "gene_name"],
    "consequence": [
        "variant_classification",
        "consequence",
        "effect",
        "annotation",
        "most_severe_consequence",
        "variant_effect",
        "functional_class",
    ],
    "protein_change": ["protein_change", "hgvsp_short", "hgvsp", "amino_acid_change", "aa_change", "protein"],
    "chrom": ["chromosome", "chr", "chrom", "contig"],
    "pos": ["start_position", "start", "pos", "position"],
    "end": ["end_position", "end", "stop"],
    "ref": ["reference_allele", "ref", "ref_allele"],
    "alt": ["tumor_seq_allele2", "alt", "alt_allele", "variant_allele", "tumor_seq_allele"],
    "filter": ["filter", "mutation_status", "filter_status"],
    "t_alt_count": ["t_alt_count", "tumor_alt_count", "alt_count", "ad_alt", "tumoraltcount"],
    "t_ref_count": ["t_ref_count", "tumor_ref_count", "ref_count", "ad_ref", "tumorrefcount"],
    "t_depth": ["t_depth", "tumor_depth", "depth", "dp", "total_depth"],
    "t_vaf": ["t_vaf", "tumor_vaf", "vaf", "af", "allele_fraction", "tumor_af"],
    "n_alt_count": ["n_alt_count", "normal_alt_count", "normalaltcount"],
    "n_depth": ["n_depth", "normal_depth", "normaldepth"],
    "n_vaf": ["n_vaf", "normal_vaf", "normal_af"],
    "build": ["ncbi_build", "build", "reference_build", "assembly", "genome"],
}

_CNV_GENE_COLUMN_ALIASES = {
    "gene": ["hugo_symbol", "gene", "gene_symbol", "symbol", "gene_name"],
    "copy_number": ["copy_number", "total_cn", "cn", "absolute_cn", "tcn", "copynumber"],
    "log2": ["log2", "log2_ratio", "seg_mean", "segment_mean", "log2ratio", "log2cna"],
    "gistic": ["gistic", "gistic_value", "discrete", "cna"],
}

_CNV_SEG_COLUMN_ALIASES = {
    "chrom": ["chromosome", "chr", "chrom", "contig"],
    "start": ["start", "start_position", "loc.start", "seg_start"],
    "end": ["end", "end_position", "loc.end", "seg_end"],
    "copy_number": ["copy_number", "total_cn", "cn", "absolute_cn", "tcn"],
    "log2": ["log2", "log2_ratio", "seg_mean", "segment_mean", "mean"],
}


def vendor_manifest_template_rows() -> list[dict[str, str]]:
    return [
        {
            "sample_id": "DIANA-TUMOR-01",
            "patient_id": "DIANA",
            "vendor": "personalis",
            "assay": "WGS",
            "reference_build": "GRCh38",
            "variant_file": "data/raw/diana/personalis/DIANA-TUMOR-01.somatic.vcf",
            "variant_format": "vcf",
            "tumor_sample_column": "TUMOR",
            "normal_sample_column": "NORMAL",
            "cnv_gene_file": "data/raw/diana/personalis/DIANA-TUMOR-01.cnv_genes.tsv",
            "cnv_seg_file": "data/raw/diana/personalis/DIANA-TUMOR-01.segments.tsv",
            "ploidy": "2.0",
            "tumor_purity": "pending",
            "capture_megabases": "",
            "mutation_count": "",
            "tmb_nonsynonymous": "",
            "aneuploidy_score": "",
            "sample_type": "Primary",
            "cancer_type_detailed": "Breast Invasive Carcinoma",
            "notes": "Personalis NeXT-style tumor-normal WGS; replace placeholder paths with real files.",
        },
        {
            "sample_id": "DIANA-TUMOR-02",
            "patient_id": "DIANA",
            "vendor": "natera",
            "assay": "WES",
            "reference_build": "GRCh38",
            "variant_file": "data/raw/diana/natera/DIANA-TUMOR-02.altera.maf",
            "variant_format": "maf",
            "tumor_sample_column": "",
            "normal_sample_column": "",
            "cnv_gene_file": "data/raw/diana/natera/DIANA-TUMOR-02.gene_cn.tsv",
            "cnv_seg_file": "",
            "ploidy": "2.0",
            "tumor_purity": "pending",
            "capture_megabases": "36",
            "mutation_count": "",
            "tmb_nonsynonymous": "",
            "aneuploidy_score": "",
            "sample_type": "Primary",
            "cancer_type_detailed": "Breast Invasive Carcinoma",
            "notes": "Natera Altera-style tumor-informed WES; capture_megabases used for TMB normalization.",
        },
    ]


def _resolve_alias(columns: Iterable[str], aliases: list[str]) -> Optional[str]:
    lowered = {column.lower().strip(): column for column in columns}
    for alias in aliases:
        if alias in lowered:
            return lowered[alias]
    return None


def _alias_map(columns: Iterable[str], alias_table: dict[str, list[str]]) -> dict[str, Optional[str]]:
    column_list = list(columns)
    return {field: _resolve_alias(column_list, aliases) for field, aliases in alias_table.items()}


# --- variant parsing ---------------------------------------------------------


def detect_variant_format(path: str, declared: str = "") -> str:
    value = (declared or "").strip().lower()
    if value in {"vcf", "maf", "tsv", "csv"}:
        return value
    lowered = path.lower()
    if lowered.endswith(".vcf") or lowered.endswith(".vcf.gz"):
        return "vcf"
    if lowered.endswith(".maf") or lowered.endswith(".maf.gz"):
        return "maf"
    if lowered.endswith(".csv"):
        return "csv"
    return "tsv"


def _vcf_consequence_and_gene(info: dict[str, str]) -> tuple[str, str, str]:
    """Pull (gene, consequence, protein_change) from VEP CSQ or SnpEff ANN."""
    for key in ("CSQ", "ANN"):
        raw = info.get(key)
        if not raw:
            continue
        first = raw.split(",")[0]
        fields = first.split("|")
        if key == "CSQ":
            # VEP default order: Allele|Consequence|IMPACT|SYMBOL|Gene|...|HGVSp
            consequence = fields[1] if len(fields) > 1 else ""
            gene = fields[3] if len(fields) > 3 else ""
            protein = next((f for f in fields if f.startswith("p.") or ":p." in f), "")
            return gene, consequence, protein
        # SnpEff ANN order: Allele|Annotation|Impact|Gene_Name|...|HGVS.p
        consequence = fields[1] if len(fields) > 1 else ""
        gene = fields[3] if len(fields) > 3 else ""
        protein = next((f for f in fields if f.startswith("p.")), "")
        return gene, consequence, protein
    gene = info.get("GENE", info.get("Gene", ""))
    consequence = info.get("CONSEQUENCE", info.get("EFF", ""))
    return gene, consequence, ""


def _parse_vcf_sample(format_keys: list[str], sample_value: str) -> dict[str, str]:
    values = sample_value.split(":")
    return dict(zip(format_keys, values))


def _sample_depth_alt(call: dict[str, str]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (alt_count, ref_count, depth) from a parsed VCF FORMAT call."""
    ad = call.get("AD")
    depth = to_number(call.get("DP"))
    alt_count: Optional[float] = None
    ref_count: Optional[float] = None
    if ad and "," in ad:
        parts = [to_number(part) for part in ad.split(",")]
        if parts and parts[0] is not None:
            ref_count = parts[0]
        alt_values = [value for value in parts[1:] if value is not None]
        if alt_values:
            alt_count = max(alt_values)
    if depth is None and ref_count is not None and alt_count is not None:
        depth = ref_count + alt_count
    return alt_count, ref_count, depth


def parse_vcf(text: str, tumor_column: str = "", normal_column: str = "") -> list[dict[str, Any]]:
    sample_names: list[str] = []
    records: list[dict[str, Any]] = []
    for line in io.StringIO(text):
        line = line.rstrip("\n")
        if line.startswith("##") or not line:
            continue
        if line.startswith("#CHROM"):
            header = line.lstrip("#").split("\t")
            sample_names = header[9:] if len(header) > 9 else []
            continue
        fields = line.split("\t")
        if len(fields) < 8:
            continue
        chrom, pos, _vid, ref, alt, _qual, flt, info_raw = fields[:8]
        info = {}
        for item in info_raw.split(";"):
            if "=" in item:
                key, value = item.split("=", 1)
                info[key] = value
            elif item:
                info[item] = "true"
        gene, consequence, protein = _vcf_consequence_and_gene(info)
        record: dict[str, Any] = {
            "chrom": chrom,
            "pos": pos,
            "ref": ref,
            "alt": alt.split(",")[0],
            "filter": flt,
            "gene": gene,
            "consequence": consequence,
            "protein_change": protein,
        }
        if len(fields) >= 10 and sample_names:
            format_keys = fields[8].split(":")
            calls = {
                name: _parse_vcf_sample(format_keys, fields[9 + index])
                for index, name in enumerate(sample_names)
                if 9 + index < len(fields)
            }
            tumor_name = tumor_column or _guess_tumor(sample_names)
            normal_name = normal_column or _guess_normal(sample_names)
            tumor_call = calls.get(tumor_name, {})
            normal_call = calls.get(normal_name, {})
            t_alt, t_ref, t_depth = _sample_depth_alt(tumor_call)
            n_alt, _n_ref, n_depth = _sample_depth_alt(normal_call)
            record.update({"t_alt_count": t_alt, "t_ref_count": t_ref, "t_depth": t_depth, "n_alt_count": n_alt, "n_depth": n_depth})
            t_af = tumor_call.get("AF")
            if t_af:
                record["t_vaf"] = to_number(t_af.split(",")[0])
            n_af = normal_call.get("AF")
            if n_af:
                record["n_vaf"] = to_number(n_af.split(",")[0])
        records.append(record)
    return records


def _guess_tumor(sample_names: list[str]) -> str:
    for name in sample_names:
        if re.search(r"tumou?r|_t$|-t$|primary|somatic", name, re.I):
            return name
    return sample_names[0] if sample_names else ""


def _guess_normal(sample_names: list[str]) -> str:
    for name in sample_names:
        if re.search(r"normal|germline|_n$|-n$|blood|buffy", name, re.I):
            return name
    return sample_names[-1] if len(sample_names) > 1 else ""


def parse_delimited_variants(text: str, delimiter: str) -> list[dict[str, Any]]:
    rows = parse_delimited(text, delimiter)
    if not rows:
        return []
    alias = _alias_map(rows[0].keys(), _VARIANT_COLUMN_ALIASES)
    records: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {}
        for field, source in alias.items():
            if source is not None:
                record[field] = row.get(source, "")
        records.append(record)
    return records


def parse_variant_file(text: str, fmt: str, tumor_column: str = "", normal_column: str = "") -> list[dict[str, Any]]:
    if fmt == "vcf":
        return parse_vcf(text, tumor_column, normal_column)
    if fmt == "csv":
        return parse_delimited_variants(text, ",")
    return parse_delimited_variants(text, "\t")


# --- filtering + normalization ----------------------------------------------


def _record_vaf(record: dict[str, Any]) -> Optional[float]:
    vaf = to_number(record.get("t_vaf"))
    if vaf is not None:
        return vaf
    alt = to_number(record.get("t_alt_count"))
    depth = to_number(record.get("t_depth"))
    if alt is not None and depth and depth > 0:
        return alt / depth
    ref = to_number(record.get("t_ref_count"))
    if alt is not None and ref is not None and (alt + ref) > 0:
        return alt / (alt + ref)
    return None


def _record_depth(record: dict[str, Any]) -> Optional[float]:
    depth = to_number(record.get("t_depth"))
    if depth is not None:
        return depth
    alt = to_number(record.get("t_alt_count"))
    ref = to_number(record.get("t_ref_count"))
    if alt is not None and ref is not None:
        return alt + ref
    return None


def filter_variant(record: dict[str, Any]) -> tuple[bool, str]:
    """Apply TCGA-equivalent somatic filters. Returns (kept, drop_reason)."""
    flt = str(record.get("filter", "")).strip()
    if flt and flt.upper() not in {"PASS", "."}:
        return False, "filter_not_pass"
    chrom = str(record.get("chrom", ""))
    contig = chrom if chrom.startswith("chr") else f"chr{chrom}"
    if not tcga.is_hrr_gene(str(record.get("gene", ""))):
        return False, "off_target_gene"
    if not standard_contig(contig):
        return False, "non_standard_contig"
    depth = _record_depth(record)
    if depth is not None and depth < tcga.MIN_TUMOR_DEPTH:
        return False, "low_tumor_depth"
    alt = to_number(record.get("t_alt_count"))
    if alt is not None and alt < tcga.MIN_TUMOR_ALT_COUNT:
        return False, "low_alt_support"
    vaf = _record_vaf(record)
    if vaf is not None and vaf < tcga.MIN_TUMOR_VAF:
        return False, "low_tumor_vaf"
    n_vaf = to_number(record.get("n_vaf"))
    if n_vaf is None:
        n_alt = to_number(record.get("n_alt_count"))
        n_depth = to_number(record.get("n_depth"))
        if n_alt is not None and n_depth and n_depth > 0:
            n_vaf = n_alt / n_depth
    if n_vaf is not None and n_vaf > tcga.MAX_NORMAL_VAF:
        return False, "germline_in_normal"
    return True, ""


def to_canonical_mutation(record: dict[str, Any], sample_id: str, patient_id: str, build: str) -> dict[str, Any]:
    gene = tcga.normalize_gene_symbol(str(record.get("gene", "")))
    ref = str(record.get("ref", ""))
    alt = str(record.get("alt", ""))
    classification = tcga.variant_classification(str(record.get("consequence", "")), ref, alt)
    record_build = tcga.normalize_build(str(record.get("build", ""))) or tcga.normalize_build(build)
    alt_count = to_number(record.get("t_alt_count"))
    ref_count = to_number(record.get("t_ref_count"))
    return {
        "sampleId": sample_id,
        "patientId": patient_id,
        "gene": {"hugoGeneSymbol": gene},
        "entrezGeneId": "",
        "mutationType": classification,
        "proteinChange": str(record.get("protein_change", "")),
        "tumorAltCount": int(alt_count) if alt_count is not None else "",
        "tumorRefCount": int(ref_count) if ref_count is not None else "",
        "ncbiBuild": record_build,
        "chr": str(record.get("chrom", "")),
        "startPosition": str(record.get("pos", "")),
        "keyword": str(record.get("consequence", "")),
    }


# --- copy number -------------------------------------------------------------


def gene_cnv_to_gistic(rows: list[dict[str, str]], ploidy: float) -> dict[str, int]:
    if not rows:
        return {}
    alias = _alias_map(rows[0].keys(), _CNV_GENE_COLUMN_ALIASES)
    result: dict[str, int] = {}
    for row in rows:
        gene_col = alias.get("gene")
        if not gene_col:
            continue
        gene = tcga.normalize_gene_symbol(row.get(gene_col, ""))
        if gene not in tcga.HRR_GENE_SET:
            continue
        gistic_col = alias.get("gistic")
        cn_col = alias.get("copy_number")
        log2_col = alias.get("log2")
        if gistic_col and row.get(gistic_col) not in (None, ""):
            value = to_number(row.get(gistic_col))
            if value is not None:
                result[gene] = max(-2, min(2, int(round(value))))
                continue
        if cn_col and row.get(cn_col) not in (None, ""):
            cn = to_number(row.get(cn_col))
            if cn is not None:
                result[gene] = tcga.gistic_from_copy_number(cn, ploidy)
                continue
        if log2_col and row.get(log2_col) not in (None, ""):
            log2 = to_number(row.get(log2_col))
            if log2 is not None:
                result[gene] = tcga.gistic_from_log2(log2)
    return result


def fraction_genome_altered(seg_rows: list[dict[str, str]], ploidy: float) -> Optional[float]:
    if not seg_rows:
        return None
    alias = _alias_map(seg_rows[0].keys(), _CNV_SEG_COLUMN_ALIASES)
    start_col = alias.get("start")
    end_col = alias.get("end")
    if not start_col or not end_col:
        return None
    cn_col = alias.get("copy_number")
    log2_col = alias.get("log2")
    total = 0.0
    altered = 0.0
    for row in seg_rows:
        start = to_number(row.get(start_col))
        end = to_number(row.get(end_col))
        if start is None or end is None or end <= start:
            continue
        length = end - start
        total += length
        is_altered = False
        if cn_col and row.get(cn_col) not in (None, ""):
            cn = to_number(row.get(cn_col))
            if cn is not None:
                is_altered = tcga.segment_is_altered(gistic=tcga.gistic_from_copy_number(cn, ploidy))
        elif log2_col and row.get(log2_col) not in (None, ""):
            log2 = to_number(row.get(log2_col))
            if log2 is not None:
                is_altered = tcga.segment_is_altered(log2=log2)
        if is_altered:
            altered += length
    if total <= 0:
        return None
    return round(altered / total, 4)


# --- clinical ----------------------------------------------------------------


def clinical_records(
    sample_id: str,
    *,
    fga: Optional[float],
    mutation_count: Optional[float],
    tmb: Optional[float],
    aneuploidy: Optional[float],
    sample_type: str,
    cancer_type_detailed: str,
) -> list[dict[str, Any]]:
    attributes = {
        "FRACTION_GENOME_ALTERED": "" if fga is None else fga,
        "MUTATION_COUNT": "" if mutation_count is None else int(mutation_count),
        "TMB_NONSYNONYMOUS": "" if tmb is None else round(tmb, 4),
        "ANEUPLOIDY_SCORE": "" if aneuploidy is None else aneuploidy,
        "SAMPLE_TYPE": sample_type,
        "CANCER_TYPE_DETAILED": cancer_type_detailed,
    }
    return [{"sampleId": sample_id, "clinicalAttributeId": key, "value": value} for key, value in attributes.items() if value != ""]
