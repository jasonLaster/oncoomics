# HCC1395 WGS HRD Interpretation Rehearsal

- Date: 2026-07-18
- Evidence run: `hcc1395-wgs-selective5-20260717`
- Overall evidence status: `partial_evidence`
- Authorized HRD state: `no_call`

## Scope and conclusion

This is a public known-answer rehearsal using SEQC2/HCC1395 tumor-normal WGS.
It is **not a Diana result**, does not contain Diana data, and cannot support a
biological or treatment conclusion about Diana.

The rehearsal establishes that the current workflow can carry deterministic
WGS mechanics into a bounded Rosalind-style reviewer packet and then present
that packet to independent qualitative model reviewers without erasing missing
inputs. It does not establish that HCC1395 is HRD-positive or HRD-negative. No
HRD-positive or HRD-negative classification is authorized: every scalar or
categorical HRD method remains `no_call`.

The named computational methods and the language-model reviews are different
things. scarHRD, SBS3 assignment, CHORD, and HRDetect require assay-derived
feature inputs and validated method-specific implementations. `gpt-5.6-sol`
and `gpt-5.6-terra` reviewed the evidence contract and reporting language; they
did not run, reproduce, or replace any of those analytical methods.

## Frozen evidence contract

The source is the committed
[Phase 3 WGS evidence-surface artifact root](../../artifacts/phase3_wgs_selective5/README.md).
It contains compact summaries from the June 12, 2026 full-source HCC1395 run,
so this rehearsal did not realign FASTQs, rerun variant calling, transfer large
BAMs, or touch the live Diana analysis.

The Rosalind packet builder indexed eight source artifacts with SHA-256 and
produced seven evidence rows plus seven adapter rows. Its authoritative outputs
are the [descriptive report](../../results/rosalind_hrd/hcc1395_wgs/hcc1395-wgs-selective5-20260717/report.md),
[evidence table](../../results/rosalind_hrd/hcc1395_wgs/hcc1395-wgs-selective5-20260717/sample_validation_summary.csv),
[adapter table](../../results/rosalind_hrd/hcc1395_wgs/hcc1395-wgs-selective5-20260717/hrd_adapter_status.csv),
[input evidence index](../../results/rosalind_hrd/hcc1395_wgs/hcc1395-wgs-selective5-20260717/input_evidence_index.json),
and [bound report manifest](../../results/rosalind_hrd/hcc1395_wgs/hcc1395-wgs-selective5-20260717/report_manifest.json).

| Bound packet file | SHA-256 |
| --- | --- |
| `report.md` | `81b8cf1e02918898a6b3420df06e8171c7d1df75d492ddc01041b1f4ca30e123` |
| `report_manifest.json` | `e86109a6219f503988b04c9503c8c8857bd2998ba5f0ec9148a546c5df7a25c0` |
| `sample_validation_summary.csv` | `ffbe4f4e01dcdfb36c80e7bef26d77ea300e014f90f728bec4026a7a618803b4` |
| `hrd_adapter_status.csv` | `36ce5450e9decf5f0c80d6ec13c535c171892214fd84dedd5aedd9b3ccdc7151` |

These hashes bind the report to the exact packet reviewed here. A later packet
must be treated as a new review input rather than silently substituted.

## Approach 1: deterministic WGS mechanics

### Process

The Phase 3 run used the full SEQC2/HCC1395 tumor and matched-normal WGS FASTQs
against the UCSC hg38 analysis-set reference. It aligned 568,040,077 read pairs
per FASTQ end, produced coordinate-sorted and indexed BAMs, ran BAM validation,
ran tumor-normal GATK Mutect2 plus FilterMutectCalls, compared calls in 295
truth intervals, generated 5 Mb tumor-normal coverage bins, built an SBS96
matrix from PASS SNVs, and counted BAM-derived split, supplementary,
discordant, and interchromosomal read evidence.

### Results

