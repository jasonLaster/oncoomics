# Draft questions (NOT SENT) - only what the data did not answer

Private; do not commit. Nothing here has been sent to anyone. Patient identifiers are deliberately left as placeholders:
add name/DOB/MRN only through the channel and authorization each recipient requires. Accession and dataset IDs below are
what each recipient needs to find the record.

Before sending anything, decide with the data owner whether the recipient is entitled to receive the patient's identifiers
and results (HIPAA/authorization). Where possible, send the questions via the ordering physician's office or the patient
portal for the relevant order.

---

## A. scRNA vendor: Signios Biosciences (project 2011765) and whoever submitted the samples

Quote: Project ID 2011765; folder `P2011765_09242026` (vendor delivery folder `signios/1012026`); samples `KH022-1` and
`KH022-1-1`; FASTQ QC report dated September 24, 2026. [PATIENT IDENTIFIER PER YOUR AUTHORIZATION, if the submitter used
one.]

The delivery contains FASTQ, Cell Ranger 10.1.0 `multi` outputs and a FASTQ QC report, but no tissue, preparation or sample
metadata. Please send, or confirm from the sample submission records:

1. The sample intake/submission form and any sample sheet for project 2011765, showing for `KH022-1` and `KH022-1-1`: species,
   tissue/organ, sample type, preservation (fresh, frozen, fixed), the customer-supplied specimen ID, collection date, and
   customer-stated treatment status, if any was provided.
2. What was received (tissue, frozen pellet, cell suspension, nuclei suspension, or finished libraries), the date received, who
   prepared the suspension, and the dates of library preparation and of each sequencing run.
3. Whole cells or nuclei? If nuclei: isolation protocol and kit, counting method, concentration, nuclei integrity or debris
   assessment. If cells: dissociation protocol, viability, live/dead method.
