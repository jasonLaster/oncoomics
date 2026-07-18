import unittest
from pathlib import Path
from unittest.mock import patch

import diana_omics.commands as command_package
from diana_omics.cli import _format_command_families, _load_commands
from diana_omics.commands.registry import COMMAND_FAMILIES, COMMAND_SPECS, FAMILY_PACKAGES, TASK_ONLY_MODULES
from diana_omics.workflow_tasks import LEGACY_PHASE3_AWS_FULL_ENV, PHASE3_FAST_AWS_EXECUTE_ENV, TASKS, run_task


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
            "build:diana-samplesheet-from-delivery",
            "build:diana-template",
            "build:packet",
            "build:phase3-fast-bam-qc-plan",
            "build:phase3-fast-input-manifest",
            "build:phase3-fast-cache-manifest",
            "build:phase3-fast-crosscheck-materialization-plan",
            "build:phase3-fast-cnv-evidence-plan",
            "build:phase3-fast-filter-mutect-plan",
            "build:phase3-fast-parabricks-mutect-plan",
            "build:phase3-fast-replication-plan",
            "build:phase3-fast-staging-plan",
            "build:phase3-fast-sv-evidence-plan",
            "build:panel",
            "build:raw-samplesheets",
            "build:rosalind-hrd-packet",
            "diagnose:pipeline",
            "fetch:full-reference-smoke",
            "fetch:full-wes",
            "fetch:human-reference-smoke",
            "fetch:phase1",
            "fetch:phase3-wgs",
            "fetch:production-somatic",
            "fetch:raw-candidates",
            "join:phase3-fast-evidence",
            "plan:diana-raw-handoff",
            "plan:known-answer-benchmarks",
            "publish:phase3-fast-final-evidence",
            "replicate:phase3-fast-inputs",
            "run:known-answer-bounded-non-dry",
            "run:known-answer-expanded-cohort",
            "run:known-answer-public-findings",
            "export:phase3-fast-small-variants",
            "run:phase3-fast-bam-qc",
            "run:phase3-fast-cnv-evidence",
            "run:phase3-fast-filter-mutect",
            "run:phase3-fast-parabricks-mutect",
            "run:phase3-fast-sv-evidence",
            "smoke:alignment",
            "smoke:full-reference",
            "smoke:human-reference",
            "smoke:production-somatic",
            "smoke:raw",
            "stage:diana-raw",
            "stage:phase3-fast-deterministic-report",
            "stage:phase3-fast-inputs",
            "triage:rosalind-hrd-readiness",
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
            "verify:phase3-fast-aws-execute",
            "verify:phase3-fast-gpu-smoke",
            "verify:phase3-fast-staged-inputs",
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
        self.assertIn("aws:hrd-packet:cloud-submit", TASKS)
        self.assertIn("nf:aws:sra-bench:tiny", TASKS)
        self.assertIn("nf:phase3-wgs-fast:stub", TASKS)
        self.assertIn("nf:aws:phase3-wgs-fast:gpu-smoke", TASKS)
        self.assertIn("nf:aws:phase3-wgs-fast:execute", TASKS)
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
        self.assertTrue(TASKS["aws:hrd-packet:cloud-submit"].accepts_args)
        self.assertTrue(TASKS["aws:hrd-packet:cloud-submit"].steps[0].append_args)

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

    def test_legacy_phase3_aws_full_tasks_require_explicit_override(self):
        guarded_tasks = {
            "nf:aws:phase3-wgs:full",
            "nf:aws:phase3-wgs:full:ondemand-large",
            "nf:aws:phase3-wgs:full:ondemand-failfast",
            "nf:aws:phase3-wgs:monolith:full",
        }

        for name in guarded_tasks:
            self.assertEqual(LEGACY_PHASE3_AWS_FULL_ENV, TASKS[name].required_env)

        self.assertIsNone(TASKS["nf:aws:phase3-wgs-fast:gpu-smoke"].required_env)
        self.assertIsNone(TASKS["nf:phase3-wgs-fast:stub"].required_env)
        self.assertIsNone(TASKS["nf:aws:phase3-wgs:stub"].required_env)
        self.assertIsNone(TASKS["nf:aws:phase3-wgs:dev"].required_env)

    def test_phase3_fast_local_stub_exercises_execute_branch_synthetically(self):
        task = TASKS["nf:phase3-wgs-fast:stub"]

        self.assertFalse(task.accepts_args)
        self.assertEqual(("bash", "scripts/run_phase3_wgs_fast_stub.sh"), task.steps[0].argv)

    def test_phase3_fast_aws_execute_task_uses_guarded_p5en_path(self):
        task = TASKS["nf:aws:phase3-wgs-fast:execute"]

        self.assertTrue(task.accepts_args)
        self.assertEqual(2, len(task.steps))
        self.assertEqual("verify:phase3-fast-aws-execute", task.steps[0].argv[-1])
        self.assertFalse(task.steps[0].append_args)
        self.assertTrue(task.steps[1].append_args)
        self.assertEqual(PHASE3_FAST_AWS_EXECUTE_ENV, task.required_env)

        argv = task.steps[1].argv
        self.assertIn("awsbatch_gpu", argv)
        self.assertIn("infra/aws/nextflow.aws.use2.json", argv)
        self.assertEqual("phase3_wgs_fast", argv[argv.index("--workflow") + 1])
        self.assertEqual("apply", argv[argv.index("--phase3_fast_replication_mode") + 1])
        self.assertEqual("execute", argv[argv.index("--phase3_fast_small_variant_mode") + 1])
        self.assertIn("--aws_max_retries", argv)
        self.assertEqual("0", argv[argv.index("--aws_max_retries") + 1])

    @patch("diana_omics.workflow_tasks.subprocess.run")
    def test_legacy_phase3_aws_full_task_fails_before_nextflow_without_override(self, run):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit) as error:
                run_task("nf:aws:phase3-wgs:full")

        self.assertIn("ALLOW_LEGACY_PHASE3_AWS_FULL=YES", str(error.exception))
        run.assert_not_called()

    @patch("diana_omics.workflow_tasks.subprocess.run")
    def test_legacy_phase3_aws_full_task_runs_with_explicit_override(self, run):
        with patch.dict("os.environ", {"ALLOW_LEGACY_PHASE3_AWS_FULL": "YES"}, clear=True):
            run_task("nf:aws:phase3-wgs:full")

        run.assert_called_once()
        argv = run.call_args.args[0]
        env = run.call_args.kwargs["env"]
        self.assertEqual("nextflow", argv[0])
        self.assertEqual("phase3_wgs", argv[argv.index("--workflow") + 1])
        self.assertEqual("full", argv[argv.index("--phase3_reads") + 1])
        self.assertEqual("YES", env["ALLOW_LEGACY_PHASE3_AWS_FULL"])

    @patch("diana_omics.workflow_tasks.subprocess.run")
    def test_phase3_fast_aws_execute_task_fails_before_nextflow_without_override(self, run):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit) as error:
                run_task("nf:aws:phase3-wgs-fast:execute")

        self.assertIn("ALLOW_PHASE3_FAST_AWS_EXECUTE=YES", str(error.exception))
        run.assert_not_called()

    @patch("diana_omics.workflow_tasks.subprocess.run")
    def test_phase3_fast_aws_execute_task_appends_reviewed_gate0_params(self, run):
        extra_args = (
            "--",
            "--phase3_fast_private_freeze_receipt",
            "private-freeze.json",
            "--phase3_fast_forbidden_tokens_json",
            '["E019"]',
        )
        with patch.dict("os.environ", {"ALLOW_PHASE3_FAST_AWS_EXECUTE": "YES"}, clear=True):
            run_task("nf:aws:phase3-wgs-fast:execute", extra_args)

        self.assertEqual(2, run.call_count)
        self.assertEqual("verify:phase3-fast-aws-execute", run.call_args_list[0].args[0][-1])
        argv = run.call_args_list[1].args[0]
        env = run.call_args_list[1].kwargs["env"]
        self.assertEqual("phase3_wgs_fast", argv[argv.index("--workflow") + 1])
        self.assertEqual("execute", argv[argv.index("--phase3_fast_small_variant_mode") + 1])
        self.assertEqual("private-freeze.json", argv[argv.index("--phase3_fast_private_freeze_receipt") + 1])
        self.assertEqual('["E019"]', argv[argv.index("--phase3_fast_forbidden_tokens_json") + 1])
        self.assertEqual("YES", env["ALLOW_PHASE3_FAST_AWS_EXECUTE"])

    def test_p5en_gpu_smoke_task_uses_isolated_gpu_profile(self):
        task = TASKS["nf:aws:phase3-wgs-fast:gpu-smoke"]

        self.assertEqual("verify:phase3-fast-gpu-smoke", task.steps[0].argv[-1])

        argv = task.steps[1].argv
        self.assertIn("awsbatch_gpu", argv)
        self.assertIn("infra/aws/nextflow.aws.use2.json", argv)
        self.assertEqual("phase3_wgs_fast_gpu_smoke", argv[argv.index("--workflow") + 1])
        self.assertEqual("8", argv[argv.index("--phase3_fast_gpu_smoke_expected_gpus") + 1])
        self.assertEqual("H200", argv[argv.index("--phase3_fast_gpu_smoke_gpu_name") + 1])
        self.assertIn("--aws_max_retries", argv)
        self.assertEqual("0", argv[argv.index("--aws_max_retries") + 1])

    def test_use2_terraform_tasks_write_dedicated_gpu_params(self):
        plan_steps = TASKS["infra:aws:plan:use2"].steps
        self.assertEqual(
            ("terraform", "-chdir=infra/aws", "workspace", "select", "-or-create", "phase3-fast-use2"),
            plan_steps[0].argv,
        )
        plan_env = plan_steps[1].env
        assert plan_env is not None
        self.assertEqual("us-east-2", plan_env["TF_VAR_region"])
        self.assertEqual("prod-use2", plan_env["TF_VAR_environment"])
        self.assertEqual("nextflow.aws.use2.json", plan_env["TF_VAR_nextflow_params_filename"])

        use1_steps = TASKS["infra:aws:plan:use1"].steps
        use1_env = use1_steps[1].env
        assert use1_env is not None
        self.assertEqual("nextflow.aws.json", use1_env["TF_VAR_nextflow_params_filename"])


if __name__ == "__main__":
    unittest.main()
