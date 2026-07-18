from __future__ import annotations

from collections.abc import Iterable

STANDARD_AUTOSOMES = tuple(f"chr{index}" for index in range(1, 23))
STANDARD_AUTOSOME_ORDER = {
    contig: index
    for index, contig in enumerate(STANDARD_AUTOSOMES, start=1)
}


def require_no_standard_autosome_gaps(
    contigs: Iterable[str],
    label: str,
    error_type: type[Exception],
) -> None:
    observed = {
        contig
        for contig in contigs
        if contig in STANDARD_AUTOSOME_ORDER
    }
    if not observed:
        return

    highest = max(STANDARD_AUTOSOME_ORDER[contig] for contig in observed)
    for expected in STANDARD_AUTOSOMES[:highest]:
        if expected not in observed:
            raise error_type(f"{label} is missing standard autosome {expected}")
