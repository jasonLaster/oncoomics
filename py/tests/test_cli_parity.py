import json
import unittest

from diana_omics.cli import _load_commands
from diana_omics.paths import ROOT


class CliParityTest(unittest.TestCase):
    def test_python_cli_registers_all_bun_workflow_commands(self):
        package_json = json.loads((ROOT / "package.json").read_text())
        excluded = {
            "typecheck",
            "test",
            "py:lint",
            "py:format",
            "py:format:check",
            "py:typecheck",
            "py:test",
            "run:all",
            "verify:plan:online",
        }
        expected = {
            name for name, command in package_json["scripts"].items() if name not in excluded and "python3 -m diana_omics" in command
        }
        commands = _load_commands()
        self.assertEqual(expected, set(commands))

    def test_phase3_commands_are_registered(self):
        commands = _load_commands()
        self.assertIn("fetch:phase3-wgs", commands)
        self.assertIn("smoke:phase3-wgs", commands)

    def test_registered_commands_are_callable(self):
        for name, command in _load_commands().items():
            self.assertTrue(callable(command), name)


if __name__ == "__main__":
    unittest.main()
