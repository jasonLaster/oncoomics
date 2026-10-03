from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ...paths import path_from_root
from ...target_discovery import (
    DNA_EVIDENCE_COLUMNS,
    TARGET_DISCOVERY_RESULTS,
    read_csv_rows,
    selected_dna_evidence_path,
)
from ...utils import ensure_dir, write_csv, write_json

DEFAULT_LOCI = "manifests/target_gene_loci_hs37d5.csv"
MIN_READS_DEFAULT = 10
TIMEOUT_SECONDS_DEFAULT = 20
WORKERS_DEFAULT = 4


@dataclass(frozen=True)
class CountResult:
    reads: int
    status: str
    detail: str = ""


def main() -> None:
    tumor_bam = _required_env("TARGET_DISCOVERY_TUMOR_BAM")
    tumor_bai = _required_env("TARGET_DISCOVERY_TUMOR_BAI")
    normal_bam = _required_env("TARGET_DISCOVERY_NORMAL_BAM")
    normal_bai = _required_env("TARGET_DISCOVERY_NORMAL_BAI")
    loci_path = os.environ.get("TARGET_DISCOVERY_LOCI", DEFAULT_LOCI)
    output_path = selected_dna_evidence_path()
    min_reads = int(os.environ.get("TARGET_DISCOVERY_MIN_READS", str(MIN_READS_DEFAULT)))
    timeout_seconds = int(os.environ.get("TARGET_DISCOVERY_SAMTOOLS_TIMEOUT_SECONDS", str(TIMEOUT_SECONDS_DEFAULT)))
    workers = int(os.environ.get("TARGET_DISCOVERY_SAMTOOLS_WORKERS", str(WORKERS_DEFAULT)))

    loci = read_csv_rows(loci_path)
    count_inputs = []
    for index, locus in enumerate(loci):
        region = f"{locus['contig']}:{locus['start']}-{locus['end']}"
        count_inputs.append((index, "tumor", tumor_bam, tumor_bai, region, timeout_seconds))
        count_inputs.append((index, "normal", normal_bam, normal_bai, region, timeout_seconds))

    counts: dict[tuple[int, str], CountResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for index, role, result in executor.map(_count_star, count_inputs):
            counts[(index, role)] = result

    rows = []
    for index, locus in enumerate(loci):
        tumor_result = counts[(index, "tumor")]
        normal_result = counts[(index, "normal")]
        callable_status = (
            "callable"
            if tumor_result.status == "passed"
            and normal_result.status == "passed"
            and tumor_result.reads >= min_reads
            and normal_result.reads >= min_reads
            else "missing"
        )
        detail = [
            f"hs37d5 locus {locus['contig']}:{locus['start']}-{locus['end']}",
            f"tumor_reads={tumor_result.reads}",
            f"normal_reads={normal_result.reads}",
        ]
        if tumor_result.detail:
            detail.append(f"tumor={tumor_result.detail}")
        if normal_result.detail:
            detail.append(f"normal={normal_result.detail}")
        detail.append(
            "indexed BAM range-read callability only; variant, CNV, HLA-loss, RNA, and protein evidence remain no_call."
        )
        rows.append(
            {
                "target_id": locus["target_id"],
                "gene_symbol": locus["gene_symbol"],
                "callability_status": callable_status,
                "copy_number_status": "no_call",
                "variant_effect": "no_call",
                "hla_loss_status": "no_call",
                "evidence_detail": "; ".join(detail),
            }
        )

    ensure_dir(path_from_root(TARGET_DISCOVERY_RESULTS))
    write_csv(path_from_root(output_path), rows, DNA_EVIDENCE_COLUMNS)
    write_json(
        path_from_root(f"{TARGET_DISCOVERY_RESULTS}/target_dna_evidence_manifest.json"),
        {
            "status": "partial_evidence",
            "output": output_path,
            "loci": loci_path,
            "tumorBam": tumor_bam,
            "normalBam": normal_bam,
            "minimumReads": min_reads,
            "samtoolsTimeoutSeconds": timeout_seconds,
            "samtoolsWorkers": workers,
            "rowCount": len(rows),
            "callableCount": sum(1 for row in rows if row["callability_status"] == "callable"),
            "timeoutCount": sum(
                1
                for result in counts.values()
                if result.status == "timeout"
            ),
            "boundary": "Indexed BAM range counts are a locus-callability screen; they do not call SNVs, CNVs, HLA loss, RNA expression, surface protein abundance, or drug sensitivity.",
        },
    )
    print(f"Target DNA evidence written: {output_path}")


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} must be set")
    return value


def samtools_count(bam: str, bai: str, region: str) -> int:
    result = run_samtools_count(bam, bai, region, timeout_seconds=TIMEOUT_SECONDS_DEFAULT)
    if result.status != "passed":
        raise RuntimeError(result.detail)
    return result.reads


def _count_star(args: tuple[int, str, str, str, str, int]) -> tuple[int, str, CountResult]:
    index, role, bam, bai, region, timeout_seconds = args
    return index, role, run_samtools_count(bam, bai, region, timeout_seconds=timeout_seconds)


def run_samtools_count(bam: str, bai: str, region: str, *, timeout_seconds: int) -> CountResult:
    try:
        result = subprocess.run(
            ["samtools", "view", "-c", "-X", bam, bai, region],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return CountResult(0, "timeout", f"samtools view timed out after {timeout_seconds}s")
    except subprocess.CalledProcessError as error:
        return CountResult(0, "failed", f"samtools view failed: {error.stderr.strip()}")
    return CountResult(int(result.stdout.strip()), "passed")


if __name__ == "__main__":
    main()
