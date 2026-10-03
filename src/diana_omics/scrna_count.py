"""Reference-locked STARsolo 2.7.11b counting. Synthetic smoke does not qualify human cell calling."""
from __future__ import annotations

import gzip
import importlib.metadata
import math
import platform
import re
import shutil
import subprocess
from pathlib import Path

from .scrna_intake import inspect_delivery, inspect_fastq, local_file
from .scrna_io import sha256_file, write_json
from .scrna_private import digest_json

STAR_VERSION = "2.7.11b"
LAYOUTS = {"3prime_v2": (16, 10), "3prime_v3": (16, 12), "3prime_v3.1": (16, 12), "3prime_v3.1_LT": (16, 12)}


def count_plan(contract: dict, delivery: Path, reference: dict, assets: Path) -> dict:
    inspection = inspect_delivery(contract, delivery)
    if len(contract["captures"]) != 1 or contract["captures"][0]["format"] != "fastq":
        raise ValueError("Count each complete FASTQ capture separately; never mix chemistries or captures")
    capture = contract["captures"][0]
    blockers = [reason for reason in inspection["captures"][0]["qc_blockers"] if not reason.startswith("FASTQ count generation")]
    if capture["chemistry"] not in LAYOUTS:
        blockers.append("Implemented counting layouts are 10x 3prime v2/v3/v3.1; other protocols need their own recipe")
    if type(capture.get("expected_cells")) is not int or not 100 <= capture["expected_cells"] <= 100000:
        blockers.append("Declare a bounded expected cell loading for the cell caller")
    if reference.get("schema_version") != 1 or reference.get("star_version") != STAR_VERSION or reference.get("review_status") != "reviewed" or not reference.get("reviewer") or not reference.get("source"):
        blockers.append("Reference/whitelist lock is not reviewed or uses another STAR version")
    if reference.get("reference_id") != capture["reference"] or reference.get("chemistry") != capture["chemistry"]:
        blockers.append("Reference/whitelist lock does not match capture metadata")
    if capture.get("reference_sha256") != digest_json(reference):
        blockers.append("Capture must bind the exact reference-lock digest")
    if reference.get("reference_class") not in {"human_grch38", "synthetic_mechanical"}:
        blockers.append("Unknown reference class")
    if reference.get("reference_class") == "synthetic_mechanical" and contract["evidence_lane"] != "public_control":
        blockers.append("Synthetic references cannot be used on patient data")
    files = reference.get("files", {})
    if set(files) != {"fasta", "gtf", "whitelist"}:
        blockers.append("FASTA, GTF and chemistry-specific whitelist are all required")
    else:
        for item in files.values():
            path = local_file(assets, item["path"])
            if path.stat().st_size != item["size_bytes"] or sha256_file(path) != item["sha256"]:
                raise ValueError("Reference resource checksum/size mismatch")
    return {"schema_version": 1, "backend": "STARsolo", "star_version": STAR_VERSION, "capture_id": capture["capture_id"],
            "reference_lock_sha256": digest_json(reference), "ready_for_reference_locked_counting": not blockers,
            "local_STAR_available": bool(shutil.which("STAR")), "blockers": blockers,
            "cell_calling": "TopCells_synthetic_only" if reference.get("reference_class") == "synthetic_mechanical" else "EmptyDrops_CR",
            "count_generation_qualified_for_patient": False, "clinical_ready": False,
            "compute_request": {"cpu": 8, "memory_mib": 65536, "timeout_seconds": 7200, "gpu": False},
            "required_outputs": ["raw matrix/features/barcodes", "filtered matrix/features/barcodes", "full FASTQ validation", "reference lock", "STAR logs and source hashes"]}


