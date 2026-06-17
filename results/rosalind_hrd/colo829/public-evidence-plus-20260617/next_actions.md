# Next Actions: COLO829/COLO829BL Tumor-Normal Guardrail Packet

## Blockers
- COLO829 submitted BAMs and fetched hg38-lifted truth still require build reconciliation.
- No Diana SV/CNA callset exists.
- COLO829 submitted BAMs are GRCh37-style while the fetched SV truth VCF is hg38-lifted.
- Selected purity BAMs require full transfer or local indexing before monotonic recall can be tested.

## Recommended Order
- Preserve this packet as the run boundary before recompute.
- Fix missing or blocked adapters before rerunning only the affected lane.
- Add research context only after sample-derived event evidence exists.
