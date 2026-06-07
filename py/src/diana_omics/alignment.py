from __future__ import annotations

import re
import subprocess
from typing import Any, Optional

from .paths import path_from_root
from .utils import capture_command, ensure_dir, quote_shell_arg, round_value, run_command


def tool_version(tool: str, lines: int = 8) -> str:
    result = subprocess.run(
        ["bash", "-lc", f"{tool} 2>&1 | head -n {lines}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    return f"{result.stdout}{result.stderr}".strip()


def read_group(row: dict[str, str]) -> str:
    return "\\t".join(
        [
            "@RG",
            f"ID:{row['read_group_id']}",
            f"SM:{row['read_group_sample']}",
            f"LB:{row['read_group_library']}",
            f"PL:{row['read_group_platform']}",
            f"PU:{row['read_group_platform_unit']}",
        ]
    )


def ensure_bwa_index(reference_path: str, results_dir: str, reference_id: str = "reference") -> bool:
    if path_from_root(f"{reference_path}.bwt").exists():
        return False
    run_command(f"bwa index {quote_shell_arg(reference_path)}", f"{results_dir}/logs/{reference_id}.bwa_index.log")
    return True


def parse_header(header: str, row: dict[str, str]) -> dict[str, Any]:
    lines = header.splitlines()
    hd = next((line for line in lines if line.startswith("@HD")), "")
    sort_match = re.search(r"\bSO:([^\t]+)", hd)
    rg_lines = [line for line in lines if line.startswith("@RG")]
    sq_lines = [line for line in lines if line.startswith("@SQ")]
    contigs = [match.group(1) for line in sq_lines for match in [re.search(r"\bSN:([^\t]+)", line)] if match]
    return {
        "sortOrder": sort_match.group(1) if sort_match else "",
        "readGroupPresent": any(f"ID:{row['read_group_id']}" in line and f"SM:{row['read_group_sample']}" in line for line in rg_lines),
        "readGroupCount": len(rg_lines),
        "contigs": contigs,
    }


def count(command: str) -> int:
    output = capture_command(command)
    return int(output or "0")


def parse_idxstats(text: str) -> list[dict[str, Any]]:
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        contig, length, mapped, unmapped = line.split("\t")[:4]
        rows.append({"contig": contig, "length": int(length), "mapped": int(mapped), "unmapped": int(unmapped)})
    return rows


def align_and_validate(row: dict[str, str], results_dir: str, required_contigs: Optional[list[str]] = None) -> dict[str, Any]:
    ensure_dir(path_from_root("/".join(row["output_bam"].split("/")[:-1])))
    threads = int(float(row.get("aligner_threads") or 2))
    command = "set -o pipefail; " + " | ".join(
        [
            f"bwa mem -t {threads} -R {quote_shell_arg(read_group(row))} {quote_shell_arg(row['reference_path'])} {quote_shell_arg(row['fastq_1'])} {quote_shell_arg(row['fastq_2'])}",
            f"samtools sort -@ {threads} -o {quote_shell_arg(row['output_bam'])} -",
        ]
    )
    run_command(command, f"{results_dir}/logs/{row['reference_id']}.{row['run_accession']}.align.log")
    run_command(
        f"samtools index {quote_shell_arg(row['output_bam'])}", f"{results_dir}/logs/{row['reference_id']}.{row['run_accession']}.index.log"
    )
    run_command(
        f"samtools flagstat {quote_shell_arg(row['output_bam'])}",
        f"{results_dir}/logs/{row['reference_id']}.{row['run_accession']}.flagstat.txt",
    )
    run_command(
        f"samtools stats {quote_shell_arg(row['output_bam'])}", f"{results_dir}/logs/{row['reference_id']}.{row['run_accession']}.stats.txt"
    )
    quickcheck = subprocess.run(
        ["samtools", "quickcheck", "-v", str(path_from_root(row["output_bam"]))],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    header_state = parse_header(capture_command(f"samtools view -H {quote_shell_arg(row['output_bam'])}"), row)
    total_alignments = count(f"samtools view -c {quote_shell_arg(row['output_bam'])}")
    mapped_alignments = count(f"samtools view -c -F 4 {quote_shell_arg(row['output_bam'])}")
    properly_paired_alignments = count(f"samtools view -c -f 2 {quote_shell_arg(row['output_bam'])}")
    idxstats_rows = parse_idxstats(capture_command(f"samtools idxstats {quote_shell_arg(row['output_bam'])}"))
    required_contigs = required_contigs or []
    expected_contigs_present = all(contig in header_state["contigs"] for contig in required_contigs)
    bam_exists = path_from_root(row["output_bam"]).exists()
    bai_exists = path_from_root(row["output_bai"]).exists()
    status = (
        quickcheck.returncode == 0
        and bam_exists
        and bai_exists
        and header_state["sortOrder"] == "coordinate"
        and header_state["readGroupPresent"]
        and (not required_contigs or expected_contigs_present)
        and total_alignments > 0
        and mapped_alignments > 0
    )
    return {
        "pair_id": row["pair_id"],
        "reference_id": row["reference_id"],
        "role": row["role"],
        "run_accession": row["run_accession"],
        "sample": row["sample"],
        "reference_sha256": row["reference_sha256"],
        "output_bam": row["output_bam"],
        "output_bai": row["output_bai"],
        "bam_exists": "yes" if bam_exists else "no",
        "bai_exists": "yes" if bai_exists else "no",
        "quickcheck": "passed" if quickcheck.returncode == 0 else "failed",
        "sort_order": header_state["sortOrder"],
        "read_group_present": "yes" if header_state["readGroupPresent"] else "no",
        "read_group_count": header_state["readGroupCount"],
        "reference_contigs": ";".join(header_state["contigs"]),
        "total_alignments": total_alignments,
        "mapped_alignments": mapped_alignments,
        "mapped_fraction": round_value(mapped_alignments / total_alignments if total_alignments else None, 4),
        "properly_paired_alignments": properly_paired_alignments,
        "properly_paired_fraction": round_value(properly_paired_alignments / total_alignments if total_alignments else None, 4),
        "idxstats_rows": idxstats_rows,
        "bam_size_bytes": path_from_root(row["output_bam"]).stat().st_size if bam_exists else "",
        "status": "passed" if status else "failed",
        "caveat": row.get("caveat", ""),
    }
