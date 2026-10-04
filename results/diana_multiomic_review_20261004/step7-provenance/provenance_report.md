# Step 7: provenance of the July 17 summary and the 08-11 EVEE report, and what the somatic data support (PRIVATE)

Research prioritization only; no clinical claim. Git-ignored (`private/`); never commit. Generated 2026-10-03.
Tags: **[E]** documented/observed, **[I]** inference (reasoning given), **[U]** unknown.
Companions: `reconciled_somatic_findings.md` (per-variant table, drop list), `questions_for_goodfire_and_pipeline_author.md`
(draft, not sent), `README.md` (commands, bytes), `results/` (machine-readable).

## 0. Bottom line

1. **No callset behind either report exists anywhere we can reach [E].** Not in any git ref (1,691 commits, all branches), all 11 linked
   worktrees, `/private/tmp/diana-*`, `private/`, `results/`, ~/Downloads, the vaults, or any of the 12 S3 buckets (current objects,
   1,370 noncurrent versions, 1,187 delete markers). The only patient variant callset in this AWS account is the repo's own 15-gene
   Mutect2 early look (484 records, 39 PASS). The three `work` buckets are empty and expire everything after 14 days [E].
2. **Neither report was produced by this repo [E/I].** "HRD score of 62", "LST 27", "16,000" (as mutations), "software setting",
   "Soft Star" and "K2" occur in no git ref. The July 17 summary arrived as a Gmail attachment on 2026-07-17 (and again 07-23) and is
   attributed in the user's notes to **EnJun Yang** (RUO WGS analysis, Drive folder recorded) [E]. The EVEE PDF was downloaded from
   Google Drive on 2026-08-13; it is titled "Soft Star Report" and its disclaimer names **K2**, which is the name of Yuga's agent
   platform (local repo `~/src/projects/yuga-bio/k2`, "Agent Orchestration") [E]; so it was most likely written by an LLM-agent run on
   K2 that used Goodfire's public EVEE/ClinVar data, not by Goodfire [I].
