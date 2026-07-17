# Fast-Rerun Performance and Cost Projection

Status: planning projection based on the live `diana-wgs-hrd-20260716T033101Z` run observed through 2026-07-16 19:25 UTC and AWS public prices retrieved on 2026-07-16.

## Executive summary

**Verdict: promising with gaps.** The selected `us-east-2` P5en/Parabricks plan is the fastest route. Reusing the completed tumor and normal BAMs, it targets **1-2 hours and $70-$135** for the immediate evidence rerun: roughly **10-24x faster** than today's projected 20-24-hour run, but more expensive per run. The archived CPU scatter plan targets **1.5-3 hours and $10-$22** from the same BAM checkpoint: roughly **7-16x faster** and about **60-75% cheaper** than today's run, but with a lower acceleration ceiling and more orchestration.

The speed ranges are engineering projections, not measured P5en or isolated-CPU benchmarks. The immediate rerun gains time from both a faster caller topology and from resuming at the validated BAM checkpoint instead of repeating alignment and BAM gathering.

| Plan | Starting point | Projected wall time | Improvement versus today | Projected run cost | Confidence |
| --- | --- | ---: | ---: | ---: | --- |
| Today's live CPU topology | FASTQs | 20-24 hours | Baseline | $40-$55 | Medium; 14.2 hours observed and still running |
| Archived CPU scatter, immediate rerun | Existing BAMs | 1.5-3 hours | 7-16x faster | $10-$22 | Low-medium until isolated-shard benchmark |
| **Selected GPU/Parabricks, immediate rerun** | Existing BAMs | **1-2 hours** | **10-24x faster** | **$70-$135** | Low-medium until full-caller benchmark |
| Archived CPU scatter, future fresh run | FASTQs | 8-10 hours | 2-3x faster | $30-$50 | Low-medium |
| Selected GPU/Parabricks, future fresh run | FASTQs | 2-3 hours | 7-12x faster | $135-$235 | Low until `fq2bam` and caller benchmarks pass |

The operational decision remains: implement the GPU plan assuming quota lands, and retain the CPU plan only as a historical artifact. The GPU premium buys the shortest turnaround; it is not expected to make this single On-Demand rerun cheaper.

For the live July WGS run, do not race the running CPU evidence job with an ad
hoc P5en recomputation. The quota request is the only immediate GPU-side action;
new GPU compute should wait for approved quota, an isolated `p5en.48xlarge`
Batch queue, and a bounded Parabricks smoke gate.

## Today's measured baseline

The live run has already established a 14.2-hour lower bound and was still running at the observation point:

| Critical-path stage | Observed wall time |
| --- | ---: |
| Eight parallel lane alignments | 4.37 hours |
| Gather and mark duplicates | 2.01 hours |
| Full evidence v2 at observation | More than 7.79 hours and still running |
| **Observed critical-path floor** | **More than 14.17 hours** |

The evidence v2 job remained inside its CPU Mutect2 scatter. At approximately 450 minutes of caller progress, `chr1` had reached only about 124.2 million bases and remained the clearest straggler. Allowing for completion of the long-contig caller, gathering, filtering, independent evidence branches, uploads, and verification produces the **20-24-hour planning range**. The lower bound is measured; the completion range is a medium-confidence extrapolation.

The current **$40-$55** run-cost estimate includes:

- eight alignment jobs packed across four observed Batch instances;
- gather/mark-duplicates, the failed evidence-v1 attempt, the still-running evidence-v2 attempt, and the targeted early-look job;
- current Spot and On-Demand Graviton prices appropriate to the observed allocations;
- temporary gp3 storage, including the current 2 TiB, 16,000-IOPS, 1,000-MB/s caller volume.

AWS Cost Explorer and the account-level billing API were unavailable to this session, and retired ECS records no longer exposed every alignment host's exact instance type. This is therefore an infrastructure model, not an invoice. It excludes taxes, support, NAT, CloudWatch ingestion, and long-term retention.

## CPU projection: cheapest fast rerun

For cost modeling, the archived 16-shard CPU design is instantiated with one `m7g.2xlarge` On-Demand instance and one independent 250 GiB gp3 volume per balanced Mutect2 interval. This prevents the same-host BAM and block-device contention observed today.

| CPU cost component | Calculation | Projection |
| --- | --- | ---: |
| Caller compute | 16 instances x $0.3264/hour x 1.5-3 hours | $7.83-$15.67 |
| Per-shard gp3 scratch | 16 volumes x about $0.079/hour x 1.5-3 hours | $1.89-$3.78 |
| Coordinator, gather, filtering, and QC | Small Graviton jobs | $1-$2 |
| **Immediate evidence rerun** | Rounded planning range | **$10-$22** |

This path should be cheaper than today because it removes failed monolithic retries, avoids expensive oversized shared storage, and pays for modest instances only while their independent shards run. For a future run beginning from FASTQs, keeping today's approximately 6.4-hour alignment-and-gather path ahead of the isolated caller yields roughly **8-10 hours and $30-$50**.

The primary uncertainty is long-contig shard balance. One fixed-interval benchmark must show that independent disks actually remove the bottleneck before treating the 1.5-3-hour range as a commitment.

