from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/operations/diana-public-data-download.md"
RUN_ID = "diana-wgs-hrd-20260716T033101Z"


class DianaPublicDataDownloadDocTests(unittest.TestCase):
    def test_rosalind_freeze_examples_use_canonical_packet_output(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertNotIn(
            ".codex-tmp/hrd-reports/deterministic-full/rosalind",
            text,
        )
        self.assertIn(
            'ROSALIND_PACKET="results/rosalind_hrd/diana_wgs/$RUN_ID"',
            text,
        )
        self.assertEqual(text.count('--packet-dir "$ROSALIND_PACKET"'), 2)
        self.assertIn(
            "$RUN_ROOT/terminal.rosalind_diana_wgs.private.json",
            text,
        )

    def test_rosalind_publication_examples_reuse_terminal_receipt_names(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertEqual(
            text.count(
                '--private-publication-receipt '
                '"$RUN_ROOT/terminal.rosalind_diana_wgs.private.json"'
            ),
            2,
        )
        self.assertEqual(
            text.count(
                '--destination-prefix "s3://diana-omics-results-172630973301-us-east-1/'
                'runs/diana-hrd-public/subject01/$RUN_ID/rosalind/"'
            ),
            2,
        )
        self.assertEqual(
            sorted(
                set(
                    re.findall(
                        r'\$RUN_ROOT/terminal\.rosalind_diana_wgs\.public(?:\.dry)?\.json',
                        text,
                    )
                )
            ),
            [
                "$RUN_ROOT/terminal.rosalind_diana_wgs.public.dry.json",
                "$RUN_ROOT/terminal.rosalind_diana_wgs.public.json",
            ],
        )

    def test_pinned_run_id_is_documented_once_for_manual_rosalind_freeze(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertIn(f"RUN_ID={RUN_ID}", text)
        self.assertIn(
            'ROSALIND_PACKET="results/rosalind_hrd/diana_wgs/$RUN_ID"',
            text,
        )


if __name__ == "__main__":
    unittest.main()
