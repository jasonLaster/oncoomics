from __future__ import annotations

import os
from pathlib import Path
from typing import Union

ROOT = Path(os.environ["DIANA_OMICS_ROOT"]).resolve() if os.environ.get("DIANA_OMICS_ROOT") else Path(__file__).resolve().parents[3]
WIKI_ROOT = Path(os.environ.get("DIANA_OMICS_WIKI_ROOT", "/Users/jasonlaster/src/projects/diana-tnbc/obsidian/wiki/omics"))


def path_from_root(relative_path: Union[str, Path]) -> Path:
    return ROOT / relative_path