3. **The EVEE method as written cannot have produced its tier-1 labels [E].** It describes a coordinate join to the EVEE ClinVar
   parquet ("covers only SNVs present in ClinVar"). Goodfire's public EVEE/ClinVar service returns not_found for 8 of the 9 tier-1
   SNVs (CUL3 R354C is the only hit: pathogenicity 0.40, ClinVar VUS), and Ensembl reports no dbSNP/ClinVar record at all at 7 of 9
   positions (DLL4 has an rsID but no ClinVar entry). The labels "LoF confirmed / high disruption" therefore came from somewhere else
   (unknown; possibly the agent's own narrative) [I].
4. **Zero of 18 EVEE-only variants reproduce [E].** All 17 placeable EVEE-only alleles (plus RB1CC1, reference at the reported base)
   show 0 ALT fragments in the deep exome (72-793x), are absent from Altera's 132-variant table, and carry exactly 1-2 WGS tumor
   fragments. Under a binomial model 0/17 gives a 95% upper bound of 16% on the fraction of these that are real (selection caveat:
   these were chosen for "disruption", not at random). The one EVEE-named variant that is real (PIKFYVE I1548T) is also an Altera call.
5. **The source list is single-molecule-dominated and depth-biased [E], i.e. a lenient WGS call set [I].** The EVEE-only alleles sit
   where WGS tumor depth is low (median 11.5 fragments vs 29 at Altera sites, Mann-Whitney p=1.3e-4; tumor/normal depth ratio 0.24 vs
   0.60, p=5.6e-4), i.e. in copy-loss regions, where one read pair is a 7-14% "VAF" against a 45x normal with zero ALT. At 7 of 9
   tier-1 sites both mates of the single fragment carry the ALT (step 3), so a read-counting caller sees 2 ALT reads. The repo's own
   Mutect2 early look on the same BAMs passes 28 of 37 non-coding PASS calls on 2-3 ALT reads. SHH Q209* (the July 17 "pathogenic SHH"
   and the EVEE "1 pathogenic call") is one of these singletons (exome 0/686), which ties the EVEE input to the July 17 annotation
   [I, moderate]. The CBL D460del in the report is a GAT-repeat stutter seen in the matched normal exome too (8/722 reads).
6. **The same list misses real events [E/I].** TP53 c.559+2T>G (exome 441/1269 = 34.8%, WGS 10/18, normal 0/837 and 0/47, the
   highest-VAF truncal event) is mentioned by neither report; TSC2 R59W (10.7%) is present although EVEE says "TSC complex intact";
   MTOR P1125A (9.4%, WGS 4/38) is not discussed while MTOR G98S (1 fragment) is the mTOR headline.
7. **New: the tumor DNA datasets are not one aliquot [E].** Altera and the exome agree closely on 112 variants (median exome/Altera VAF
   ratio 1.02), but 9 Altera variants at 5-10% are present in WGS (3-7 fragments, normal 0; pooled WGS VAF 10%) and **absent** from
   the exome and tumor RNA (0/163-0/580), and 5 more sit at 1-2% in the exome. So a ~10% subclone is in the Altera block and the WGS
   but nearly absent from the Personalis exome/RNA material [I: spatial or aliquot heterogeneity]. This does not rescue the EVEE
   alleles (Altera, which shares that subclone, lists none of them; their WGS support is one molecule), but it means exome absence
   alone is not proof of absence, and specimen identity statements should say "same tumor, different regions/aliquots".
8. **HRD 62 is unresolved [U].** No code, config or output for it exists on disk or S3; the "software setting" is undocumented
   anywhere we can read. The repo's July 22 scarHRD (LST 28 / TAI 20 / LOH 24) comes from a fit already flagged as broken.

## 1. The EVEE PDF (2026-08-11), complete extraction

Source: `private/evee/deep-20261003/source_reports/08-11-wgs-evee-variant-interpretation-report.pdf` (6 pages, 66,781 bytes, Typst
0.13.0, created 2026-08-11 16:43 PDT; byte-identical to `~/Downloads/WGS_EVEE_Variant_Interpretation_Report.pdf`, downloaded from
Google Drive 2026-08-13). No appendix, footnotes, references list, VAF, depth, caller, filter, build statement or file name exist in it.

Methods as stated (verbatim facts, paraphrased):
- Input: "607 somatic variants from matched tumor/normal WGS (Personalis pipeline)". No file name, caller, filters or VAF/depth.
- Scoring: coordinate join against "EVEE ClinVar Parquet (4.25M variants, 5 shards, 33GB)"; variant ID `{chrom}:{VCF_POS-1}:{REF}:{ALT}`.
- "EVEE covers only SNVs present in ClinVar"; ~95 indels/complex unscored. Build implied GRCh38 (coordinates match GRCh38 MANE).
- Counts: 607 total; ~512 SNVs "eligible"; ~95 indels; ~85 VEP HIGH (14.0%); ~522 VEP MODERATE (86.0%). HIGH+MODERATE = 607, so the
  input was a protein-altering subset (no LOW/MODIFIER) [I].
- Selection of the 9: "EVEE predicted pathogenic, VEP = MODERATE, no ClinVar pathogenic flag". No numeric scores or thresholds.

Internal inconsistencies [E]: (a) three tier-1 rows are stop_gained (VEP HIGH) under a "VEP = MODERATE" header; (b) ~512 SNVs called
"eligible" although only ClinVar SNVs can be joined and 8/9 tier-1 SNVs are not in the public EVEE/ClinVar set; (c) "TSC complex intact"
vs a 10.7% TSC2 missense; (d) FGFR4 S106 is described as kinase-adjacent but is in Ig-like domain 1, BRD3 S676 is outside both
bromodomains (step 3 / Codex review); (e) "de novo" scoring described as a lookup.

Every variant named in the PDF:

| Gene | As written | GRCh38 | Report claim | Exome T (frags) | Exome N | WGS T (frags) | Altera | Verdict |
|---|---|---|---|---|---|---|---|---|
| MTOR | p.Gly98Ser | chr1:11257145 C>T | high disruption; everolimus | 0/793 | 0/426 | 1/10 | absent (lists P1125A) | not reproduced |
| SCAP | p.Trp633Ter | chr3:47419370 C>T | LoF confirmed; statin | 0/293 | 0/214 | 1/12 | absent | not reproduced |
| RXRA | p.Ser96Ter | chr9:134408156 C>A | LoF confirmed; bexarotene | 0/299 | 0/180 | 1/9 | absent | not reproduced |
| CUL3 | p.Arg354Cys | chr2:224506102 G>A | high disruption; NRF2 | 0/190 | 0/36 | 2/47 | absent | not reproduced |
| DLL4 | p.Arg516Cys | chr15:40936533 C>T | high disruption; anti-DLL4 | 0/258 | 0/176 | 1/11 | absent | not reproduced |
| ATG4B | p.Trp142Ter | chr2:241655311 G>A | LoF confirmed; autophagy | 0/201 | 0/108 | 1/17 | absent | not reproduced |
| ATG13 | p.Asp213Gly | chr11:46657565 A>G | high disruption | 0/285 | 0/124 | 0/25 (step 3: 1 supplementary-only) | absent | not reproduced |
| FGFR4 | p.Ser106Phe | chr5:177090615 C>T | moderate-high; FGFR inhibitor | 0/678 | 0/614 | 1/9 | absent | not reproduced |
| BRD3 | p.Ser676Gly | chr9:134034740 T>C | moderate; BET inhibitor | 0/372 | 0/177 | 1/11 | absent | not reproduced |
| RB1CC1 | splice donor chr8:52624715 | (no alleles) | autophagy initiation abolished | ref 435/435 | ref | n/a | absent | not reproduced |
| PPARD | p.Gln415His | chr6:35425998 G>C (only SNV giving Q>H) | lipid rewiring | 0/653 | 0/290 | 1/16 | absent | not reproduced |
| WNT2B | p.Leu39Pro | chr1:112509378 T>C (unique SNV) | Wnt | 0/121 | 0/69 | 1/7 | absent | not reproduced |
| WNT6 | p.Ser88Pro | chr2:218871208 T>C (unique) | Wnt | 0/422 | 0/211 | 2/15 | absent | not reproduced |
| LIN28A | p.Ala24Val | chr1:26411425 C>T (unique) | stem regulator | 0/136 | 0/81 | 1/9 | absent | not reproduced |
| FZD10 | p.Ala19Val | chr12:130162998 C>T (unique) | Frizzled | 0/72 | 0/84 | 1/8 | absent | not reproduced (exome 72x) |
| CBL | p.Asp460del | chr11:119278646 3-bp del (GAT repeat) | E3 ligase | 38/2067 reads | **8/722 reads** | 3/28 | absent | repeat-stutter artifact |
| ARIH2 | p.Glu29del | (no allele) | RBR E3 ligase | none in any window | none | none | absent | not reproduced |
| SHH | p.Gln209Ter | chr7:155803664 G>A (unique) | "1 pathogenic (VEP-only)" | 0/686 | 0/535 | 1/14 | absent | not reproduced |
| PIKFYVE | p.Ile1548Thr | chr2:208338539 T>C | mTOR/PI3K bullet | 15/173 (8.7%) | 0/61 | 7/45 | 12% | **confirmed** |
| KMT5B, HDAC4 | (no change given) | - | BET rationale | - | - | - | - | untestable |
| BRCA1 | "BRCA1 loss" (no change) | - | PARP axis | 22.4% (c.81-1G>A) | 0 | 4/23 | 27% | confirmed (the c.81-1 allele) |

For the seven variants without reported coordinates, the protein change mapped to exactly one possible SNV across all Ensembl
transcripts, so no candidate was chosen post hoc; every one of those unique alleles has exactly 1-2 WGS tumor fragments, which
indicates the report's input list was derived from these WGS reads [I, strong].

## 2. Where the reports came from and what was deleted

| Item | Finding | Tag |
|---|---|---|
| July 17 summary file | `~/Downloads/DRF-PSN49561_Analysis_Summary.md`, Gmail attachment (thread id in `kMDItemWhereFroms`), added 2026-07-17 23:03 UTC; identical copy re-downloaded 07-23; identical to the vault/source-report copies | E |
| July 17 author | vault source note `07-30-enjun-patient-sequencing-analysis.md`: `source_author: En Jun`, plus a Google Drive folder link; emails 07-22/07-24 describe "EnJun ... RUO analysis of WGS" and his BRCA1 deletion call | E (as recorded by the user's notes) |
| July 17 inputs | "All 16 data files passed integrity checks" = exactly the 16 DRF-PSN49561 WGS FASTQs (tumor lanes 5-8, normal lanes 1-4, R1/R2) in the Personalis delivery manifest; stated depth 35-40x | E (count) / I (identity) |
| July 17 pipeline code | not in this repo (no trace of 62/LST 27/TAI 26/"software setting" in any ref) nor anywhere on this machine; the June 30 Yuga K2 checkout contains only generic agent "skills" (Mutect2/Strelka2 workflow, scarHRD usage), no Diana outputs | E |
| "Two methods agreed" | callers and combination rule undocumented | U |
| Intermediates "removed" | per the summary itself; nothing recoverable here. This account's `work` buckets expire all objects at 14 days and are empty; results buckets hold only the repo's own runs | E |
| EVEE PDF | Drive download 2026-08-13; "Soft Star Report"; "K2 supports research..."; claims Goodfire EVEE (Evo2) scoring | E |
| EVEE producer | K2 = Yuga agent-orchestration platform (repo name and README); Yuga's team (Pavan Ramkumar) introduced 2026-04-30, EnJun in the 08-24 review with Yuga | I (strong) |
| 607-variant input | no file anywhere; "Personalis pipeline" is not a Personalis deliverable (the delivery has no VCF/MAF) | E/U |
| Link EVEE <-> July 17 | shared distinctive SHH Q209* singleton; "prior analysis" pathways (HRD, Hedgehog, Epigenetic) match July 17 | I (moderate) |
| HRD 62 code path | none found; the "software setting" is unknown | U |
| Repo-side HRD | July 22 Modal Sequenza->scarHRD: LOH 24 / TAI 20 / LST 28 (sum 72), fit flagged unreliable (next-steps item 4) | E |

Searched: `git grep` across all 1,691 commits for DRF-PSN49561, 16,000, two independent, Strelka, consensus, HRD score of 62, LST 27,
607, software setting, Soft Star, K2 supports (+ numeric regexes for LST/HRD-sum); filesystem find for *.vcf*, *.maf*, *somatic*,
*consensus*, *strelka*, *scarhrd*, *607* under the repo, 11 linked git worktrees, `~/.codex/worktrees`, `/private/tmp/diana-*`, ~/Downloads and
the diana-tnbc vaults; Spotlight; S3 `ls --recursive` of all 12 buckets in us-east-1/us-east-2/us-west-1 plus `list-object-versions`
(noncurrent + delete markers) on the versioned ones. Not searched (outside this task's scope; the user can): the Gmail thread that
delivered the July 17 file, EnJun's Drive folder recorded in the vault note, and whatever storage K2 used.

## 3. Comparison with the deep exome (task 3)

No callset was recovered, so instead of a full false-positive census I re-genotyped every variant named in any of the four sources
(149 protein/splice changes -> 247 candidate SNVs/indels over all transcripts; 196 regions) in tumor/normal exome, tumor RNA and
tumor/normal WGS. Full table: `reconciled_somatic_findings.md`.

| Source | Reproduced | Not reproduced | Notes |
|---|---|---|---|
| EVEE-only (18) | 0 | 18 | 0/17 placeable alleles in exome; each 1-2 WGS fragments; CBL is stutter present in normal |
| July 17 named (3) | 2 (BRCA1, BRCA2) | 1 (SHH) | TP53 c.559+2T>G not mentioned |
| Altera (132) | 112 exome + 9 WGS-only | 0 shown false | 9 unresolved (exome 0-1, WGS 0-2), 2 coordinates unresolved |

Estimated false-positive rate of the EVEE/July 17 source list [I]: among its distinctive (non-Altera) calls, 0/17 reproduce (95%
upper bound on true fraction 16%). By count, ~125-130 coding variants are seen by Altera/exome at 440-600x, while the EVEE input had
607 protein-altering calls; if all real coding variants were included, >=~78% of the 607 would be extra, and the sampled extras are
all non-reproducible. Best estimate: the large majority (plausibly 70-90%) of the 607 are artifacts; exact rate needs the file.
VAF profile of non-reproduced calls: all single-molecule (1-2 WGS fragments, nominal VAF 4-14%, inflated by low tumor depth in
copy-loss regions), 0 in RNA above noise; substitution classes C>T/G>A 9/15 (60%), the class elevated 3-5x in this tumor library's
damage background (step 3); orientation is uninformative with one fragment.

Most likely mechanism [I, ranked]: (1) a permissive somatic call set (union or a loose consensus, or a single caller with a low
ALT-read floor) on ~40x WGS where overlapping mates count as two reads, and tumor depth is halved in copy-loss regions while the normal
is deep and clean; (2) sequencing/FFPE-type damage singletons (C>T dominant) and repeat stutter (CBL); (3) protein-altering filter +
LLM-agent narrative selecting "disruptive-looking" genes, which enriches for exactly these noise calls. A WGS-private subclone carrying
these alleles cannot be excluded, but would have to be absent from the Altera block, which shares the WGS-visible ~10% subclone.

Specimen heterogeneity (new) [E]: the 9 Altera variants absent from exome/RNA but present in WGS (AP5M1 V407A, ATP13A3 K1040T, F5
E2057*, LPHN3 E37V, OTUD4 T1049P, PRRG1 R20I, SCN11A I1376M, SVOPL L81P, SYNJ1 G22E; WGS 3-7 fragments each, normals 0) plus 5 at
1-2% in exome (ARAF S490*/L527M/L598I, MRPS9, MUC2, OR51A4, RXFP4) define a subclone enriched in the Altera block and in the WGS
specimen relative to the Personalis exome/RNA specimen. Truncal events (TP53, BRCA1, BRCA2, TSC2, MTOR P1125A, ~100 others) are shared.
Implication for other steps: purity, CN and clonality estimated on the WGS may not transfer exactly to the exome/RNA specimen.

## 4. Unknowns that only the authors can close

The 607-row file; the ~16,000 VCF(s); caller names/versions and the merge rule; post-filters (min ALT reads, VAF, depth, mate
overlap); PoN/germline resource; orientation-bias filtering; contamination handling; the HRD tool chain, fit and the "setting";
how EVEE labels were produced for non-ClinVar variants; how the nine were chosen. Draft questions:
`questions_for_goodfire_and_pipeline_author.md`.

## 5. Side findings to flag (not acted on)

- **Public exposure:** git-tracked and pushed to origin/main: `manifests/evee_report_highlights.tsv`,
  `manifests/evee_report_highlights.workbench.json`, `results/evee_context/evee_report_highlights/variant_scores.csv` (the patient's EVEE
  variant list) and, per step 1, `results/diana_wgs_hrd/early-look-.../VARIANT_REVIEW.tsv` (BRCA1/BRCA2 calls). Decide whether that is
  intended; removal from history is a separate, irreversible-ish operation.
- `next-steps-20261003.md` section 4 lists "the July 17 in-house HRD 62" as one of several signals; given sections 0.2/0.8 it should be
  described as external, unreproduced, and from the same analysis that produced the non-reproducible variant list.
- The specimen-heterogeneity finding should be added to the step 1 ledger ("one tumor genome" stays true; "one aliquot" does not).

## 6. Limits

- Re-genotyping covers only variants that were *named*; the EVEE/July 17 false-positive estimate is from 17 selected calls, not a
  random sample of the 607/16,000.
- Protein-to-genome mapping used Ensembl GRCh37 `variant_recoder` over all transcripts (one candidate per change for every EVEE-only
  variant; several for some Altera changes, where the best-supported candidate is shown). KIAA1919 K213fs and MSH5 WF273CI could not
  be mapped. Frameshift/in-frame indels were tested only by a +/-12 bp scan (>=3 tumor fragments, normal 0, >=2%).
- WGS depth at these sites is 7-66 fragments, so WGS absence is weak evidence; exome noise floor is ~0.5-1% (step 3).
- Authorship statements rest on the user's own notes and file metadata, not on confirmation from the authors.
