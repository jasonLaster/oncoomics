from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from ...paths import ROOT, WIKI_ROOT


def command_version(command: str, args: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            [command] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace")).strip().splitlines()
    return output[0] if output else ""


def check_url(url: str) -> Optional[str]:
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status < 400:
                    return None
                if response.status not in (403, 405):
                    return f"URL returned {response.status}: {url}"
        except urllib.error.HTTPError as error:
            if error.code not in (403, 405):
                return f"URL returned {error.code}: {url}"
        except Exception as error:
            return f"URL check failed for {url}: {error}"
    return None


def main() -> None:
    errors: list[str] = []
    warnings: list[str] = []

    def require_file(path: Path) -> None:
        if not path.exists():
            errors.append(f"Missing required file: {path}")

    def read_project_file(relative_path: str) -> str:
        full_path = ROOT / relative_path
        require_file(full_path)
        return full_path.read_text(encoding="utf-8") if full_path.exists() else ""

    for file in [
        "README.md",
        "docs/status/current-state.md",
        "docs/data/source-map.md",
        "docs/data/wiki-source-summary.md",
        "manifests/validation_atlases.json",
    ]:
        require_file(ROOT / file)
    if os.environ.get("DIANA_OMICS_SKIP_WIKI_CHECKS", "").lower() in {"1", "true", "yes"}:
        warnings.append("Skipping Diana wiki source checks because DIANA_OMICS_SKIP_WIKI_CHECKS=1.")
    else:
        for file in [
            "index.md",
            "findings-overview.md",
            "derived-findings.md",
            "analysis-workflows.md",
            "validation-atlases.md",
            "partner-questions.md",
        ]:
            require_file(WIKI_ROOT / file)

    plan = read_project_file("docs/status/current-state.md")
    for required_section in [
        "Phase 1: Processed Public HRD/RNA Panel",
        "Phase 2: Raw WES and Caller Readiness",
        "Phase 3: Full Public WGS Validation",
        "Phase 3B: Orthogonal Known-Answer Validation",
        "Phase 4: Diana Raw-Data Recompute",
        "Continuous Quality Gates",
    ]:
        if required_section not in plan:
            errors.append(f"current-state.md is missing section: {required_section}.")
    for required in ["Verifier", "HRD", "Python", "Diana", "HG008", "COLO829", "CHORD", "scarHRD"]:
        if required not in plan:
            errors.append(f"current-state.md is missing required term: {required}")

    source_map = read_project_file("docs/data/source-map.md")
    for required_url in [
        "https://www.nist.gov/programs-projects/cancer-genome-bottle",
        "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/analysis/NIST_HG008-T_somatic-smvar_DraftBenchmark_V0.3-20260425/",
        "https://www.ebi.ac.uk/ena/browser/view/PRJEB27698",
        "https://zenodo.org/records/7515830",
        "https://www.natera.com/oncology/altera/",
        "https://investors.personalis.com/news-releases/news-release-details/personalis-launches-next-personaltm-tumor-informed-liquid-biopsy",
    ]:
        if required_url not in source_map:
            errors.append(f"source-map.md is missing required URL: {required_url}")

    manifest = None
    try:
        manifest = json.loads(read_project_file("manifests/validation_atlases.json"))
    except Exception as error:
        errors.append(f"validation_atlases.json is not valid JSON: {error}")

    if manifest:
        if not manifest.get("schema_version"):
            errors.append("Manifest is missing schema_version.")
        sources = manifest.get("sources")
        if not isinstance(sources, list) or len(sources) < 10:
            errors.append("Manifest should include at least 10 researched sources/tools.")
            sources = []
        ids = set()
        has_phase1 = has_tool = has_dataset = False
        for source in sources:
            if source.get("id") in ids:
                errors.append(f"Duplicate manifest source id: {source.get('id')}")
            ids.add(source.get("id"))
            for field in ["id", "title", "kind", "priority", "primary_use", "access", "verifier"]:
                if not source.get(field):
                    errors.append(f"Manifest source {source.get('id') or '(missing id)'} is missing {field}.")
            if not source.get("urls"):
                errors.append(f"Manifest source {source.get('id')} must include at least one URL.")
            if not source.get("expected_artifacts"):
                errors.append(f"Manifest source {source.get('id')} must include expected artifacts.")
            has_phase1 = has_phase1 or "phase-1" in source.get("priority", "")
            has_tool = has_tool or source.get("kind") == "tool"
            has_dataset = has_dataset or source.get("kind") == "dataset"
        if not has_phase1:
            errors.append("Manifest has no phase-1 source.")
        if not has_tool:
            errors.append("Manifest has no tool sources.")
        if not has_dataset:
            errors.append("Manifest has no dataset sources.")

    python_version = command_version("python3", ["--version"])
    if not python_version:
        errors.append("python3 is not available.")
    if not command_version("R", ["--version"]):
        warnings.append("R is not available locally; R-native tools should use a container or later R setup.")

    if manifest and os.environ.get("CHECK_URLS") == "1":
        for source in manifest.get("sources", []):
            for url in source.get("urls", []):
                warning = check_url(url)
                if warning:
                    warnings.append(warning)

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for message in errors:
            print(f"error: {message}", file=sys.stderr)
        raise SystemExit(1)
    print("Plan verification passed.")
    if python_version:
        print(f"Python: {python_version}")


if __name__ == "__main__":
    main()