| Evidence surface | Observed result | Interpretation boundary |
| --- | --- | --- |
| FASTQ/BAM mechanics | Full-source inputs; BAM validation passed | Validates file and alignment mechanics only |
| Small variants | 300 truth-depth-eligible variants; 273 PASS records in the intervals; 268 exact PASS truth matches | Known-answer caller evidence, not an HRD score |
| Copy number | 631 coverage bins at 5 Mb | Coverage bins are not allele-specific CNV/LOH segments |
| Mutation matrix | 265 usable PASS SNVs in a 96-channel matrix | Matrix construction passed; SBS3 assignment did not run |
| Structural-variant evidence | Two tumor/normal evidence rows; 39,983,763 discordant mapped pairs in aggregate | Read counters are not a production somatic SV VCF or BEDPE |

The deterministic result is therefore a passed WGS mechanics rehearsal with
`partial_evidence`, not an HRD classification. The copy-number and SV outputs
are deliberately described as plumbing evidence because their richer
method-specific inputs do not exist in this artifact set.

## Approach 2: Rosalind-style packet interpretation

### Process

The packet builder read the frozen artifact root, verified each present source
artifact by SHA-256, normalized the evidence into reviewer-facing rows, and
recorded adapter-specific no-call boundaries. The committed packet can be
recreated with the same source root and a new immutable run ID:

```sh
ROSALIND_HRD_SAMPLE_SET=hcc1395_wgs \
ROSALIND_HRD_ARTIFACT_ROOT=artifacts/phase3_wgs_selective5 \
ROSALIND_HRD_RUN_ID=<new-immutable-run-id> \
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet
```

### Results

All seven evidence rows were materialized and none of the eight indexed source
artifacts was missing. The packet correctly retained the distinction between
mechanical success and interpretability:

- BAM, small-variant, coverage-bin, SBS96-matrix, and SV-counter lanes passed
  their bounded checks.
- Allele-specific CNV/LOH, a validated production SV callset, completed
  signature assignment, and integrated-model calibration were absent.
- The packet-level state remained `partial_evidence`; the only authorized HRD
  conclusion remained `no_call`.

This is the appropriate Rosalind result: the packet is useful for review and
for planning the missing lanes, but it does not promote a readiness signal into
a biological classification.

## Approach 3: analytical HRD cross-checks

No analytical cross-check below produced a score or class in this rehearsal.
The table records what was available, the exact missing input contract, and the
result that follows from those gaps.

| Method | Available evidence | Exact missing input or validation | Result |
| --- | --- | --- | --- |
| scarHRD | 631 real 5 Mb tumor-normal coverage bins | Validated allele-specific segments containing total and minor copy number, plus purity and ploidy | `no_call` |
| SBS3 / SigProfiler assignment | A real SBS96 matrix with 265 usable PASS SNVs | Completed signature assignment with reconstruction metrics, a locked minimum-mutation and SBS3 interpretation policy, and known-answer performance | `no_call` |
| CHORD | Somatic small-variant output, coverage plumbing, and BAM-derived SV counters | Validated somatic SNV/indel features, a production somatic SV VCF or BEDPE, CNV context, completed feature extraction, and known-answer calibration | `no_call` |
| HRDetect | Partial small-variant, copy-number, and mechanical SV evidence surfaces | Locked six-feature model inputs including substitution, indel, rearrangement, and CNV/LOH features, plus validated model calibration | `no_call` |

The important negative result is methodological, not biological: these methods
were unavailable because required inputs and validated adapters were missing.
Their `no_call` states must not be rewritten as HRD-negative.

## Approach 4: `gpt-5.6-sol` narrative audit

### Process

An independent `gpt-5.6-sol` pass reviewed the bounded packet as a qualitative
narrative reviewer. It was asked to separate measured observations from
inference and to check whether the available evidence could support any of the
named HRD outputs. It did not receive authority to infer missing assay results
or to substitute prose for a computational method.

### Results

The audit agreed with the packet's fail-closed conclusion. It identified the
full-source BAM and caller checks, 268 exact PASS truth matches, 631 coverage
bins, 265 SBS96 input SNVs, and mechanical SV evidence as real observations.
It separately identified the absent allele-specific copy-number solution,
production SV callset, signature assignment and thresholds, and integrated
model calibration. Its conclusion was `partial_evidence` with overall
`no_call`, with no scarHRD, SBS3, CHORD, or HRDetect output to cross-check.

