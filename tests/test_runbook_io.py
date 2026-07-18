from __future__ import annotations

import sys
import tempfile
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

    def test_required_and_create_only_path_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            regular = root / "regular.txt"
            directory = root / "directory"
            missing = root / "missing.txt"
            broken_symlink = root / "broken"
            regular.write_text("ok\n", encoding="utf-8")
            directory.mkdir()
            broken_symlink.symlink_to(root / "absent")

            paths = (regular, directory, missing, broken_symlink)

            self.assertEqual(
                MODULE.missing_required_files(paths),
                (directory, missing, broken_symlink),
            )
            self.assertEqual(
                MODULE.preexisting_create_only_paths(paths),
                (regular, directory, broken_symlink),
            )
