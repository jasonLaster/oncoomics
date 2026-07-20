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
            symlinked_regular = root / "symlinked-regular.txt"
            directory = root / "directory"
            missing = root / "missing.txt"
            broken_symlink = root / "broken"
            regular.write_text("ok\n", encoding="utf-8")
            symlinked_regular.symlink_to(regular)
            directory.mkdir()
            broken_symlink.symlink_to(root / "absent")

            paths = (regular, symlinked_regular, directory, missing, broken_symlink)

            self.assertEqual(
                MODULE.missing_required_files(paths),
                (symlinked_regular, directory, missing, broken_symlink),
            )
            self.assertEqual(
                MODULE.preexisting_create_only_paths(paths),
                (regular, symlinked_regular, directory, broken_symlink),
            )

    def test_required_and_create_only_filters_reject_symlinked_parents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-inputs"
            real_input = real_parent / "checked-in.py"
            linked_parent = root / "linked-inputs"
            real_parent.mkdir()
            real_input.write_text("print('ok')\n", encoding="utf-8")
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            required = linked_parent / "checked-in.py"
            missing_output = linked_parent / "missing" / "receipt.json"

            self.assertTrue(required.is_file())
            self.assertEqual(MODULE.missing_required_files([required]), (required,))
            self.assertEqual(
                MODULE.preexisting_create_only_paths([missing_output]),
                (missing_output,),
            )

    def test_load_json_object_rejects_non_objects_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "receipt.json"
            array = root / "array.json"
            duplicate = root / "duplicate.json"
            invalid = root / "invalid.json"
            broken_symlink = root / "broken.json"
            receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
            array.write_text('["not", "an", "object"]\n', encoding="utf-8")
            duplicate.write_text(
                '{"status":"passed","status":"passed"}\n',
                encoding="utf-8",
            )
            invalid.write_text('{"status":\n', encoding="utf-8")
            broken_symlink.symlink_to(root / "absent.json")

            self.assertEqual(
                MODULE.load_json_object(receipt, "private publication receipt"),
                {"status": "passed"},
            )
            with self.assertRaisesRegex(ValueError, "not a JSON object"):
                MODULE.load_json_object(array, "private publication receipt")
            with self.assertRaisesRegex(ValueError, "duplicate JSON object name"):
                MODULE.load_json_object(duplicate, "private publication receipt")
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                MODULE.load_json_object(invalid, "private publication receipt")
            with self.assertRaisesRegex(ValueError, "missing or a symlink"):
                MODULE.load_json_object(broken_symlink, "private publication receipt")
            with self.assertRaisesRegex(ValueError, "missing or a symlink"):
                MODULE.load_json_object(root / "missing.json", "missing receipt")

    def test_load_json_object_rejects_receipts_that_change_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
            real_sha256_bytes = MODULE.sha256_bytes

            def tamper_after_initial_read(data: bytes) -> str:
                digest = real_sha256_bytes(data)
                receipt.write_text('{"status":"tampered"}\n', encoding="utf-8")
                return digest

            with (
                mock.patch.object(
                    MODULE,
                    "sha256_bytes",
                    side_effect=tamper_after_initial_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "private publication receipt changed during read",
                ),
            ):
                MODULE.load_json_object(receipt, "private publication receipt")

    def test_sha256_file_rejects_inputs_that_change_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runbook = Path(temporary) / "runbook.md"
            runbook.write_text("original\n", encoding="utf-8")
            real_sha256_bytes = MODULE.sha256_bytes

            def tamper_after_initial_read(data: bytes) -> str:
                digest = real_sha256_bytes(data)
                runbook.write_text("tampered\n", encoding="utf-8")
                return digest

            with (
                mock.patch.object(
                    MODULE,
                    "sha256_bytes",
                    side_effect=tamper_after_initial_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "runbook.md SHA-256 input changed during read",
                ),
            ):
                MODULE.sha256_file(runbook)

    def test_sha256_file_rejects_same_byte_leaf_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runbook = root / "runbook.md"
            replacement = root / "replacement-runbook.md"
            runbook.write_text("original\n", encoding="utf-8")
            replacement.write_text("original\n", encoding="utf-8")
            real_read_once = MODULE.read_real_input_file_once
            swapped = False

            def replace_after_initial_read(path: Path, label: str):
                nonlocal swapped
                data = real_read_once(path, label)
                if path == runbook and not swapped:
                    swapped = True
                    replacement.replace(runbook)
                return data

            with (
                mock.patch.object(
                    MODULE,
                    "read_real_input_file_once",
                    side_effect=replace_after_initial_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "runbook.md SHA-256 input changed during read",
                ),
            ):
                MODULE.sha256_file(runbook)

            self.assertTrue(swapped)

    def test_sha256_file_rejects_symlink_swap_between_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runbook = root / "runbook.md"
            relocated = root / "relocated-runbook.md"
            runbook.write_text("original\n", encoding="utf-8")
            real_read_once = MODULE.read_real_input_file_once
            reads = 0

            def swap_after_initial_read(path: Path, label: str):
                nonlocal reads
                data = real_read_once(path, label)
                if path == runbook and reads == 0:
                    runbook.unlink()
                    relocated.write_text("original\n", encoding="utf-8")
                    runbook.symlink_to(relocated)
                reads += 1
                return data

            with (
                mock.patch.object(
                    MODULE,
                    "read_real_input_file_once",
                    side_effect=swap_after_initial_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "runbook.md SHA-256 input is missing or a symlink",
                ),
            ):
                MODULE.sha256_file(runbook)

    def test_sha256_file_rejects_symlink_swap_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runbook = root / "runbook.md"
            relocated = root / "relocated-runbook.md"
            runbook.write_text("original\n", encoding="utf-8")
            real_os_open = MODULE.os.open
            moved = False

            def swap_before_open(
                path: Path,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal moved
                if path == runbook and not moved:
                    moved = True
                    runbook.unlink()
                    relocated.write_text("original\n", encoding="utf-8")
                    runbook.symlink_to(relocated)
                return real_os_open(path, flags, mode, dir_fd=dir_fd)

            with (
                mock.patch.object(
                    MODULE.os,
                    "open",
                    side_effect=swap_before_open,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "runbook.md SHA-256 input changed during read",
                ),
            ):
                MODULE.sha256_file(runbook)

            self.assertTrue(moved)

    def test_write_once_is_mode_0600_and_refuses_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runbook.md"

            with mock.patch.object(
                MODULE.os,
                "fsync",
                wraps=MODULE.os.fsync,
            ) as fsync:
                MODULE.write_once(output, "one\n")

            self.assertEqual(output.read_text(encoding="utf-8"), "one\n")
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(fsync.call_count, 2)
            with self.assertRaises(FileExistsError):
                MODULE.write_once(output, "two\n")

    def test_write_once_removes_partial_output_after_file_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runbook.md"

            with (
                mock.patch.object(
                    MODULE.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                MODULE.write_once(output, "partial\n")

            self.assertFalse(output.exists())

    def test_write_once_removes_partial_output_after_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runbook.md"

            with (
                mock.patch.object(
                    MODULE.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                MODULE.write_once(output, "partial\n")

            self.assertFalse(output.exists())

    def test_write_once_rehashes_after_directory_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runbook.md"
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text("tampered\n", encoding="utf-8")

            with (
                mock.patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_directory_fsync,
                ),
                self.assertRaisesRegex(ValueError, "output changed during write"),
            ):
                MODULE.write_once(output, "complete\n")

            self.assertFalse(output.exists())

    def test_write_once_rejects_same_byte_leaf_replacement_during_rehash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "runbook.md"
            replacement = root / "replacement-runbook.md"
            replacement.write_text("complete\n", encoding="utf-8")
            real_read_once = MODULE.read_real_input_file_once
            swapped = False

            def replace_after_initial_read(path: Path, label: str):
                nonlocal swapped
                data = real_read_once(path, label)
                if path == output and not swapped:
                    swapped = True
                    replacement.replace(output)
                return data

            with (
                mock.patch.object(
                    MODULE,
                    "read_real_input_file_once",
                    side_effect=replace_after_initial_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "runbook.md SHA-256 input changed during read",
                ),
            ):
                MODULE.write_once(output, "complete\n")

            self.assertTrue(swapped)
            self.assertFalse(output.exists())

    def test_write_once_rechecks_output_mode_after_directory_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runbook.md"
            real_fsync_directory = MODULE.fsync_directory

            def chmod_after_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.chmod(0o644)

            with (
                mock.patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=chmod_after_directory_fsync,
                ),
                self.assertRaisesRegex(ValueError, "output mode changed during write"),
            ):
                MODULE.write_once(output, "complete\n")

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
