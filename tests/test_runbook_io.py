from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

    def test_load_json_object_rejects_non_objects_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "receipt.json"
            array = root / "array.json"
            broken_symlink = root / "broken.json"
            receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
            array.write_text('["not", "an", "object"]\n', encoding="utf-8")
            broken_symlink.symlink_to(root / "absent.json")

            self.assertEqual(
                MODULE.load_json_object(receipt, "private publication receipt"),
                {"status": "passed"},
            )
            with self.assertRaisesRegex(ValueError, "not a JSON object"):
                MODULE.load_json_object(array, "private publication receipt")
            with self.assertRaisesRegex(ValueError, "missing or a symlink"):
                MODULE.load_json_object(broken_symlink, "private publication receipt")
            with self.assertRaisesRegex(ValueError, "missing or a symlink"):
                MODULE.load_json_object(root / "missing.json", "missing receipt")

    def test_write_once_is_mode_0600_and_refuses_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runbook.md"

            MODULE.write_once(output, "one\n")

            self.assertEqual(output.read_text(encoding="utf-8"), "one\n")
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.write_once(output, "two\n")

    def test_write_once_removes_partial_output_after_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runbook.md"

            with (
                mock.patch.object(
                    MODULE.os,
                    "fsync",
                    side_effect=OSError("synthetic fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic fsync failure"),
            ):
                MODULE.write_once(output, "partial\n")

            self.assertFalse(output.exists())

    def test_write_once_rejects_symlinked_parent_without_writing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-output"
            real_parent.mkdir()
            symlink_parent = root / "linked-output"
            symlink_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "output parent is a symlink"):
                MODULE.write_once(symlink_parent / "runbook.md", "redirected\n")

            self.assertFalse((real_parent / "runbook.md").exists())

    def test_write_once_rejects_nested_symlinked_parent_without_writing_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-output"
            real_parent.mkdir()
            symlink_parent = root / "linked-output"
            symlink_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "output parent is a symlink"):
                MODULE.write_once(
                    symlink_parent / "missing" / "runbook.md",
                    "redirected\n",
                )

            self.assertFalse((real_parent / "missing" / "runbook.md").exists())
