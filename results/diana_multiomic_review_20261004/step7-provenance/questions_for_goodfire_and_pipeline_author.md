# Draft questions: EVEE "Soft Star" report authors and the July 17 WGS pipeline author (PRIVATE, DRAFT, NOT SENT)

Research prioritization only. Nothing here has been sent; the user decides whether, how and to whom. Keep under git-ignored
`private/`. Do not paste patient findings into any public channel.

Who to ask is itself partly inferred (see `provenance_report.md` section 2):
- The July 17 plain-language summary is attributed in the user's notes to **EnJun Yang** (research-use WGS analysis; arrived as a
  Gmail attachment 2026-07-17 and again 2026-07-23; a supporting Google Drive folder is recorded in the vault source metadata).
- The 08-11 EVEE PDF is titled "Soft Star Report" and its disclaimer says "**K2** supports research...". K2 is the name of the Yuga
  (YugaBio) agent-orchestration platform (a June 30 copy of that repo is on this machine). It was downloaded from Google Drive on
  2026-08-13. So the report was most likely produced by an LLM-agent workflow on Yuga's K2 that *used* Goodfire's public EVEE/ClinVar
  dataset, not by Goodfire. Confirm this before writing to Goodfire at all.

## A. To the July 17 pipeline author (EnJun) - recover the callset and its settings

1. Can you share the **final somatic VCF(s)** behind "~16,000 tumor mutations", per caller and the merged set, with FORMAT AD/DP/AF
   for tumor and normal and the FILTER column intact? If they were deleted, which run directory/bucket held them and is any copy
   (Drive, object-store versioning, Nextflow `work/`, `results/`) recoverable?
2. Which **two callers** (name + version: e.g. Mutect2 4.x, Strelka2 2.9.x, MuSE, VarScan2, DeepSomatic?) and how were they combined:
   **intersection** of PASS calls, union, or "called by >=2 of N"? Was it applied to SNVs only, or indels too (Strelka2 indels vs
   Mutect2 indels)? Was consensus position-only or position+allele?
3. Mutect2 settings: panel of normals (which; 1000G PoN?), germline resource (gnomAD AF-only?), `--f1r2-tar-gz` +
   `LearnReadOrientationModel` used (yes/no), `CalculateContamination` (the summary says contamination QC was not run - so was
   `FilterMutectCalls` run without `--contamination-table`?), `--min-base-quality-score`, any `--max-reads-per-alignment-start` /
   `--dont-use-soft-clipped-bases` changes. Was `FilterMutectCalls` PASS required, or were `weak_evidence`/`orientation` calls kept?
4. Were there **post-filters** on tumor alt reads / VAF / depth (e.g. tumor AD >= 3, VAF >= 5%, normal depth >= 10)? Were overlapping
   read mates de-duplicated before counting support (i.e. could one fragment whose two mates both carry the ALT count as 2 reads)?
5. Alignment: reference (GRCh38 analysis set / with alt contigs / hs38DH?), aligner + version, duplicate marking, BQSR, which of the
   16 FASTQs per sample (4 lanes x R1/R2 x tumor/normal) went where.
6. Was any **tumor-only** or "rescue" mode used for some regions (e.g. low-normal-depth sites)?
7. **HRD 62**: which tool chain produced LST 27 / TAI 26 / LOH 9 (Sequenza + scarHRD? ASCAT? FACETS?), versions, purity/ploidy of the
   fit actually used, number of segments, and the exact **"software setting"** that was changed between the "misleadingly low" run
   and the 62 run (old value, new value, old score). Was the change made after seeing the result?
8. "**Biallelic BRCA1**": what was the BRCA1 segment's total and minor copy number, the purity used, and the BRCA1 c.81-1G>A tumor
   VAF/depth in your data? What "separate BRCA report" was it compared with?
9. Tumor/normal identity and contamination were not run and intermediates were removed: which intermediates (BAMs, pileups,
   per-caller VCFs) and when? Are the aligned BAMs still anywhere (md5 would let us check they match ours)?
10. How was the ~5 mutations/Mb computed (genome size, callable size)? How many of the 16,000 are coding/protein-altering?

## B. To the EVEE report producer (Soft Star / K2 run owner; Goodfire only if they actually ran it)

1. What exact **input file** was used for "607 somatic variants from matched tumor/normal WGS (Personalis pipeline)": file name,
   checksum, who supplied it, and what "Personalis pipeline" means (the Personalis delivery contains no somatic VCF/MAF)? Was it the
   July 17 annotated table?
2. How were the **607 selected** from the full callset (VEP impact HIGH+MODERATE only? coding only? a gene list? a VAF/depth filter?)
   Please share the 607-row table with tumor/normal AD, DP and VAF per variant.
3. The report states scoring was a coordinate join to the EVEE ClinVar parquet (4.25M variants). Goodfire's public EVEE/ClinVar
   service returns **not_found for 8 of the 9 tier-1 SNVs** (only CUL3 R354C is present, pathogenicity 0.4003, ClinVar VUS), and
   Ensembl reports no dbSNP/ClinVar record at 7 of the 9 positions. Where did "LoF confirmed", "high disruption" and
   "moderate-high disruption" come from for MTOR, SCAP, RXRA, DLL4, ATG4B, ATG13, FGFR4, BRD3? Were EVEE probes run de novo
   (which model checkpoint, which probe, which score threshold), or were labels written by the language-model agent?
4. Please send the **numeric EVEE outputs** (pathogenicity, effective pathogenicity, splice disruption, top disruption deltas) for all
   ~512 scored SNVs, and the threshold that defined "high disruption".
5. How were the **9 tier-1 variants selected** (rank order, cutoff, gene list of "therapeutically actionable" genes)?
6. The tier-1 header says "VEP = MODERATE" but SCAP W633*, RXRA S96* and ATG4B W142* are stop_gained (VEP HIGH). Which VEP version and
   transcript set were used (MANE? canonical? `--pick`?)
7. RB1CC1 "splice donor (chr8:52624715)" and PPARD p.Gln415His have no alleles in the report: what were REF/ALT and HGVSc?
   Same for WNT2B p.Leu39Pro, WNT6 p.Ser88Pro, LIN28A p.Ala24Val, FZD10 p.Ala19Val, CBL p.Asp460del, ARIH2 p.Glu29del, SHH p.Gln209Ter,
   KMT5B and HDAC4 (no change given).
8. The report says "TSC complex intact (no variants detected)". Was TSC2 in the 607 input or excluded by a filter? (A TSC2 missense is
   listed by the clinical exome.) Likewise MTOR p.Pro1125Ala: present in the input or not?
9. Was any human review done before release, and was the report generated by an automated agent end-to-end?

## C. What we would do with the answers

- Re-genotype every one of the 607 (and, ideally, all ~16,000) in the deep exome/WGS with the fragment-level audit already built
  (`step3-exome-evee`, `step7-provenance/scripts/03_audit.py`), giving an exact false-positive rate rather than the sampled estimate in
  `provenance_report.md`.
- Re-run HRD from the same allele-specific fit with and without the "setting" to see whether 62 is setting-sensitive.
