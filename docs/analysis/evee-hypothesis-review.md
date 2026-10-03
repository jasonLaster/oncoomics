# EVEE hypothesis validation

Use this protocol to test reported biological hypotheses against independently
verified sample evidence. Keep patient findings, assay values, regional BAMs,
identifiers and source receipts under private storage. The reusable methods are
documented in [metadata-held matrix diagnostics](../scrna-exploratory.md).

## Evidence ladder

Each hypothesis needs distinct answers for allele reality, functional direction,
pathway state, biological dependency and intervention relevance. A pathogenicity
prediction supplies none of the last four automatically. A predicted stop-gained
consequence is a truncating-allele hypothesis, not confirmed complete gene loss;
allelic state, transcript usage, protein and functional evidence still matter.
Gene RNA can remain detectable from the other allele, other cells or transcripts.

1. Freeze matched tumor/normal inputs, build, reference, versions and full hashes.
   Resolve the actual somatic VCF, filters, depths, allele fractions, transcript
   identifiers and numeric model scores. An absent public model result is missing
   evidence, not a benign classification.
2. Reproduce REF and transcript consequences. Preserve every transcript and
   distinguish MANE translation from functional evidence. Check original alignments
   with overlapping mates collapsed, nonprimary alignments excluded and quality
   sensitivities retained. A raw two-read signal can be one physical fragment, or
   only supplementary alignments.
3. Qualify specimen identity and malignant-cell origin before comparing assays.
   Keep capture/library namespaces separate, inspect ambient and doublet
   sensitivity, and avoid cell-level tests that pretend one sample supplies
   thousands of independent biological replicates.
4. Test the proposed functional direction against an explicit competing mechanism.
   Require target engagement, rescue controls and a relevant model before promoting
   a dependency. Keep RNA abundance, protein amount and dynamic activity separate.

## Falsifiable mechanisms

| Axis | Mechanistic uncertainty | Smallest useful functional discriminator after allele confirmation |
| --- | --- | --- |
| ATG4B / ATG13 / RB1CC1 | One allele in each gene need not establish triple-hit autophagy loss in the same malignant clone. A damaged upstream pathway need not gain further benefit from downstream lysosomal inhibition. | Resolve second hits and the complete splice allele; distinguish formation from clearance with LC3 turnover with and without lysosomal blockade, p62 turnover and a complementary flux assay. Test proteasome stress sensitivity with target engagement and genetic rescue. |
| MTOR | Disruption does not specify activation. Component RNA and total protein do not measure mTORC1/2 activity. | Check mutant-versus-wild-type function, nutrient sensitivity, phospho-S6 and phospho-4EBP1, plus phospho-AKT where relevant. Demonstrate growth dependency and pathway suppression separately. |
| SCAP / RXRA / PPARD | SCAP loss and a sterol-insensitive SCAP allele are different mechanisms. Lipid uptake, synthesis and isoprenoid requirements can yield different responses. An RXRA truncation need not predict RXR agonist sensitivity. | Measure nuclear SREBP processing and uptake/synthesis under controlled lipid conditions. Separate mevalonate, cholesterol and isoprenoid rescue experiments. Confirm receptor protein and transcriptional function. |
| CUL3 / NRF2 / ferroptosis | A CUL3 missense allele does not establish KEAP1-substrate failure. NRF2-associated protection and state-dependent GPX4 dependency are competing predictions. | Check nuclear NRF2 and a coordinated target panel; distinguish system-Xc blockade from direct GPX4 inhibition, measure lipid peroxidation, and require ferroptosis-specific rescue and appropriate controls. |
| DLL4 / Notch / Wnt | Ligand disruption need not mean activated signaling. Vascular and malignant-cell effects are distinct. | Localize the ligand/receptor, test NICD and transcriptional output in the relevant compartment, and use a ligand-dependent coculture or reporter with an orthogonal perturbation. |
| FGFR4 | Extracellular missense changes cannot inherit evidence for kinase-domain hotspots. | Confirm receptor expression, ligand/coreceptor context, mutant phosphorylation and downstream signaling; test actual inhibitor engagement and rescue. |
| BRD3 / BET | A regulatory-tail variant does not establish bromodomain addiction, and family-level inhibition need not depend on the reported BRD3 allele. | Compare mutant and wild-type chromatin engagement and genetic dependency; test transcriptional response and rescue across relevant BET family members. |

Autophagy needs dynamic, complementary measurements; static LC3 or transcript
levels cannot determine flux. [Autophagy assay guidelines](https://pubmed.ncbi.nlm.nih.gov/33634751/).
Breast-model FIP200 studies separate canonical autophagy from effects on immune
signaling. [FIP200 breast-model study](https://pubmed.ncbi.nlm.nih.gov/32580962/).

Functional studies of activating MTOR alleles do not validate every MTOR missense
allele. [Grabiner et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC4012430/).
SCAP-dependent SREBP signaling affects both uptake and synthesis, and breast-cell
statin response can depend on HMGCR feedback. [SCAP/SREBP functional study](https://www.nature.com/articles/s41467-020-14811-1),
[breast-cell statin resistance study](https://www.nature.com/articles/s41419-019-1322-x).

NRF2 activation protected glioma models from ferroptosis; this supplies a competing
prediction, not a universal TNBC result. Brusatol is not a selective NRF2 mechanistic
probe. [NRF2/ferroptosis study](https://www.nature.com/articles/oncsis201765),
[brusatol protein-synthesis study](https://pubmed.ncbi.nlm.nih.gov/26711467/).

DLL4 blockade can act through abnormal angiogenesis rather than a tumor-cell
differentiation mechanism. [DLL4 angiogenesis study](https://pubmed.ncbi.nlm.nih.gov/17183323/).
FGFR4 hotspot experiments concern specific activating kinase alleles in
rhabdomyosarcoma, and the original JQ1 experiments establish bromodomain inhibition
in a different biological context. [FGFR4 functional study](https://pubmed.ncbi.nlm.nih.gov/19809159/),
[BET bromodomain study](https://pubmed.ncbi.nlm.nih.gov/20871596/).

## Review output

For every axis retain: exact alleles and transcripts; original report claim;
independent evidence and its confidence boundary; supported and competing
predictions; the observation that would disprove each prediction; the smallest
validation assay; specimen and QC dependencies; source versions; and a separate
clinical evidence state. Rank next experiments by information gained, not by the
novelty of a suggested drug. Do not promote a hypothesis using expressive RNA,
a model score or a successful compute receipt alone.
