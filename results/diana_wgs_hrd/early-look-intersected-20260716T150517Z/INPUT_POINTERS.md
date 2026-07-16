# Public input pointers

The exact inputs used by the successful early-look job are anonymously
available under the same public run root as the result artifacts.

## Public run root

```text
s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/
```

## Validated matched pair

```text
inputs/validated_bams/tumor.markdup.bam
inputs/validated_bams/tumor.markdup.bam.bai
inputs/validated_bams/normal.markdup.bam
inputs/validated_bams/normal.markdup.bam.bai
```

| Object | Bytes | Run-evidence ETag |
| --- | ---: | --- |
| `tumor.markdup.bam` | 51,081,679,103 | `bb415f6914d254906d5c200cd3e233ed-6090` |
| `normal.markdup.bam` | 55,978,126,326 | `8f1dc3b07e7e98c85177fafd5e17c1eb-6674` |
| `tumor.markdup.bam.bai` | 9,093,656 | `93fbace6dc11de207c69d4e1f04fb387-2` |
| `normal.markdup.bam.bai` | 8,974,736 | `2cf1f5bafa7af24be82513221d48fe17-2` |

The same prefix includes headers, flagstat, duplicate metrics, and
`gather.json`.

## Caller resources

```text
inputs/caller_resources/
```

This contains GATK 4.6.2.0, the hg38 1000 Genomes PoN, af-only gnomAD,
common-biallelic sites and indexes, and the worker versions stored with the run.

## Reference

```text
inputs/reference/
```

This contains the UCSC hg38 analysis-set FASTA, FAI, dictionary, compressed
upstream FASTA, BWA indexes, and BRCA smoke BED.

## Anonymous staging

```bash
PUBLIC_RUN='s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z'

aws s3 sync "$PUBLIC_RUN/inputs/validated_bams/" ./validated_bams/ \
  --no-sign-request --only-show-errors

samtools quickcheck -v \
  ./validated_bams/tumor.markdup.bam \
  ./validated_bams/normal.markdup.bam
```

Individual objects can also be downloaded by replacing the `s3://` bucket
prefix with:

```text
https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/
```