## GPU projection: fastest rerun

The selected design uses one On-Demand `p5en.48xlarge` in `us-east-2` for Parabricks `mutectcaller`. The instance provides 192 vCPUs, 2 TiB RAM, eight NVIDIA H200 GPUs, and eight 3.8 TB local NVMe devices. The public On-Demand price retrieved for `us-east-2` was **$63.296 per instance-hour**.

| GPU cost component | Calculation | Projection |
| --- | --- | ---: |
| P5en caller | 1-2 instance-hours x $63.296/hour | $63.30-$126.59 |
| CPU QC, filtering, evidence join, and verification | Small Graviton jobs | $2-$5 |
| Initial regional replication | About 130 GB x $0.02/GB | About $2.60 once |
| **Immediate evidence rerun** | Rounded cold/warm range | **$70-$135** |

The **1-2-hour** target includes staging from the regional cache, Parabricks calling on local NVMe, downstream filtering/evidence branches, and publication. It assumes the P5en quota and capacity land and that the bounded smoke test confirms all eight GPUs are usable. NVIDIA publishes large CPU-to-GPU acceleration examples for Parabricks, but no directly comparable H200 tumor-normal MutectCaller benchmark was found; the projection is therefore deliberately broader than a vendor benchmark claim.

For a later FASTQ-origin run, two P5en `fq2bam` jobs would process tumor and normal concurrently, followed by one P5en caller job. A planning allowance of 2.0-3.5 total P5en instance-hours plus CPU branches gives **2-3 hours and $135-$235**. This future mode is not part of the immediate rerun and cannot be promoted until BAM and downstream known-answer non-inferiority gates pass.

## Storage projection

Storage is small relative to P5en compute and should be used to remove transfer and recomputation from the critical path.

| Storage item | Size assumption | Projection |
| --- | ---: | ---: |
| Current observed work plus early-look prefixes | About 325.5 GiB | About $7.50/month |
| Proposed `us-east-2` immutable BAM/reference/resource cache | About 130 GB | About $3/month |
| One-time source-to-cache transfer | About 130 GB | About $2.60 |

Results should point to the immutable BAMs by version and checksum instead of copying the approximately 100 GiB BAM pair into every result prefix. Temporary P5en NVMe is included with the instance and should hold scratch data only; durable checkpoints must be uploaded before job exit.

## What changes performance

```text
today: FASTQs -> CPU lane alignment -> serial gather -> ten Mutect2 JVMs sharing one host/disk -> monolithic evidence package
 CPU: validated BAMs ----------------> sixteen isolated Mutect2 hosts/disks -------> resumable evidence branches
 GPU: validated BAMs ----------------> one 8x H200 Parabricks caller -------------> resumable evidence branches
```

The major improvements are architectural, not just larger machines:

1. Resume from immutable validated BAMs for this rerun.
2. Remove same-host caller contention: isolated disks on CPU or one GPU-native caller.
3. Split caller, contamination, CNV, SV, filtering, and packaging into durable Nextflow checkpoints.
4. Keep data and resources in the execution region and stage onto local scratch.
5. Store large inputs once and publish small results plus provenance pointers.

## Projection gates and claim boundaries

The smallest useful validation is the same bounded genomic interval on both candidate topologies:

- one isolated CPU shard with its own staged BAMs and gp3 volume;
- one eight-H200 Parabricks run with the same BAMs, reference, resources, and interval;
- queue, staging, caller, upload, total wall time, resource utilization, normalized concordance, and actual instance-hours recorded separately.

Promotion then requires full BAM-to-evidence benchmarking and known-answer non-inferiority. Until those gates pass:

- none of the projected times is an SLA or guarantee;
- GPU speed does not establish caller equivalence;
- a completed run proves mechanics and research evidence generation, not clinical validity;
- costs can move with AWS pricing, capacity, retries, and actual staging volume;
- coarse CNV and mechanical SV evidence must not be relabeled as validated HRD, LOH, or production SV calls.

## Source and calculation notes

- AWS P5en specifications: [Accelerated computing instance types](https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html).
- AWS P5en On-Demand availability: [Amazon EC2 P5en instances announcement](https://aws.amazon.com/blogs/aws/new-amazon-ec2-p5en-instances-with-nvidia-h200-tensor-core-gpus-and-efav3-networking/).
- Exact EC2 prices were retrieved from the AWS public regional Price List files for [US East (Ohio)](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-2/index.json) and [US East (N. Virginia)](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.json) on 2026-07-16. Spot inputs came from the live AWS `describe-spot-price-history` API on the same date.
- EBS calculations use [AWS EBS pricing](https://aws.amazon.com/ebs/pricing/); S3 storage and transfer assumptions use [AWS S3 pricing](https://aws.amazon.com/s3/pricing/).
- Parabricks capability and benchmark context: [Parabricks overview](https://docs.nvidia.com/clara/parabricks/latest/overview.html), [`fq2bam` documentation](https://docs.nvidia.com/clara/parabricks/tool-reference/tools/fq-2-bam-bwa-mem-gatk), and [`mutectcaller` documentation](https://docs.nvidia.com/clara/parabricks/latest/documentation/tooldocs/man_mutectcaller.html).
