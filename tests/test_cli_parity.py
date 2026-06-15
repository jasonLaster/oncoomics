import unittest

from diana_omics.cli import _load_commands
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
            "normalize:vendor",
            "plan:known-answer-benchmarks",
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
            "verify:known-answer-readiness",
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

    def test_python_task_runner_owns_workflow_aliases(self):
        self.assertIn("run:all", TASKS)
        self.assertIn("benchmark:known-answer", TASKS)
        self.assertIn("nf:aws:sra-bench:tiny", TASKS)
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
        self.assertIn("--aws_max_retries", argv)
        self.assertEqual("0", argv[argv.index("--aws_max_retries") + 1])
        self.assertEqual("16", argv[argv.index("--phase3_align_cpus") + 1])
        self.assertEqual("96 GB", argv[argv.index("--phase3_align_memory") + 1])
        self.assertEqual("12", argv[argv.index("--phase3_bwa_threads") + 1])
        self.assertEqual("4", argv[argv.index("--phase3_sort_threads") + 1])
        self.assertNotIn("64", argv[argv.index("--phase3_align_cpus") + 1])


if __name__ == "__main__":
    unittest.main()
