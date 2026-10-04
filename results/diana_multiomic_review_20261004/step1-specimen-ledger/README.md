# Step 1 specimen ledger: files, commands, bytes transferred

Private (git-ignored). Read-only on S3; nothing uploaded, committed, sent, or published. No Gmail or external contact.

## Files

| File | What |
| --- | --- |
| `ledger.csv` | 12 rows (Altera, ImmunoID tumor exome / normal exome / tumor RNA, WGS tumor / normal, proteomics, H&E A / B, KH022-1, KH022-1-1, EVEE report); requested columns plus `field_status`, `other_dates_hints`, `open_questions`; every cell's evidence is in `evidence_for_each_field` |
| `ledger.md` | established / inferred / unknown, timeline, relationship map, discrepancies, checks still needed |
| `vendor_questions.md` | drafted, copy-ready questions per recipient (nothing sent) |
| `he_labels/` | embedded label and macro images from both SVS files, plus contrast-stretched label crops (the labels show the patient's name) |
| `evidence/` | raw extractions: cleaned BAM headers, read-count JSONs, insert-size JSON, FASTQ read-name table, KH022 source-file times, scripts |

## Commands used (representative; presigned URLs expire in 1 h and are not stored)

Region note: the AWS CLI default region is not us-east-1 here, so every call used `--region us-east-1` (a plain `presign`
produced a us-west-1 URL that failed).

```sh
# listings and small files
aws s3 ls --region us-east-1 s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/ ...
aws s3 cp --region us-east-1 <manifest.csv | checksums.sha256 | checksum.txt | README.md | md5sum.txt | qc/2011765_qc.pdf | qc_report.html | publication_receipt.json> <scratch>
aws s3 cp --region us-east-1 s3://diana-omics-private-results-172630973301-us-east-1/private/scrna/deliveries/kernis-kh022-20261003T015100Z/arrival_receipt.json <scratch>
aws s3api head-object --region us-east-1 --bucket <b> --key <k>

# BAM headers (header only), then drop samtools' own @PG line, which embeds the presigned URL
u=$(aws s3 presign --region us-east-1 s3://<bucket>/<key>.bam --expires-in 3600)
samtools view --no-PG -H "$u" > <name>.header.txt

# first read names (first 1 MiB of each FASTQ; 7 offsets x 2 libraries for KH022 R1)
aws s3api get-object --region us-east-1 --bucket <b> --key <fastq> --range bytes=0-1048575 out.gz ; gzip -dc out.gz | head
python3 evidence/scripts/sample_fq_offsets.py          # gzip-member resync at 12/25/40/55/70/85/97% offsets

# vendor documents
pdftotext -layout 2011765_qc.pdf - ; pdfinfo ; python3 (embedded `const data` JSON in qc_report.html)

# SVS metadata (HTTP range reads through tifffile; label+macro decoded from the file's own pages)
uv run --no-project --python 3.11 --with tifffile --with imagecodecs --with pillow --with numpy python evidence/scripts/he_probe.py

# variant sites (single position, then BRCA1 gene window), both with -X BAM-url BAI-url
samtools mpileup -Q 0 -q 0 -B -d 100000 --ff 0 -r <region> -X "$bam_url" "$bai_url"
samtools view -f 0x42 -F 0x904 -q 20 -X "$bam_url" "$bai_url" <region> | awk '$9>0 && $9<1000{print $9}'   # insert sizes
python3 evidence/scripts/conc.py                          # exome-vs-WGS germline concordance with hg19->hg38 offset
uv run --no-project --python 3.11 --with pysam python evidence/scripts/brca2_probe.py   # BRCA2 hs37d5 position via 40 bp read context
uv run --no-project --python 3.11 --with pysam python evidence/scripts/kh_variant_counts.py   # KH022-1 reads at both sites
python3 evidence/scripts/bam_locate.py KH022-1-1          # shows the BAI/BAM mismatch
python3 evidence/scripts/bisect_bam.py KH022-1-1 31295983934 chr17 43115780 150   # byte-offset bisection around the site
uv run --no-project --python 3.11 --with pysam python evidence/scripts/slice_counts.py KH022-1-1 chr17 43115780
python3 evidence/scripts/build_ledger.py                  # writes ledger.csv
```

Sites used: BRCA1 c.81-1G>A at hs37d5 17:41267797 = hg38 chr17:43115780 (offset 1,847,983); BRCA2 c.8084C>T at hs37d5
13:32937423 = hg38 chr13:32363286 (offset 574,137). Gene windows: hs37d5 17:41196312-41277500, hg38
chr17:43044295-43125483. BAMs: Personalis exome/RNA from the raw inbox; WGS from the private bucket
`runs/subject01/diana-wgs-hrd-20260716T033101Z/deterministic/inputs/{tumor,normal}.markdup.bam`; KH022 from the inbox copy.

## Bytes transferred (estimate, not metered; total about 0.6 GB, well under the 3 GB budget)

| Item | Approx. bytes |
| --- | ---: |
| Personalis small files (manifest, checksums, checksum.txt) | 0.02 MB |
| BAM headers (8 files; RNA header alone is 0.58 MB) | up to 8 MB |
| FASTQ first MiB: 11 Personalis files + 8 KH022 files | 20 MB |
| FASTQ offset sampling in KH022 R1 files (14 x 1 MiB) | 14.7 MB |
| KH022 small objects (README, QC PDF, md5s, dotfiles, CSVs, 2 qc_report.html, manifest, receipts) | 20 MB |
| SVS range reads (measured: 9,109,581 + 7,029,645) | 16.1 MB |
| BAM index downloads (samtools/pysam re-download the whole .bai on every call; about 35 calls; largest share) | about 380 MB |
| BAM region data (BRCA1 window x2 passes in four BAMs, BRCA2 windows, KH022 single sites) | about 100 MB |
| KH022-1-1 bisection and locate probes (measured 22.5 + 4.2 MB, plus 12 MB) | about 39 MB |
| Whole BAM/FASTQ downloads | 0 |

Local scratch (not deliverable): `/private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/4fbd936b-233c-45a5-9c20-5ff0fee4d763/scratchpad/step1/`
(the mpileup text and FASTQ fragments live there).

## Caveats

- Single-site counts are unfiltered (MAPQ 0, base quality 0, duplicates kept) unless stated, and are intended for
  presence/absence of a rare allele, not for VAF estimation.
- `evidence/bam_headers/` files were cleaned of samtools' own @PG line (it embedded a time-limited presigned URL).
- The KH022-1-1 slice BAM and the mpileup text were not copied into this folder.
