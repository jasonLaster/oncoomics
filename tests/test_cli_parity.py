import unittest
from pathlib import Path

import diana_omics.commands as command_package
from diana_omics.cli import _format_command_families, _load_commands
from diana_omics.commands.registry import COMMAND_FAMILIES, COMMAND_SPECS, FAMILY_PACKAGES, TASK_ONLY_MODULES
from diana_omics.workflow_tasks import TASKS


class CliParityTest(unittest.TestCase):
    def test_python_cli_registers_core_workflow_commands(self):
        expected = {
            "analyze:hrd",
            "analyze:lehmann",
            "analyze:rna",
            "audit:raw-tools",
            "benchmark:full-wes",
            "benchmark:sra-range",
            "build:alignment-smoke",
            "build:diana-template",
            "build:packet",
            "build:panel",
            "build:raw-samplesheets",
            "diagnose:pipeline",
            "fetch:full-reference-smoke",
            "fetch:full-wes",
            "fetch:human-reference-smoke",
            "fetch:phase1",
            "fetch:phase3-wgs",
            "fetch:production-somatic",
            "fetch:raw-candidates",
            "plan:known-answer-benchmarks",
            "run:known-answer-bounded-non-dry",
            "run:known-answer-expanded-cohort",
            "run:known-answer-public-findings",
            "smoke:alignment",
            "smoke:full-reference",
            "smoke:human-reference",
            "smoke:production-somatic",
            "smoke:raw",
            "stage:diana-raw",
            "validate:phase3-wgs",
            "verify:clinical-assay-boundaries",
            "verify:clinical-change-control",
            "verify:clinical-qc-thresholds",
            "verify:clinical-signoff-workflow",
            "verify:clinical-validation-evidence-links",
            "verify:clinical-validation-packet",
            "verify:clinicalization-readiness-rollup",
            "verify:cnv-loh-readiness",
            "verify:diana-raw",
            "verify:hrd-interpretation-readiness",
            "verify:known-answer-asset-acquisition",
            "verify:known-answer-asset-approval-packet",
            "verify:known-answer-asset-integrity",
            "verify:known-answer-benchmark-manifests",
            "verify:known-answer-checksum-policy",
            "verify:known-answer-public-findings",
            "verify:known-answer-readiness",
            "verify:known-answer-sample-pull-plan",
            "verify:orthogonal",
            "verify:outputs",
            "verify:phase3-outputs",
            "verify:plan",
            "verify:sv-caller-readiness",
        }
        commands = _load_commands()
        self.assertEqual(expected, set(commands))

    def test_phase3_commands_are_registered(self):
        commands = _load_commands()
        self.assertIn("fetch:phase3-wgs", commands)
        self.assertIn("validate:phase3-wgs", commands)

    def test_registered_commands_are_callable(self):
        for name, command in _load_commands().items():
            self.assertTrue(callable(command), name)

    def test_registered_commands_have_specs(self):
        self.assertEqual(set(COMMAND_SPECS), set(_load_commands()))

    def test_command_package_exports_registered_modules(self):
        module_names = {spec.module.rsplit(".", 1)[-1] for spec in COMMAND_SPECS.values()}
        module_names.update(module.rsplit(".", 1)[-1] for module in TASK_ONLY_MODULES)
        self.assertEqual(module_names, set(command_package.__all__))

    def test_command_specs_point_to_family_modules(self):
        for name, spec in COMMAND_SPECS.items():
            module_parts = spec.module.split(".")
            self.assertEqual(["diana_omics", "commands"], module_parts[:2], name)
            self.assertIn(module_parts[2], FAMILY_PACKAGES, name)
            self.assertGreaterEqual(len(module_parts), 4, name)

    def test_task_only_modules_point_to_family_modules(self):
        for module in TASK_ONLY_MODULES:
            module_parts = module.split(".")
            self.assertEqual(["diana_omics", "commands"], module_parts[:2], module)
            self.assertIn(module_parts[2], FAMILY_PACKAGES, module)
            self.assertGreaterEqual(len(module_parts), 4, module)

    def test_command_modules_are_grouped_in_family_directories(self):
        commands_dir = Path(__file__).parents[1] / "src" / "diana_omics" / "commands"
        flat_modules = sorted(path.name for path in commands_dir.glob("*.py"))
        self.assertEqual(["__init__.py", "registry.py"], flat_modules)

    def test_command_families_cover_cli_surface(self):
        command_names = set(_load_commands()) | set(TASKS)
        family_names = [name for family in COMMAND_FAMILIES for name in family.commands]
        self.assertEqual(command_names, set(family_names))
        self.assertEqual(len(family_names), len(set(family_names)))

    def test_command_families_have_descriptions(self):
        for family in COMMAND_FAMILIES:
            self.assertGreaterEqual(len(family.description.split()), 6, family.title)

    def test_help_formats_commands_by_family(self):
        help_text = _format_command_families(set(_load_commands()) | set(TASKS))
        self.assertIn("Command families:", help_text)
        self.assertIn("HRD and RNA context:", help_text)
        self.assertIn("Build processed public context", help_text)
        self.assertIn("Phase 3 WGS:", help_text)
        self.assertIn("AWS and deployment:", help_text)
        self.assertNotIn("Other:", help_text)

    def test_python_task_runner_owns_workflow_aliases(self):
        self.assertIn("run:all", TASKS)
        self.assertIn("benchmark:known-answer", TASKS)
        self.assertIn("nf:aws:sra-bench:tiny", TASKS)
        self.assertIn("nf:aws:known-answer-bounded-non-dry", TASKS)
        self.assertIn("nf:aws:known-answer-expanded-cohort", TASKS)
        self.assertIn("phase3:stage:align:tumor", TASKS)
        forbidden = "b" + "un"
        for name, task in TASKS.items():
            for step in task.steps:
                self.assertNotIn(forbidden, step.argv, name)

    def test_nextflow_tasks_write_logs_under_logs(self):
        for name, task in TASKS.items():
            for step in task.steps:
                if step.argv and step.argv[0] == "nextflow":
                    self.assertEqual(("nextflow", "-log", "logs/nextflow.log", "run", "main.nf"), step.argv[:5], name)

    def test_test_task_accepts_pytest_arguments(self):
        self.assertTrue(TASKS["py:test"].accepts_args)
        self.assertTrue(TASKS["py:test"].steps[0].append_args)
        self.assertTrue(TASKS["benchmark:known-answer"].accepts_args)
        self.assertTrue(TASKS["benchmark:known-answer"].steps[0].append_args)

    def test_phase3_aws_failfast_task_is_conservative(self):
        argv = TASKS["nf:aws:phase3-wgs:full:ondemand-failfast"].steps[0].argv
        self.assertIn("awsbatch_ondemand", argv)
        self.assertEqual("public_bam", argv[argv.index("--phase3_source_mode") + 1])
        self.assertEqual("flagstat_only", argv[argv.index("--phase3_bam_validation_mode") + 1])
        self.assertEqual("full", argv[argv.index("--phase3_coverage_cnv_mode") + 1])
        self.assertIn("--aws_max_retries", argv)
        self.assertEqual("0", argv[argv.index("--aws_max_retries") + 1])
        self.assertEqual("16", argv[argv.index("--phase3_align_cpus") + 1])
        self.assertEqual("96 GB", argv[argv.index("--phase3_align_memory") + 1])
        self.assertEqual("12", argv[argv.index("--phase3_bwa_threads") + 1])
        self.assertEqual("4", argv[argv.index("--phase3_sort_threads") + 1])
        self.assertNotIn("64", argv[argv.index("--phase3_align_cpus") + 1])


if __name__ == "__main__":
    unittest.main()