This audit improved the explanation of the evidence boundary. It supplied no
new sample-derived measurement and no independent HRD classification.

## Approach 5: `gpt-5.6-terra` adversarial audit

### Process

A separate `gpt-5.6-terra` pass read the same bounded evidence as an adversarial
report reviewer. Its job was to look for language or schema choices that could
allow a downstream reader or model to overstate the result.

### Results

The audit preserved `partial_evidence` and `no_call`, but found two reporting
hazards in the committed packet:

1. The top-level operational blocker list was empty even though method-level
   interpretation gaps remained active. A reader who skipped the adapter table
   could mistake “no operational blockers” for “ready to interpret.”
2. The legacy SBS96 state label could be read as though a classification
   threshold had passed, although only the input matrix existed and assignment
   had not run.

The required disposition is to surface interpretation gaps prominently and
separately from operational/data blockers, and to describe the SBS state as
“input matrix available; assignment not run.” The audit found no basis for a
biological HRD call. Like the narrative audit, it contributed a reporting
quality check rather than an assay-derived result.

The disposition was exercised in a disposable regeneration from the same
frozen source root, without replacing the committed packet above. The patched
renderer retained `operational blockers=[]` while separately surfacing five
active interpretation gaps:

- `SigProfilerAssignment`: `input_matrix_ready_assignment_not_run`.
- `sigprofiler_sbs3`: `no_call`; needs a validated SBS96/SBS288 matrix,
  reconstruction metrics, and locked minimum-mutation policy.
- `scarhrd`: `no_call`; needs allele-specific total/minor copy number, purity,
  and ploidy.
- `chord`: `no_call`; needs validated somatic SNV/indel features, a production
  SV VCF/BEDPE, and CNV context.
- `hrdetect`: `no_call`; needs locked six-feature inputs and calibration.

All 41 focused packet tests passed after that rendering change. This verifies
the reporting disposition, not a new HCC1395 assay result; the frozen hashes
above remain the evidence identity for this report.

## Cross-approach synthesis

| Approach | What it independently contributes | Current conclusion |
| --- | --- | --- |
| Deterministic WGS mechanics | Reproducible measurements and known-answer caller evidence | Mechanics passed; `partial_evidence`; HRD `no_call` |
| Rosalind-style packet | Hashed provenance, evidence-layer separation, and adapter readiness board | Packet complete for its bounded purpose; HRD `no_call` |
| scarHRD / SBS3 / CHORD / HRDetect | Would provide orthogonal assay-derived HRD scores or classifications | Not run; required inputs missing; each `no_call` |
| `gpt-5.6-sol` | Independent narrative boundary audit | Agreed with `partial_evidence` / `no_call` |
| `gpt-5.6-terra` | Independent adversarial schema and wording audit | Found two over-read hazards; preserved `no_call` |

The approaches are concordant only on the evidentiary boundary: the available
artifacts validate mechanics and packet construction, while HRD interpretation
remains unavailable. This is not multi-method biological concordance because
the four analytical methods have not yet produced results.

## What this rehearses for the future Diana workflow

Once a satisfactory deterministic Diana WGS result exists, the same sequence
can be applied without changing the evidentiary rules:

1. Freeze and hash the deterministic artifacts.
2. Build the Diana Rosalind packet and preserve all `partial_evidence`,
   `no_call`, and `blocked` states.
3. Run only analytical methods whose exact input contracts are satisfied.
4. Generate one descriptive report per method, including versions, inputs,
   parameters, QC, outputs, limitations, and an authorized conclusion.
5. Give independent qualitative models the source reports for narrative and
   adversarial review, while making clear that they cannot replace the methods.
6. Compare the resulting evidence by assay layer and explain disagreements
   rather than collapsing them into a single unsupported score.

Until those Diana-specific deterministic and method-specific artifacts exist,
this HCC1395 rehearsal remains a workflow validation artifact and nothing more.
