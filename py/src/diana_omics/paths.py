from __future__ import annotations

from pathlib import Path
from typing import Union

ROOT = Path(__file__).resolve().parents[3]
WIKI_ROOT = Path("/Users/jasonlaster/src/projects/diana-tnbc/obsidian/wiki/omics")


def path_from_root(relative_path: Union[str, Path]) -> Path:
    return ROOT / relative_path