4. Library construction for each sample: kit and version (Cell Ranger reports "Single Cell 3' v4 (polyA)"; is this
   GEM-X Universal 3' v4?), chip and channel (GEM well), cells loaded and targeted recovery, cDNA amplification cycles, index
   plate and wells (observed dual indexes: `CTTGCATAAA+AAGCCCTGAT` for KH022-1; `TGATGATTCA+CGACTCCTAC` for KH022-1-1), and
   whether any cell hashing, multiplexing, or sample pooling was used.
5. What do `KH022-1` and `KH022-1-1` denote? Two GEM wells from one suspension, two aliquots, a technical replicate, a repeat
   after a failed first attempt, or two different tissues/timepoints? Are they from the same donor?
6. Sequencing: the BAM read groups list three flowcell-lanes on instrument LH00707 (`25C3KCLT4` lane 6, `257T5WLT4` lane 6,
   `25FC5MLT4` lane 7; run counters 450, 454, 457), and each library's FASTQ is a merge of them named `S1_L001`. Please confirm
   the run IDs and dates, which other libraries shared those lanes, the demultiplexing software and settings (barcode
   mismatches, index-hopping handling), and whether the pre-merge per-lane FASTQ files or demultiplexing reports exist.
7. Cell Ranger configuration: were `include-introns true`, `create-bam true`, reference `refdata-gex-GRCh38-2024-A` and
   `cell-annotation-model auto` your defaults or at the customer's request? Please send the exact `cellranger multi` config
   and command line.
8. **File defect:** `KH022-1-1/per_sample_outs/KH022-1-1/sample_alignments.bam.bai` does not correspond to the delivered
   `sample_alignments.bam` (samtools region queries fail with "Invalid BGZF header"; both files match your `md5sum.txt`).
   `KH022-1`'s pair works. Please regenerate or re-deliver the index and confirm the BAM's integrity.
9. Any pre-sequencing QC on file for each library (Bioanalyzer/TapeStation traces for cDNA and final library, Qubit/qPCR
   yield), and any internal notes on tissue quality.

For the data owner, not the vendor: who submitted KH022 to Signios (the delivery came through a Google Cloud bucket named
`kernis-kh022`), which tissue it was, and the date it was collected. See section F.

---

## B. Personalis (and the "Echo" account/program on the delivery)

Quote: delivery folder `2026-07-14-echo-personalis`; ImmunoID NeXT sample IDs `DNA_E019_S01` (tumor DNA), `DNA_E019_S05_Vial1`
(matched normal DNA), `RNA_E019_S01` (tumor RNA); WGS project `DRF-PSN49561` (tumor and normal); pipeline versions
CORE_DNA_v1.14.1.1 and CAN_RNA_v2.13.2; order path `/ops/symphony/80726/401804/40493683` (from the BAM headers).
[PATIENT IDENTIFIER PER YOUR AUTHORIZATION.]

The manifest says "source-side metadata not provided". Please send:

1. A sample/accession manifest linking E019_S01, E019_S05_Vial1 and DRF-PSN49561 (tumor and normal) to the submitting
   accession(s): specimen type, the submitting institution's specimen ID and block ID, collection date, and date received
   at Personalis. Confirm that E019 and DRF-PSN49561 are the same patient/case in your system.
2. Tumor material: FFPE block, curls, slides, or fresh/frozen tissue; macro-dissection or tumor-content estimate (percent, who
   reviewed which H&E); extraction dates; DNA and RNA yields and QC (DIN, DV200).
3. Normal material: whole blood, saliva or buccal; what "Vial1" means (is there a Vial 2?); collection date and receipt date.
4. Were the ImmunoID exome, the RNA, and the WGS libraries made from the same DNA/RNA extraction and the same tissue block?
5. Sequencing run dates and flowcell IDs for each library. We see: exome tumor and RNA on flowcell `255LYLLT4` (instrument
   LH01020, run 177), exome normal on `25255YLT4` (LH00493, run 388), WGS normal on `23WGWNLT4` (LH00493, run 337), WGS tumor
   on `23YV5FLT4` (LH00696, run 273). Why were WGS tumor and normal run on different instruments/flowcells?
6. The exome BAMs were aligned from FASTQs named `downsampled.*.fq` (bwa @PG line). What downsampling was applied (target
   read count or fraction)? Are the delivered FASTQs the full reads or the downsampled ones? Please also send the
   per-sample QC reports (coverage, on-target, duplication, contamination, tumor-normal concordance, sex check).
7. A third-party report states its 607 somatic variants came from a "Personalis pipeline" on matched tumor/normal WGS. Please
   send the VCF/MAF actually produced (caller, version, reference build, date), plus any copy-number/SV calls and purity/ploidy
   estimates, and the WGS alignments/reference if you produced them. Our delivery has FASTQ only for WGS.
8. Any sample-identity/fingerprinting QC you ran (tumor vs normal vs RNA), and HLA typing, TMB/MSI and neoantigen outputs.
9. Retention: how much extracted DNA/RNA (and tissue) remains, and for how long it is held.
10. Who is the contact for specimen records on the "Echo" account, and what is the program?

---

## C. Altera (Natera)

Quote: Order ID 74338010; client accession 55497045.1-2-FXB; path lab block ID `SUS26-1600 A2`; preliminary report issued
05/12/2026; tumor collected 03/13/2026, blood collected 04/01/2026, block retrieved 04/29/2026, received 05/02/2026.
[PATIENT IDENTIFIER PER YOUR AUTHORIZATION; request via the ordering provider if required.]

1. The final report (with IHC) when issued, and the current PDF of the preliminary report.
2. Specimen record for block `SUS26-1600 A2`: submitting pathology lab, procedure type (core biopsy vs excision), how the 30.0%
   tumor content was estimated (which H&E section, which reviewer), tumor area, and the block's return status and date.
   What does the "1-2" in the client accession encode?
3. Matched normal: confirm the normal was peripheral blood collected 04/01/2026, and provide the normal read counts at the BRCA1
   c.81-1G>A site (chr17:41267797, GRCh37) so absence in the normal is documented.
4. Research-use data, if you can release it: somatic and germline VCF/MAF, BAM/CRAM (or FASTQ) for tumor DNA, normal DNA and
   tumor RNA, copy-number segments with purity/ploidy estimates, and the full variant table with depth and VAF (including the
   VUS table; BRCA1 VAF 27% at depth 2565).
5. Does the assay produce an HRD or genomic-instability score? The preliminary report has none. Please confirm none was
   issued, so that an HRD value attributed to Altera elsewhere can be corrected.
6. Was BRCA2 p.Ser2695Leu (VAF 12%) called somatic, and with what filters? Same question for PIKFYVE, TSC2 and MTOR VUS.
7. Library preparation and sequencing dates (flowcell IDs) for the tumor DNA, normal DNA and tumor RNA.

---

## D. Proteomics lab: OncoOmicsDx

Quote: specimen UID CP0216 (Version 1); requisition # 6543; incoming specimen ID `SP-26-027487-BR-VL3-A1`; collected
13-Mar-2026, received 21-Aug-2026, reported 03-Sep-2026. [PATIENT IDENTIFIER PER YOUR AUTHORIZATION.]

1. The requisition and chain-of-custody record: who shipped the specimen, from which institution, on what date, and what was
   sent (block vs unstained slides; number of sections). The report names "Sutter Health - Alta Bates Summit Medical Center" as
   the pathology institution, while H&E slides bearing the same accession read "Stanford Pathology". Which is correct for the
   physical material you received?
2. What does `BR-VL3-A1` encode (part, vial, block)? Is A1 the block ID?
3. Specimen type (core biopsy vs excision), fixation, percent tumor, dissected area (mm2), number of sections and cells
   collected, and protein input mass; please send the page-4 specimen image and the dissection map at full resolution.
4. Where did "Date collected 13-Mar-2026" come from (requisition vs pathology report)?
5. Is any tissue, section or lysate left? Could additional targets (for example SLFN11 below the current LOQ, or phospho
   targets) be quantified from remaining lysate?
6. Any recorded cold-ischemia/fixation time or block age; raw instrument data availability.

---

## E. Pathology / treating team (Stanford Pathology and Alta Bates Summit pathology, ordering oncologist)

Quote: `SUS26-1600 A2`, `SP-26-027487` (and block A1), `SP-26-022231`; collection date 2026-03-13.

1. Please map the three identifiers `SUS26-1600`, `SP-26-027487`, `SP-26-022231`: for each, the institution, procedure (core
   biopsy, vacuum biopsy, excision, node), site/laterality, collection date, diagnosis, receptor status (ER, PR, HER2,
   Ki-67), and whether it is an outside-consult case re-accessioned at Stanford.
2. Which blocks exist for each accession (A1, A2, ...)? For each release: Altera block A2 (retrieved 04/29/2026), proteomics lab
   (A1; received 08/21/2026), Personalis (which tissue?), and the H&E slides scanned 2026-07-09 ("H&E INITIAL" labels, HistoWiz
   order 40822). Which were returned, and how much tissue remains for IHC (membrane TROP2, SLFN11, PD-L1, HER2-low, Ki-67)?
3. What are slides `SP-26-022231` (many separate fragments) and `SP-26-027487` (one linear core)? Dates, procedures,
   pre- or post-treatment?
4. The primary treatment timeline: regimen, first infusion date (a note records 2026-04-02 but cites a clinical timeline not in
   our files), cycle dates, interruptions, imaging, date of surgery, surgical pathology (pCR or RCB), and any biopsy between
   2026-03-13 and surgery.
5. Was any tissue banked fresh or frozen at the 03-13 biopsy, at any on-treatment biopsy, or at surgery (research biobank)?
   Where did the tissue for the single-cell assay (KH022) come from, who processed it, and on what date?
6. The hereditary germline panel report (lab, date, genes, result including any VUS) and any Guardant360/ctDNA report (date,
   BRCA1 splice-site VAF). We only have second-hand statements that the panel was negative.
7. Blood draw dates and which tubes went where: Altera (04/01/2026), Personalis normal ("Vial1"), any other lab.

---

## F. For the data owner (decisions only you can make)

1. Who ordered/submitted KH022 (bucket `kernis-kh022`, Signios project 2011765), and what is the tissue and collection date?
2. Is the public-read inbox release intentional and consented for: the two SVS slides (embedded label images show the patient's
   name and accession), BAMs/FASTQ with germline genotypes, and the vendor dotfiles (an `.htaccess` listing vendor
   basic-auth usernames)? Also the git-tracked `results/diana_wgs_hrd/early-look-.../VARIANT_REVIEW.tsv`, which names the
   patient's BRCA1 and BRCA2 variants and is on `origin/main`.
3. Authorization path for sending identifiers to each recipient above.