def run_starsolo(contract: dict, delivery: Path, reference: dict, assets: Path, output: Path, threads: int = 8) -> dict:
    plan = count_plan(contract, delivery, reference, assets)
    if not plan["ready_for_reference_locked_counting"]:
        raise ValueError("Count preflight blocked; inspect protected count plan")
    if type(threads) is not int or not 1 <= threads <= 8:
        raise ValueError("Counting is bounded to one through eight threads")
    executable = shutil.which("STAR")
    if not executable or subprocess.run([executable, "--version"], capture_output=True, text=True, check=True).stdout.strip() != STAR_VERSION:
        raise ValueError("Pinned STAR 2.7.11b runtime required")
    output.mkdir(parents=True, exist_ok=False)
    explicit = subprocess.run(["micromamba", "list", "--explicit"], capture_output=True, text=True, check=True)
    (output / "conda-explicit.txt").write_text(explicit.stdout)
    write_json(output / "count_environment.json", {"python": platform.python_version(), "STAR": STAR_VERSION,
               "packages": {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions() if dist.metadata["Name"]},
               "conda_explicit_sha256": sha256_file(output / "conda-explicit.txt")})
    capture = contract["captures"][0]
    pairs = {}
    for item in capture["files"]:
        pairs.setdefault(item["pair_id"], {})[item["role"]] = local_file(delivery, item["path"])
    validations = [inspect_fastq(pair, capture["chemistry"], limit=None) for pair in pairs.values()]
    write_json(output / "full_fastq_validation.json", validations)
    files = {role: local_file(assets, item["path"]) for role, item in reference["files"].items()}
    contigs, genome_size = set(), 0
    with files["fasta"].open() as handle:
        for line in handle:
            if line.startswith(">"):
                name = line[1:].split()[0]
                if name in contigs:
                    raise ValueError("Duplicate FASTA contig")
                contigs.add(name)
            else:
                sequence = line.strip()
                if not re.fullmatch(r"[ACGTNacgtn]*", sequence):
                    raise ValueError("Unsupported FASTA sequence alphabet")
                genome_size += len(sequence)
    if not genome_size or not contigs:
        raise ValueError("Empty reference FASTA")
    exons = 0
    with files["gtf"].open() as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            fields = line.rstrip().split("\t")
            if len(fields) != 9 or fields[0] not in contigs:
                raise ValueError("GTF columns/contigs disagree with FASTA")
            if fields[2] == "exon":
                if not re.search(r'gene_id "[^"]+"', fields[8]) or not re.search(r'gene_name "[^"]+"', fields[8]):
                    raise ValueError("GTF exons must carry stable gene IDs and human-readable symbols")
                exons += 1
    if not exons:
        raise ValueError("GTF contains no usable exons")
    whitelist = output / "whitelist.txt"
    opener = gzip.open if files["whitelist"].suffix == ".gz" else open
    seen = set()
    with opener(files["whitelist"], "rt") as source, whitelist.open("w") as target:
        for line in source:
            barcode = line.strip()
            if not re.fullmatch(r"[ACGT]{16}", barcode) or barcode in seen:
                raise ValueError("Whitelist must have unique 16-base barcodes for this recipe")
            seen.add(barcode)
            target.write(barcode + "\n")
    if not seen:
        raise ValueError("Empty whitelist")
    index = output / "star-index"
    index.mkdir()
    overhang = max(length for value in validations for length in value["read_lengths"]["R2"]) - 1
    index_args = [executable, "--runMode", "genomeGenerate", "--runThreadN", str(threads), "--genomeDir", str(index),
                  "--genomeFastaFiles", str(files["fasta"]), "--sjdbGTFfile", str(files["gtf"]), "--sjdbOverhang", str(overhang),
                  "--genomeSAindexNbases", str(max(1, min(14, int(math.log2(genome_size) / 2 - 1)))), "--genomeSAsparseD", "3",
                  "--outFileNamePrefix", str(output / "index-")]
    cb, umi = LAYOUTS[capture["chemistry"]]
    lanes = sorted(pairs)
    r1 = ",".join(str(pairs[lane]["R1"]) for lane in lanes)
    r2 = ",".join(str(pairs[lane]["R2"]) for lane in lanes)
    if any("," in str(path) or any(c in str(path) for c in "\n\r") for pair in pairs.values() for path in pair.values()):
        raise ValueError("STAR comma-separated lane syntax cannot represent these input filenames")
    compressed = {pairs[lane][role].suffix == ".gz" for lane in lanes for role in ("R1", "R2")}
    if len(compressed) != 1:
        raise ValueError("All counting FASTQs must use the same compression")
    if True in compressed and any(not re.fullmatch(r"[A-Za-z0-9_./-]+", str(path)) for pair in pairs.values() for path in pair.values()):
        # STAR invokes readFilesCommand through a shell, despite our own argv being a list.
        raise ValueError("Compressed FASTQ paths need safe aliases before STAR's shell decompressor")
    count_args = [executable, "--runThreadN", str(threads), "--genomeDir", str(index), "--readFilesIn", r2, r1,
                  "--soloType", "CB_UMI_Simple", "--soloCBstart", "1", "--soloCBlen", str(cb), "--soloUMIstart", "17", "--soloUMIlen", str(umi),
                  "--soloBarcodeReadLength", "0", "--soloCBwhitelist", str(whitelist), "--soloFeatures", "Gene", "--soloStrand", "Forward",
                  "--soloCBmatchWLtype", "1MM_multi_Nbase_pseudocounts", "--soloUMIfiltering", "MultiGeneUMI_CR", "--soloUMIdedup", "1MM_CR",
                  "--outSAMtype", "None", "--outFileNamePrefix", str(output / "count-")]
    # 2.7.11b TopCells indexes the sorted threshold at N (zero based), including ties.
    # The synthetic fixture's Nth-highest threshold is rank N-1. Human data always use EmptyDrops_CR.
    count_args += ["--soloCellFilter", "TopCells", str(capture["expected_cells"] - 1)] if reference["reference_class"] == "synthetic_mechanical" else ["--soloCellFilter", "EmptyDrops_CR", str(capture["expected_cells"])]
    if True in compressed:
        count_args += ["--readFilesCommand", "zcat"]
    write_json(output / "execution_plan.json", {"index_argv": index_args, "count_argv": count_args, "plan": plan})
    write_json(output / "reference_lock.json", reference)
    for name, command in (("index", index_args), ("count", count_args)):
        with (output / (name + ".log")).open("w") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=3600, check=False)
        if result.returncode:
            raise RuntimeError("STAR execution failed; inspect protected index/count logs")
    transformations = []
    for state in ("raw", "filtered"):
        source = output / "count-Solo.out" / "Gene" / state
        target = output / state
        target.mkdir()
        shutil.copyfile(source / "matrix.mtx", target / "matrix.mtx")
        with (source / "features.tsv").open() as handle, (target / "features.tsv").open("w") as dest:
            for line in handle:
                fields = line.rstrip("\r\n").split("\t")
                if len(fields) not in {2, 3}:
                    raise ValueError("Unexpected STARsolo feature format")
                dest.write("\t".join(fields[:2] + ["Gene Expression"]) + "\n")
        with (source / "barcodes.tsv").open() as handle, (target / "barcodes.tsv").open("w") as dest:
            for line in handle:
                value = line.strip()
                if re.fullmatch(r"[ACGT]{16}", value):
                    value += "-1"
                elif not re.fullmatch(r"[ACGT]{16}-1", value):
                    raise ValueError("Unexpected STARsolo barcode format")
                dest.write(value + "\n")
        transformations.append({"state": state, "feature_type": "Explicit Gene Expression from STARsolo Gene output", "barcode_policy": "Single declared capture; append -1 only when STAR omits channel suffix"})
    # Index/redundant raw outputs are reproducible from locked sources, not duplicated as result artifacts.
    shutil.rmtree(index)
    whitelist.unlink()
    shutil.rmtree(output / "count-Solo.out")
    receipt = {"status": "count_generation_provisional", "backend": "STARsolo", "version": STAR_VERSION,
               "reference_lock_sha256": digest_json(reference), "full_records_checked": sum(v["sampled_records"] for v in validations),
               "transformations": transformations, "source_sha256": sha256_file(Path(__file__)),
               "cell_calling_qualified_for_patient": False, "clinical_ready": False}
    write_json(output / "count_receipt.json", receipt)
    return receipt
