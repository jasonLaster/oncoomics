from __future__ import annotations

from types import SimpleNamespace

import pytest

from diana_omics.variant_read_audit import audit_bam, count_fragments, evidence_state, validate_sites


def read(name="fragment", base="A", reverse=False, **overrides):
    values = dict(
        query_name=name,
        query_sequence="C" * 10 + base + "C" * 10,
        query_qualities=[35] * 21,
        mapping_quality=60,
        is_unmapped=False,
        is_secondary=False,
        is_supplementary=False,
        is_duplicate=False,
        is_qcfail=False,
        is_reverse=reverse,
        is_read1=True,
    )
    values.update(overrides)
    item = SimpleNamespace(**values)
    item.get_aligned_pairs = lambda matches_only=False: [(10, 99)]
    item.has_tag = lambda tag: True
    item.get_tag = lambda tag: "lane1"
    return item


def test_overlapping_mates_do_not_double_count_alternate():
    result = count_fragments([read(), read(reverse=True)], 100, "C", "A")
    assert result["alt_fragments"] == result["fragment_depth"] == 1
    assert result["overlap_observations_collapsed"] == 1


def test_read_group_namespaces_are_distinct():
    second = read()
    second.get_tag = lambda tag: "lane2"
    assert count_fragments([read(), second], 100, "C", "A")["alt_fragments"] == 2


def test_conflicting_overlapping_mates_are_excluded():
    result = count_fragments([read(), read(base="C")], 100, "C", "A")
    assert result["fragment_depth"] == 0
    assert result["discordant_fragments_excluded"] == 1


@pytest.mark.parametrize("field", ["is_duplicate", "is_secondary", "is_supplementary", "is_qcfail", "is_unmapped"])
def test_alignment_exclusions(field):
    assert count_fragments([read(**{field: True})], 100, "C", "A")["fragment_depth"] == 0


def test_quality_and_end_filters():
    assert count_fragments([read(mapping_quality=29)], 100, "C", "A")["fragment_depth"] == 0
    assert count_fragments([read(query_qualities=[29] * 21)], 100, "C", "A")["fragment_depth"] == 0
    assert count_fragments([read()], 100, "C", "A", min_end_distance=11)["fragment_depth"] == 0


def test_zero_alternate_has_depth_limited_bound():
    result = count_fragments([read(str(i), base="C") for i in range(30)], 100, "C", "A")
    assert result["zero_alt_one_sided_95pct_upper_fraction"] == pytest.approx(0.0950338529)
    assert evidence_state(result, result) == "alternate_not_observed_at_this_depth"


def test_low_depth_never_promoted_and_normal_support_is_distinct():
    t = count_fragments([read(str(i)) for i in range(4)], 100, "C", "A")
    n = count_fragments([read(str(i), base="C") for i in range(40)], 100, "C", "A")
    assert evidence_state(t, n) == "insufficient_depth"
    t = count_fragments([read(str(i), base="A" if i < 4 else "C") for i in range(40)], 100, "C", "A")
    assert evidence_state(t, n) == "tumor_enriched_read_support"
    assert evidence_state(t, t) == "alternate_observed_in_normal"


@pytest.mark.parametrize("change", [{"build": "GRCh37"}, {"alt": "AG"}, {"ref": "N"}, {"pos": 0}, {"alt": "C"}])
def test_invalid_or_incomplete_alleles_rejected(change):
    with pytest.raises(ValueError):
        validate_sites([dict(chrom="chr1", pos=100, ref="C", alt="A", build="GRCh38", **{}) | change])


def test_real_indexed_bam_and_reference_dictionary(tmp_path):
    pysam = pytest.importorskip("pysam")
    path = tmp_path / "reads.bam"
    header = {"HD": {"VN": "1.6", "SO": "coordinate"}, "SQ": [{"SN": "chr1", "LN": 1000}]}
    with pysam.AlignmentFile(str(path), "wb", header=header) as bam:
        for name, base in (("alt", "A"), ("ref", "C")):
            item = pysam.AlignedSegment()
            item.query_name = name
            item.query_sequence = "C" * 10 + base + "C" * 10
            item.flag = 0
            item.reference_id = 0
            item.reference_start = 89
            item.mapping_quality = 60
            item.cigar = [(0, 21)]
            item.query_qualities = [35] * 21
            bam.write(item)
    pysam.index(str(path))
    sites = [{"chrom": "chr1", "pos": 100, "ref": "C", "alt": "A", "build": "GRCh38"}]
    result = audit_bam(str(path), sites, {"chr1": 1000})
    primary = result["sites"][0]["policies"]["primary_30_30_end5"]
    assert primary["alt_fragments"] == primary["ref_fragments"] == 1
    assert result["variant_caller_run"] is False
    with pytest.raises(ValueError):
        audit_bam(str(path), sites, {"chr1": 999})
