# Diana WGS HRD early-look handoff

This Git-tracked handoff documents the matched tumor-normal WGS early-look run.
The reviewed analysis is publicly available under a pseudonymous alias; Git
retains the narrative handoff rather than local mirrors of evidence objects.

- Full-run ID: `diana-wgs-hrd-20260716T033101Z`
- Successful early-look ID: `early-look-intersected-20260716T150517Z`
- Successful AWS Batch job: `a1aa4109-4b38-46a4-9b58-bfe6335b02d4`
- Early-look completion: 2026-07-16 08:32:54 PDT
- Evidence state: `partial_evidence`
- Overall HRD state: `no_call`

Start with [HANDOFF.md](HANDOFF.md), then [NEXT_STEPS.md](NEXT_STEPS.md).
Current public URLs and the publication boundary are in
[PUBLIC_DATA.md](PUBLIC_DATA.md).

## Public analysis boundary

The data owner explicitly authorized unrestricted public distribution of the
analysis. The reviewed public alias contains small derived analysis and report
artifacts reheadered to `subject01_normal` and `subject01_tumor`. Raw FASTQs,
BAMs, contamination pileups, direct source identifiers, operational logs, and
version-history/custody inventories remain outside the public alias.

`PUBLIC_S3_MANIFEST.tsv` is retained only as a historical record of the original
2026-07-16 publication. Its old paths and broad bucket-access statements are
superseded by the current publication manifest linked from `PUBLIC_DATA.md`.

The recovered pre-data Rosalind packets are also public for protocol provenance,
but are explicitly labeled superseded because they report
`waiting_for_diana_raw_data` and `no_call`. Current HRD interpretation must use
the deterministic early-look evidence and the final frozen WGS contract.
