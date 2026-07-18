from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import runbook_io as MODULE  # noqa: E402


class RunbookIoTests(unittest.TestCase):
    def test_shell_join_quotes_paths_and_preserves_raw_tokens(self) -> None:
        self.assertEqual(
            MODULE.shell_join(
                [
                    "python3",
                    Path("/repo/scripts with spaces/run.py"),
                    "--output",
                    MODULE.Raw('"$RUNBOOK"'),
                ]
            ),
            "python3 '/repo/scripts with spaces/run.py' --output \"$RUNBOOK\"",
        )

    def test_block_helpers_render_bash_fences(self) -> None:
        self.assertEqual(
            MODULE.block(["python3", Path("/repo/scripts with spaces/run.py")]),
            "```bash\npython3 '/repo/scripts with spaces/run.py'\n```\n",
        )
        self.assertEqual(
            MODULE.bash_block(["NEXT=1", 'echo "$NEXT"']),
            "```bash\nNEXT=1\necho \"$NEXT\"\n```\n",
        )

    def test_timestamped_runbook_assignment_quotes_the_prefix_only(self) -> None:
        self.assertEqual(
            MODULE.timestamped_runbook_assignment(
                "NEXT_RUNBOOK",
                Path("/repo/.codex-tmp/hrd reports/ai-review"),
                "terminal.post-reports-runbook",
            ),
            "NEXT_RUNBOOK='/repo/.codex-tmp/hrd reports/ai-review/"
            "terminal.post-reports-runbook.'$(date -u +%Y%m%dT%H%M%SZ).md",
        )
