from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Mapping

from diana_omics.commands.phase3_wgs import export_phase3_fast_small_variant_artifacts as small_variant_export
from diana_omics.commands.phase3_wgs import join_phase3_fast_evidence as evidence_join
from diana_omics.commands.phase3_wgs import plan_phase3_fast_crosscheck_inputs as crosscheck_plan
from diana_omics.commands.phase3_wgs import publish_phase3_fast_final_evidence as final_evidence
from diana_omics.commands.phase3_wgs import render_phase3_fast_bam_qc_plan as bam_qc_plan
from diana_omics.commands.phase3_wgs import render_phase3_fast_cache_manifest as cache_manifest
from diana_omics.commands.phase3_wgs import render_phase3_fast_cnv_evidence_plan as cnv_evidence_plan
from diana_omics.commands.phase3_wgs import render_phase3_fast_filter_mutect_plan as filter_mutect_plan
from diana_omics.commands.phase3_wgs import render_phase3_fast_input_manifest as input_manifest
from diana_omics.commands.phase3_wgs import render_phase3_fast_parabricks_mutect_plan as parabricks_plan
from diana_omics.commands.phase3_wgs import render_phase3_fast_replication_plan as replication_plan
from diana_omics.commands.phase3_wgs import render_phase3_fast_staging_plan as staging_plan
from diana_omics.commands.phase3_wgs import render_phase3_fast_sv_evidence_plan as sv_evidence_plan
from diana_omics.commands.phase3_wgs import replicate_phase3_fast_inputs as replication_receipt
from diana_omics.commands.phase3_wgs import run_phase3_fast_bam_qc as bam_qc
from diana_omics.commands.phase3_wgs import run_phase3_fast_cnv_evidence as cnv_evidence
from diana_omics.commands.phase3_wgs import run_phase3_fast_filter_mutect as filter_mutect
from diana_omics.commands.phase3_wgs import run_phase3_fast_parabricks_mutect as parabricks_mutect
from diana_omics.commands.phase3_wgs import run_phase3_fast_sv_evidence as sv_evidence
from diana_omics.commands.phase3_wgs import safe_json_output
from diana_omics.commands.phase3_wgs import stage_phase3_fast_inputs as stage_inputs
from diana_omics.commands.phase3_wgs import verify_phase3_fast_staged_inputs as staged_inputs
from diana_omics.commands.phase3_wgs.render_phase3_fast_input_manifest import ManifestError

Writer = Callable[[Path, Mapping[str, Any]], None]

WRITERS: tuple[tuple[str, Writer], ...] = (
    ("input_manifest", input_manifest.write_manifest),
    ("cache_manifest", cache_manifest.write_manifest),
    ("replication_plan", replication_plan.write_plan),
    ("staging_plan", staging_plan.write_plan),
    ("stage_inputs", stage_inputs.write_manifest),
    ("staged_inputs", staged_inputs.write_manifest),
    ("parabricks_plan", parabricks_plan.write_plan),
    ("filter_mutect_plan", filter_mutect_plan.write_plan),
    ("bam_qc_plan", bam_qc_plan.write_plan),
    ("cnv_evidence_plan", cnv_evidence_plan.write_plan),
    ("sv_evidence_plan", sv_evidence_plan.write_plan),
    ("replication_receipt", replication_receipt.write_receipt),
    ("parabricks_receipt", parabricks_mutect.write_receipt),
    ("filter_mutect_receipt", filter_mutect.write_receipt),
    ("bam_qc_receipt", bam_qc.write_receipt),
    ("cnv_evidence_receipt", cnv_evidence.write_receipt),
    ("sv_evidence_receipt", sv_evidence.write_receipt),
    ("small_variant_export", small_variant_export.write_receipt),
    ("evidence_join", evidence_join.write_manifest),
    ("final_evidence", final_evidence.write_manifest),
    ("crosscheck_plan", crosscheck_plan.write_plan),
)


class Phase3FastSafeJsonOutputsTests(unittest.TestCase):
    def test_rejects_symlinked_output_parent(self) -> None:
        for name, writer in WRITERS:
            for nested in ("missing", "existing"):
                with self.subTest(name=name, nested=nested), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    real_output = root / "real-output"
                    if nested == "existing":
                        (real_output / nested).mkdir(parents=True)
                    else:
                        real_output.mkdir()
                    linked_output = root / "linked-output"
                    linked_output.symlink_to(real_output, target_is_directory=True)

                    with self.assertRaisesRegex(
                        ManifestError, "parent may not be a symlink"
                    ):
                        writer(
                            linked_output / nested / f"{name}.json",
                            {"status": "redirected"},
                        )

                    self.assertFalse((real_output / nested / f"{name}.json").exists())

    def test_rejects_symlinked_output_file(self) -> None:
        for name, writer in WRITERS:
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_output = root / "real-output.json"
                linked_output = root / f"{name}.json"
                linked_output.symlink_to(real_output)

                with self.assertRaisesRegex(ManifestError, "may not be a symlink"):
                    writer(linked_output, {"status": "redirected"})

                self.assertFalse(real_output.exists())

    def test_read_real_json_rejects_redirected_inputs(self) -> None:
        for bad_kind in ("missing", "directory", "symlink"):
            with self.subTest(bad_kind=bad_kind), TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_input = root / "real-input.json"
                real_input.write_text('{"status": "redirected"}\n', encoding="utf-8")
                input_path = root / f"{bad_kind}.json"
                if bad_kind == "directory":
                    input_path.mkdir()
                elif bad_kind == "symlink":
                    input_path.symlink_to(real_input)

                with self.assertRaisesRegex(ManifestError, "must be a real JSON file"):
                    safe_json_output.read_real_json(input_path, "source", ManifestError)

    def test_read_real_json_reads_real_json_file(self) -> None:
        with TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            input_path.write_text('{"status": "ready"}\n', encoding="utf-8")

            payload = safe_json_output.read_real_json(input_path, "source", ManifestError)

        self.assertEqual({"status": "ready"}, payload)


if __name__ == "__main__":
    unittest.main()
