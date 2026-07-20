from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import export_phase3_fast_small_variant_artifacts as export_small_variants
from diana_omics.commands.phase3_wgs import run_phase3_fast_filter_mutect as run_filter
from diana_omics.commands.phase3_wgs import run_phase3_fast_parabricks_mutect as run_parabricks
from diana_omics.utils import write_json
from tests.test_phase3_fast_filter_mutect_run import FilterMutectRunner, filter_plan_and_parabricks_receipt
from tests.test_phase3_fast_input_manifest import SHA_1

SHA_2 = "b" * 64
SHA_3 = "c" * 64


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipts(root: Path) -> tuple[dict, dict]:
    filter_plan, parabricks_receipt = filter_plan_and_parabricks_receipt(root)
    filter_receipt = run_filter.run_phase3_fast_filter_mutect(
        filter_plan,
        parabricks_receipt,
        runner=FilterMutectRunner(),
        filter_mutect_plan_sha256=SHA_1,
        parabricks_mutect_receipt_sha256=SHA_2,
    )
    return parabricks_receipt, filter_receipt


class Phase3FastSmallVariantExportTests(unittest.TestCase):
    def test_exports_receipt_verified_materialized_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "workspace" / "results" / "phase3_wgs_fast"
            parabricks_receipt, filter_receipt = _receipts(root)

            receipt = export_small_variants.export_phase3_fast_small_variant_artifacts(
                parabricks_receipt,
                filter_receipt,
                parabricks_mutect_receipt_sha256=SHA_2,
                filter_mutect_receipt_sha256=SHA_3,
                output_root=output_root,
            )

        self.assertEqual("phase3_wgs_fast_small_variant_artifact_export", receipt["manifest_type"])
        self.assertEqual("completed", receipt["status"])
        self.assertEqual("no_call", receipt["interpretation"]["authorized_hrd_state"])
        self.assertEqual(SHA_2, receipt["source"]["parabricks_mutect_receipt_sha256"])
        self.assertEqual(SHA_3, receipt["source"]["filter_mutect_receipt_sha256"])
        self.assertEqual(set(run_parabricks.MATERIALIZED_OUTPUTS), set(receipt["exports"]["parabricks_mutect"]))
        self.assertEqual(set(run_filter.MATERIALIZED_OUTPUTS), set(receipt["exports"]["filter_mutect"]))
        self.assertEqual("copy-version-5", receipt["input_sources"]["reference"]["fasta"]["version_id"])
        self.assertEqual("copy-version-1", receipt["input_sources"]["bam_pair"]["tumor"]["bam"]["version_id"])
        self.assertEqual("subject01_tumor", receipt["input_sources"]["bam_pair"]["tumor"]["bam"]["sample_id"])
        self.assertEqual(
            "copy-version-15",
            receipt["input_sources"]["caller_resources"]["panel_of_normals_vcf"]["version_id"],
        )
        exported_filtered = receipt["exports"]["filter_mutect"]["filtered_vcf"]
        self.assertEqual(
            filter_receipt["materialized_outputs"]["filtered_vcf"]["sha256"],
            exported_filtered["sha256"],
        )
        self.assertTrue(exported_filtered["exported_path"].endswith("/filter_mutect/filtered_vcf/diana.wgs.mutect2.parabricks.filtered.vcf.gz"))

    def test_environment_command_writes_export_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parabricks_receipt_path = root / "parabricks-receipt.json"
            filter_receipt_path = root / "filter-receipt.json"
            export_root = root / "exported"
            export_path = root / "small-variant-export.json"
            parabricks_receipt, filter_receipt = _receipts(root)
            write_json(parabricks_receipt_path, parabricks_receipt)
            filter_receipt["source"]["parabricks_mutect_receipt_sha256"] = _sha256_json(parabricks_receipt_path)
            write_json(filter_receipt_path, filter_receipt)
            expected_parabricks_sha = _sha256_json(parabricks_receipt_path)
            expected_filter_sha = _sha256_json(filter_receipt_path)

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT": str(parabricks_receipt_path),
                    "PHASE3_WGS_FAST_FILTER_MUTECT_RECEIPT": str(filter_receipt_path),
                    "PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT_ROOT": str(export_root),
                    "PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT_OUTPUT": str(export_path),
                },
                clear=False,
            ):
                receipt, output = export_small_variants.load_export_from_environment()
                export_small_variants.write_receipt(output, receipt)
            export_text = export_path.read_text()

        self.assertEqual(export_path, output)
        self.assertEqual(expected_parabricks_sha, receipt["source"]["parabricks_mutect_receipt_sha256"])
        self.assertEqual(expected_filter_sha, receipt["source"]["filter_mutect_receipt_sha256"])
        self.assertIn('"manifest_type": "phase3_wgs_fast_small_variant_artifact_export"', export_text)

    def test_environment_command_binds_export_to_parsed_receipts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parabricks_receipt_path = root / "parabricks-receipt.json"
            filter_receipt_path = root / "filter-receipt.json"
            parabricks_receipt, filter_receipt = _receipts(root)
            write_json(parabricks_receipt_path, parabricks_receipt)
            original_parabricks_sha = _sha256_json(parabricks_receipt_path)
            filter_receipt["source"]["parabricks_mutect_receipt_sha256"] = (
                original_parabricks_sha
            )
            write_json(filter_receipt_path, filter_receipt)
            original_filter_sha = _sha256_json(filter_receipt_path)
            real_read = export_small_variants.read_real_json_with_sha256

            def mutate_after_read(path, label, error_type):
                value, digest = real_read(path, label, error_type)
                write_json(path, {"status": "mutated"})
                return value, digest

            with (
                patch.dict(
                    "os.environ",
                    {
                        "PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT": str(
                            parabricks_receipt_path
                        ),
                        "PHASE3_WGS_FAST_FILTER_MUTECT_RECEIPT": str(
                            filter_receipt_path
                        ),
                        "PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT_ROOT": str(
                            root / "exported"
                        ),
                        "PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT_OUTPUT": str(
                            root / "small-variant-export.json"
                        ),
                    },
                    clear=False,
                ),
                patch.object(
                    export_small_variants,
                    "read_real_json_with_sha256",
                    side_effect=mutate_after_read,
                ),
            ):
                receipt, _output = export_small_variants.load_export_from_environment()

        self.assertEqual(
            original_parabricks_sha,
            receipt["source"]["parabricks_mutect_receipt_sha256"],
        )
        self.assertEqual(
            original_filter_sha,
            receipt["source"]["filter_mutect_receipt_sha256"],
        )

    def test_environment_command_rejects_redirected_receipts_before_copying_artifacts(self) -> None:
        cases = (
            (
                "Parabricks receipt",
                "PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT",
                "parabricks-receipt.json",
            ),
            (
                "FilterMutect receipt",
                "PHASE3_WGS_FAST_FILTER_MUTECT_RECEIPT",
                "filter-receipt.json",
            ),
        )
        for label, env_name, file_name in cases:
            with self.subTest(label=label), TemporaryDirectory() as tmp:
                root = Path(tmp)
                parabricks_receipt, filter_receipt = _receipts(root)
                parabricks_path = root / "parabricks-receipt.json"
                filter_path = root / "filter-receipt.json"
                write_json(parabricks_path, parabricks_receipt)
                filter_receipt["source"]["parabricks_mutect_receipt_sha256"] = _sha256_json(
                    parabricks_path
                )
                write_json(filter_path, filter_receipt)
                redirected_path = root / f"redirected-{file_name}"
                redirected_path.symlink_to(root / file_name)
                output_root = root / "exported"

                with patch.dict(
                    "os.environ",
                    {
                        "PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT": str(parabricks_path),
                        "PHASE3_WGS_FAST_FILTER_MUTECT_RECEIPT": str(filter_path),
                        "PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT_ROOT": str(output_root),
                        "PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT_OUTPUT": str(
                            root / "small-variant-export.json"
                        ),
                        env_name: str(redirected_path),
                    },
                    clear=False,
                ):
                    with self.assertRaisesRegex(
                        export_small_variants.ManifestError, "real JSON file"
                    ):
                        export_small_variants.load_export_from_environment()

                self.assertFalse(output_root.exists())

    def test_sha256_path_rejects_symlinked_hash_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-parent"
            real_parent.mkdir()

            real_receipt = root / "real-parabricks.json"
            real_receipt.write_text("{}\n", encoding="utf-8")
            symlinked_receipt = root / "parabricks.json"
            symlinked_receipt.symlink_to(real_receipt)

            parent_receipt = real_parent / "parabricks.json"
            parent_receipt.write_text("{}\n", encoding="utf-8")
            symlinked_parent = root / "symlinked-parent"
            symlinked_parent.symlink_to(real_parent, target_is_directory=True)

            cases = (
                (symlinked_receipt, "SHA-256 input"),
                (symlinked_parent / parent_receipt.name, "parent may not be a symlink"),
            )
            for hash_input, message in cases:
                with self.subTest(hash_input=hash_input), self.assertRaisesRegex(
                    export_small_variants.ManifestError, message
                ):
                    export_small_variants._sha256_path(hash_input)

    def test_rejects_parabricks_file_that_changed_after_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parabricks_receipt, filter_receipt = _receipts(root)
            Path(parabricks_receipt["materialized_outputs"]["raw_vcf"]["local_path"]).write_bytes(b"changed\n")

            with self.assertRaisesRegex(export_small_variants.ManifestError, "raw_vcf source bytes and sha256"):
                export_small_variants.export_phase3_fast_small_variant_artifacts(
                    parabricks_receipt,
                    filter_receipt,
                    parabricks_mutect_receipt_sha256=SHA_2,
                    filter_mutect_receipt_sha256=SHA_3,
                    output_root=root / "exported",
                )

            self.assertFalse((root / "exported").exists())

    def test_rejects_non_exact_input_source_bytes_before_exporting_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parabricks_receipt, filter_receipt = _receipts(root)
            parabricks_receipt["inputs"]["reference_fasta"]["source"]["bytes"] = True
            filter_receipt["inputs"]["reference_fasta"]["source"]["bytes"] = True

            with self.assertRaisesRegex(export_small_variants.ManifestError, "reference_fasta source bytes"):
                export_small_variants.export_phase3_fast_small_variant_artifacts(
                    parabricks_receipt,
                    filter_receipt,
                    parabricks_mutect_receipt_sha256=SHA_2,
                    filter_mutect_receipt_sha256=SHA_3,
                    output_root=root / "exported",
                )

            self.assertFalse((root / "exported").exists())

    def test_rejects_non_exact_materialized_output_bytes_before_exporting_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parabricks_receipt, filter_receipt = _receipts(root)
            raw_vcf = parabricks_receipt["materialized_outputs"]["raw_vcf"]
            Path(raw_vcf["local_path"]).write_bytes(b"x")
            raw_vcf["bytes"] = True
            raw_vcf["sha256"] = hashlib.sha256(b"x").hexdigest()

            with self.assertRaisesRegex(export_small_variants.ManifestError, "raw_vcf.bytes"):
                export_small_variants.export_phase3_fast_small_variant_artifacts(
                    parabricks_receipt,
                    filter_receipt,
                    parabricks_mutect_receipt_sha256=SHA_2,
                    filter_mutect_receipt_sha256=SHA_3,
                    output_root=root / "exported",
                )

            self.assertFalse((root / "exported").exists())

    def test_rejects_symlinked_source_before_exporting_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parabricks_receipt, filter_receipt = _receipts(root)
            source = Path(parabricks_receipt["materialized_outputs"]["raw_vcf"]["local_path"])
            redirected = source.parent / "raw_vcf.redirected"
            source.rename(redirected)
            source.symlink_to(redirected)

            with self.assertRaisesRegex(export_small_variants.ManifestError, "source may not be a symlink"):
                export_small_variants.export_phase3_fast_small_variant_artifacts(
                    parabricks_receipt,
                    filter_receipt,
                    parabricks_mutect_receipt_sha256=SHA_2,
                    filter_mutect_receipt_sha256=SHA_3,
                    output_root=root / "exported",
                )

            self.assertFalse((root / "exported").exists())

    def test_rejects_filter_receipt_that_does_not_match_parabricks_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parabricks_receipt, filter_receipt = _receipts(root)
            filter_receipt["source"]["parabricks_mutect_receipt_sha256"] = "d" * 64

            with self.assertRaisesRegex(export_small_variants.ManifestError, "Parabricks receipt SHA-256"):
                export_small_variants.export_phase3_fast_small_variant_artifacts(
                    parabricks_receipt,
                    filter_receipt,
                    parabricks_mutect_receipt_sha256=SHA_2,
                    filter_mutect_receipt_sha256=SHA_3,
                    output_root=root / "exported",
                )

            self.assertFalse((root / "exported").exists())

    def test_rejects_filter_receipt_with_different_reference_source(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parabricks_receipt, filter_receipt = _receipts(root)
            filter_receipt["inputs"]["reference_fasta"]["source"]["version_id"] = "raced-version"

            with self.assertRaisesRegex(export_small_variants.ManifestError, "reference_fasta source"):
                export_small_variants.export_phase3_fast_small_variant_artifacts(
                    parabricks_receipt,
                    filter_receipt,
                    parabricks_mutect_receipt_sha256=SHA_2,
                    filter_mutect_receipt_sha256=SHA_3,
                    output_root=root / "exported",
                )

            self.assertFalse((root / "exported").exists())

    def test_rejects_untracked_stale_export_before_copying_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "exported"
            stale = output_root / "filter_mutect" / "old.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale\n", encoding="utf-8")
            parabricks_receipt, filter_receipt = _receipts(root)

            with self.assertRaisesRegex(export_small_variants.ManifestError, "unexpected existing export files"):
                export_small_variants.export_phase3_fast_small_variant_artifacts(
                    parabricks_receipt,
                    filter_receipt,
                    parabricks_mutect_receipt_sha256=SHA_2,
                    filter_mutect_receipt_sha256=SHA_3,
                    output_root=output_root,
                )

            self.assertEqual([stale], [path for path in output_root.rglob("*") if path.is_file()])

    def test_removes_partial_temporary_export_after_copy_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "exported"
            parabricks_receipt, filter_receipt = _receipts(root)
            original_write_bytes = Path.write_bytes

            def fail_after_partial_write(destination: Path, payload: bytes) -> int:
                if destination.name.startswith(".") and destination.name.endswith(".tmp"):
                    original_write_bytes(destination, b"partial small variant artifact")
                    raise OSError("simulated export interruption")
                return original_write_bytes(destination, payload)

            with patch.object(Path, "write_bytes", fail_after_partial_write):
                with self.assertRaisesRegex(OSError, "simulated export interruption"):
                    export_small_variants.export_phase3_fast_small_variant_artifacts(
                        parabricks_receipt,
                        filter_receipt,
                        parabricks_mutect_receipt_sha256=SHA_2,
                        filter_mutect_receipt_sha256=SHA_3,
                        output_root=output_root,
                    )

            self.assertEqual([], [path for path in output_root.rglob("*") if path.is_file()])

    def test_copies_previously_validated_source_bytes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "exported"
            parabricks_receipt, filter_receipt = _receipts(root)
            source = Path(parabricks_receipt["materialized_outputs"]["raw_vcf"]["local_path"])
            source_payload = source.read_bytes()
            target_temporary = output_root / "parabricks_mutect" / "raw_vcf" / f".{source.name}.tmp"
            original_write_bytes = Path.write_bytes
            mutated = False

            def mutate_source_before_temporary_write(destination: Path, payload: bytes) -> int:
                nonlocal mutated
                if destination == target_temporary:
                    mutated = True
                    original_write_bytes(source, b"changed\n")
                return original_write_bytes(destination, payload)

            with patch.object(Path, "write_bytes", mutate_source_before_temporary_write):
                export = export_small_variants.export_phase3_fast_small_variant_artifacts(
                    parabricks_receipt,
                    filter_receipt,
                    parabricks_mutect_receipt_sha256=SHA_2,
                    filter_mutect_receipt_sha256=SHA_3,
                    output_root=output_root,
                )

            exported = Path(export["exports"]["parabricks_mutect"]["raw_vcf"]["exported_path"])
            self.assertTrue(mutated)
            self.assertEqual(source_payload, exported.read_bytes())
            self.assertEqual(b"changed\n", source.read_bytes())

    def test_rejects_symlinked_temporary_export_before_installing_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "exported"
            redirected = root / "redirected-small-variant-artifact"
            parabricks_receipt, filter_receipt = _receipts(root)
            original_write_bytes = Path.write_bytes

            def write_symlink(destination: Path, payload: bytes) -> int:
                if destination.name.startswith(".") and destination.name.endswith(".tmp"):
                    original_write_bytes(redirected, b"redirected small variant artifact")
                    destination.symlink_to(redirected)
                    return len(payload)
                return original_write_bytes(destination, payload)

            with patch.object(Path, "write_bytes", write_symlink):
                with self.assertRaisesRegex(export_small_variants.ManifestError, "may not be a symlink"):
                    export_small_variants.export_phase3_fast_small_variant_artifacts(
                        parabricks_receipt,
                        filter_receipt,
                        parabricks_mutect_receipt_sha256=SHA_2,
                        filter_mutect_receipt_sha256=SHA_3,
                        output_root=output_root,
                    )

            self.assertEqual([], [path for path in output_root.rglob("*") if path.is_file()])

    def test_rejects_and_removes_tampered_installed_export(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "exported"
            parabricks_receipt, filter_receipt = _receipts(root)
            original_replace = Path.replace

            def replace_then_tamper(source: Path, target: Path) -> Path:
                installed = original_replace(source, target)
                Path(target).write_bytes(b"tampered installed export\n")
                return installed

            with patch.object(Path, "replace", replace_then_tamper):
                with self.assertRaisesRegex(
                    export_small_variants.ManifestError,
                    "exported bytes and sha256",
                ):
                    export_small_variants.export_phase3_fast_small_variant_artifacts(
                        parabricks_receipt,
                        filter_receipt,
                        parabricks_mutect_receipt_sha256=SHA_2,
                        filter_mutect_receipt_sha256=SHA_3,
                        output_root=output_root,
                    )

            self.assertEqual([], [path for path in output_root.rglob("*") if path.is_file()])

    def test_rejects_untracked_symlinked_export_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "exported"
            linked_dir = output_root / "old"
            real_dir = root / "real-old"
            real_dir.mkdir()
            linked_dir.parent.mkdir(parents=True)
            linked_dir.symlink_to(real_dir, target_is_directory=True)
            parabricks_receipt, filter_receipt = _receipts(root)

            with self.assertRaisesRegex(export_small_variants.ManifestError, "output_root contains a symlink"):
                export_small_variants.export_phase3_fast_small_variant_artifacts(
                    parabricks_receipt,
                    filter_receipt,
                    parabricks_mutect_receipt_sha256=SHA_2,
                    filter_mutect_receipt_sha256=SHA_3,
                    output_root=output_root,
                )

            self.assertEqual([], list(real_dir.rglob("*")))

    def test_rejects_export_destination_that_is_not_a_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "exported"
            parabricks_receipt, filter_receipt = _receipts(root)
            raw_vcf_name = Path(parabricks_receipt["materialized_outputs"]["raw_vcf"]["local_path"]).name
            (output_root / "parabricks_mutect" / "raw_vcf" / raw_vcf_name).mkdir(parents=True)

            with self.assertRaisesRegex(export_small_variants.ManifestError, "export destination"):
                export_small_variants.export_phase3_fast_small_variant_artifacts(
                    parabricks_receipt,
                    filter_receipt,
                    parabricks_mutect_receipt_sha256=SHA_2,
                    filter_mutect_receipt_sha256=SHA_3,
                    output_root=output_root,
                )

    def test_rejects_symlinked_output_root_without_copying_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_output = root / "real-exported"
            real_output.mkdir()
            output_root = root / "exported"
            output_root.symlink_to(real_output, target_is_directory=True)
            parabricks_receipt, filter_receipt = _receipts(root)

            with self.assertRaisesRegex(export_small_variants.ManifestError, "output_root.*symlink"):
                export_small_variants.export_phase3_fast_small_variant_artifacts(
                    parabricks_receipt,
                    filter_receipt,
                    parabricks_mutect_receipt_sha256=SHA_2,
                    filter_mutect_receipt_sha256=SHA_3,
                    output_root=output_root,
                )

            self.assertEqual([], list(real_output.rglob("*")))

    def test_rejects_output_root_below_symlinked_parent_without_copying_outputs(self) -> None:
        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_output = root / "real-exported"
                if nested == "existing":
                    (real_output / nested).mkdir(parents=True)
                else:
                    real_output.mkdir()
                linked_output = root / "linked-exported"
                linked_output.symlink_to(real_output, target_is_directory=True)
                parabricks_receipt, filter_receipt = _receipts(root)

                with self.assertRaisesRegex(export_small_variants.ManifestError, "parent may not be a symlink"):
                    export_small_variants.export_phase3_fast_small_variant_artifacts(
                        parabricks_receipt,
                        filter_receipt,
                        parabricks_mutect_receipt_sha256=SHA_2,
                        filter_mutect_receipt_sha256=SHA_3,
                        output_root=linked_output / nested / "exported",
                    )

                self.assertEqual([], [path for path in real_output.rglob("*") if path.is_file()])


if __name__ == "__main__":
    unittest.main()
