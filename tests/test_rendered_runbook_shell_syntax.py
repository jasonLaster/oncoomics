from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import render_ai_synthesis_runbook as AI_SYNTHESIS  # noqa: E402
import render_post_success_runbook as POST_SUCCESS  # noqa: E402
import render_reviewed_publication_runbook as REVIEWED_PUBLICATION  # noqa: E402
import render_source_report_freeze_runbook as SOURCE_REPORT_FREEZE  # noqa: E402


BASH_FENCE = re.compile(r"```bash\n(.*?)\n```", re.DOTALL)


def ai_receipt_summaries() -> tuple[dict[str, str | int], ...]:
    return tuple(
        {
            "method_id": method_id,
            "receipt": f"{method_id}.private.json",
            "destination_prefix": f"s3://private/{method_id}/",
            "report_manifest_version_id": f"version-{index}",
            "report_manifest_sha256": f"{index:064x}",
            "object_count": 5,
        }
        for index, method_id in enumerate(AI_SYNTHESIS.REQUIRED_METHOD_IDS, 1)
    )


def reviewed_publication_receipt_summaries(
    receipt_paths: list[Path],
) -> tuple[dict[str, str | int], ...]:
    return tuple(
        {
            "method_id": method_id,
            "receipt": str(receipt_path),
            "receipt_sha256": f"{index:064x}",
            "destination_prefix": REVIEWED_PUBLICATION.destination_prefix(
                method_id
            ),
            "object_count": 3,
        }
        for index, (method_id, receipt_path) in enumerate(
            zip(REVIEWED_PUBLICATION.REPORT_METHOD_IDS, receipt_paths, strict=True),
            1,
        )
    )


def rendered_runbooks() -> dict[str, str]:
    root = Path("/repo")
    reviewed_public_receipts = [
        Path(f"/receipts/{method_id}.private.json")
        for method_id in REVIEWED_PUBLICATION.REPORT_METHOD_IDS
    ]
    return {
        "post-success": POST_SUCCESS.render(
            root,
            "12345678-1234-1234-1234-123456789abc",
        ),
        "source-report-freeze": SOURCE_REPORT_FREEZE.render(root, "unit"),
        "ai-synthesis": AI_SYNTHESIS.render(
            root,
            "unit",
            receipt_summaries=ai_receipt_summaries(),
        ),
        "reviewed-publication": REVIEWED_PUBLICATION.render(
            root,
            reviewed_public_receipts,
            "unit",
            receipt_summaries=reviewed_publication_receipt_summaries(
                reviewed_public_receipts,
            ),
        ),
    }


class RenderedRunbookShellSyntaxTests(unittest.TestCase):
    def test_rendered_bash_fences_parse(self) -> None:
        for label, text in rendered_runbooks().items():
            with self.subTest(runbook=label):
                blocks = BASH_FENCE.findall(text)
                self.assertGreater(len(blocks), 0)
                for index, source in enumerate(blocks, 1):
                    with self.subTest(runbook=label, block=index):
                        result = subprocess.run(
                            ["bash", "-n"],
                            input=source,
                            text=True,
                            capture_output=True,
                            check=False,
                        )
                        self.assertEqual(
                            result.returncode,
                            0,
                            f"{label} bash fence {index} failed syntax check\n"
                            f"stderr:\n{result.stderr}\n"
                            f"source:\n{source}",
                        )


if __name__ == "__main__":
    unittest.main()
