#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from sequenza.misc import SeqzLogger, SubcommandHelpFormatter
from sequenza.programs.bam2seqz import bam2seqz
from sequenza.programs.gc_wiggle import gc_wiggle
from sequenza.programs.seqz_binning import seqz_binning

PROGRAMS = {
    "bam2seqz": bam2seqz,
    "gc_wiggle": gc_wiggle,
    "seqz_binning": seqz_binning,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("usage: sequenza-utils MODULE [ARGS...]", file=sys.stderr)
        print("modules: " + ", ".join(sorted(PROGRAMS)), file=sys.stderr)
        return 0 if args else 2

    module_name = args.pop(0)
    if module_name not in PROGRAMS:
        print(f"unsupported sequenza-utils module: {module_name}", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(
        prog="sequenza-utils",
        formatter_class=lambda prog: SubcommandHelpFormatter(
            prog,
            max_help_position=20,
            width=75,
        ),
        add_help=True,
    )
    subparsers = parser.add_subparsers(dest="module")
    PROGRAMS[module_name](subparsers, module_name, args, SeqzLogger(level=30))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
