from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

INVENTORY_SCRIPT = SCRIPT_DIR / "hrd_report_inventory.py"
INVENTORY_SPEC = importlib.util.spec_from_file_location("hrd_report_inventory", INVENTORY_SCRIPT)
assert INVENTORY_SPEC and INVENTORY_SPEC.loader
INVENTORY = importlib.util.module_from_spec(INVENTORY_SPEC)
INVENTORY_SPEC.loader.exec_module(INVENTORY)

PUBLISH_SCRIPT = SCRIPT_DIR / "publish_reviewed_public_report.py"
PUBLISH_SPEC = importlib.util.spec_from_file_location("publish_reviewed_public_report", PUBLISH_SCRIPT)
assert PUBLISH_SPEC and PUBLISH_SPEC.loader
PUBLISH = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(PUBLISH)

BLOCKED_SCRIPT = SCRIPT_DIR / "generate_blocked_hrd_crosscheck_reports.py"
BLOCKED_SPEC = importlib.util.spec_from_file_location("generate_blocked_hrd_crosscheck_reports", BLOCKED_SCRIPT)
assert BLOCKED_SPEC and BLOCKED_SPEC.loader
BLOCKED = importlib.util.module_from_spec(BLOCKED_SPEC)
BLOCKED_SPEC.loader.exec_module(BLOCKED)

STAGE_SCRIPT = SCRIPT_DIR / "stage_hrd_crosscheck_report.py"
STAGE_SPEC = importlib.util.spec_from_file_location("stage_hrd_crosscheck_report", STAGE_SCRIPT)
assert STAGE_SPEC and STAGE_SPEC.loader
STAGE = importlib.util.module_from_spec(STAGE_SPEC)
STAGE_SPEC.loader.exec_module(STAGE)


class Stringy:
    def __init__(self, value: str):
        self.value = value

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"Stringy({self.value!r})"


class HrdReportInventoryTests(unittest.TestCase):
    def test_publisher_contracts_follow_pinned_method_inventory(self) -> None:
        self.assertEqual(
            tuple(PUBLISH.METHOD_CONTRACTS),
            INVENTORY.REPORT_METHOD_IDS,
        )
        self.assertEqual(
            tuple(PUBLISH.METHOD_CONTRACTS)[: len(INVENTORY.REQUIRED_METHOD_IDS)],
            INVENTORY.REQUIRED_METHOD_IDS,
        )

    def test_crosscheck_generators_cover_canonical_slices(self) -> None:
        self.assertEqual(
            tuple(method["method_id"] for method in BLOCKED.METHODS),
            INVENTORY.BLOCKED_CROSSCHECK_METHOD_IDS,
        )
        self.assertEqual(
            INVENTORY.BLOCKED_CROSSCHECK_REPORT_DIRS,
            {method["method_id"]: method["directory"] for method in BLOCKED.METHODS},
        )
        self.assertEqual(
            tuple(sorted(STAGE.SUPPORTED_ROUTES)),
            tuple(sorted(INVENTORY.EXECUTABLE_CROSSCHECK_METHOD_IDS)),
        )

    def test_inventory_binding_rejects_reorder_or_digest_drift(self) -> None:
        payload = INVENTORY.inventory_payload()
        digest = INVENTORY.inventory_sha256()

        INVENTORY.require_pinned_methods(
            INVENTORY.REQUIRED_METHOD_IDS,
            "test inventory",
        )
        INVENTORY.require_inventory_binding(payload, digest, "test binding")

        reordered = (
            INVENTORY.REQUIRED_METHOD_IDS[1],
            INVENTORY.REQUIRED_METHOD_IDS[0],
            *INVENTORY.REQUIRED_METHOD_IDS[2:],
        )
        with self.assertRaisesRegex(ValueError, "exact order"):
            INVENTORY.require_pinned_methods(reordered, "test inventory")

        with self.assertRaisesRegex(ValueError, "report inventory"):
            INVENTORY.require_report_methods(reordered, "test inventory")

        with self.assertRaisesRegex(ValueError, "differs"):
            INVENTORY.require_inventory_binding(payload, "0" * 64, "test binding")

    def test_inventory_guards_reject_stringy_non_strings(self) -> None:
        pinned_methods = list(INVENTORY.REQUIRED_METHOD_IDS)
        pinned_methods[0] = Stringy(INVENTORY.REQUIRED_METHOD_IDS[0])
        with self.assertRaisesRegex(ValueError, "exact order"):
            INVENTORY.require_pinned_methods(pinned_methods, "test inventory")

        report_methods = list(INVENTORY.REPORT_METHOD_IDS)
        report_methods[0] = Stringy(INVENTORY.REPORT_METHOD_IDS[0])
        with self.assertRaisesRegex(ValueError, "exact order"):
            INVENTORY.require_report_methods(report_methods, "report inventory")

        payload = INVENTORY.inventory_payload()
        with self.assertRaisesRegex(ValueError, "differs"):
            INVENTORY.require_inventory_binding(
                payload,
                Stringy(INVENTORY.inventory_sha256()),
                "test binding",
            )

    def test_inventory_binding_requires_exact_lowercase_digest(self) -> None:
        payload = INVENTORY.inventory_payload()
        with self.assertRaisesRegex(ValueError, "differs"):
            INVENTORY.require_inventory_binding(
                payload,
                INVENTORY.inventory_sha256().upper(),
                "test binding",
            )

    def test_inventory_binding_requires_exact_string_inventory_id(self) -> None:
        payload = INVENTORY.inventory_payload()
        payload["inventory_id"] = Stringy(INVENTORY.INVENTORY_ID)

        with self.assertRaisesRegex(ValueError, "inventory_id"):
            INVENTORY.require_inventory_binding(
                payload,
                INVENTORY.inventory_sha256(),
                "test binding",
                inventory_id=None,
            )

    def test_hcc1395_known_answer_inventory_is_distinct_and_exact(self) -> None:
        inventory_id = INVENTORY.HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID
        methods = INVENTORY.HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS
        payload = INVENTORY.inventory_payload(inventory_id)
        digest = INVENTORY.inventory_sha256(inventory_id)

        self.assertEqual(payload["inventory_id"], "hcc1395_wgs_known_answer_v1")
        self.assertEqual(tuple(payload["ordered_method_ids"]), methods)
        self.assertEqual(methods[0], "deterministic_full_wgs")
        self.assertEqual(methods[1], "rosalind_hcc1395_wgs")
        self.assertNotIn("rosalind_diana_wgs", methods)
        self.assertNotEqual(digest, INVENTORY.inventory_sha256())

        INVENTORY.require_pinned_methods(methods, "HCC inventory", inventory_id)
        INVENTORY.require_inventory_binding(
            payload,
            digest,
            "HCC inventory binding",
            inventory_id,
        )
        with self.assertRaisesRegex(ValueError, "hcc1395_wgs_known_answer_v1"):
            INVENTORY.require_pinned_methods(
                INVENTORY.REQUIRED_METHOD_IDS,
                "HCC inventory",
                inventory_id,
            )

    def test_unknown_inventory_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown HRD report inventory"):
            INVENTORY.inventory_payload("unknown_inventory")

    def test_source_report_paths_follow_pinned_method_order(self) -> None:
        root = Path("/repo")

        packet_dirs = INVENTORY.source_report_packet_dirs(root, "run-20260718")
        manifest_paths = INVENTORY.source_report_manifest_paths(root, "run-20260718")

        self.assertEqual(tuple(packet_dirs), INVENTORY.REQUIRED_METHOD_IDS)
        self.assertEqual(
            packet_dirs["deterministic_full_wgs"],
            root / ".codex-tmp/hrd-reports/deterministic-full/report",
        )
        self.assertEqual(
            packet_dirs["rosalind_diana_wgs"],
            root / "results/rosalind_hrd/diana_wgs/run-20260718",
        )
        self.assertEqual(
            packet_dirs["sequenza_scarhrd"],
            root / ".codex-tmp/hrd-reports/crosschecks/sequenza_scarhrd",
        )
        self.assertEqual(
            packet_dirs["sigprofiler_sbs3"],
            root / ".codex-tmp/hrd-reports/crosschecks/sigprofiler_sbs3",
        )
        for method_id, directory in INVENTORY.BLOCKED_CROSSCHECK_REPORT_DIRS.items():
            self.assertEqual(
                packet_dirs[method_id],
                root / ".codex-tmp/hrd-reports/blocked-crosschecks" / directory,
            )
        self.assertEqual(
            manifest_paths,
            {method_id: packet_dir / "report_manifest.json" for method_id, packet_dir in packet_dirs.items()},
        )

    def test_source_report_paths_accept_executable_route_overrides(self) -> None:
        root = Path("/repo")

        packet_dirs = INVENTORY.source_report_packet_dirs(
            root,
            "run-20260718",
            sigprofiler_report_dir=Path("/tmp/sigprofiler"),
            sequenza_report_dir=Path("/tmp/sequenza"),
        )

        self.assertEqual(
            packet_dirs["sequenza_scarhrd"],
            Path("/tmp/sequenza"),
        )
        self.assertEqual(
            packet_dirs["sigprofiler_sbs3"],
            Path("/tmp/sigprofiler"),
        )

    def test_source_report_paths_accept_fast_packet_overrides(self) -> None:
        root = Path("/repo")

        packet_dirs = INVENTORY.source_report_packet_dirs(
            root,
            "run-20260718",
            deterministic_report_dir=Path("/fast/deterministic"),
            rosalind_report_dir=Path("/fast/rosalind"),
            blocked_crosscheck_root=Path("/fast/blocked"),
        )
        manifest_paths = INVENTORY.source_report_manifest_paths(
            root,
            "run-20260718",
            deterministic_report_dir=Path("/fast/deterministic"),
            rosalind_report_dir=Path("/fast/rosalind"),
            blocked_crosscheck_root=Path("/fast/blocked"),
        )

        self.assertEqual(tuple(packet_dirs), INVENTORY.REQUIRED_METHOD_IDS)
        self.assertEqual(packet_dirs["deterministic_full_wgs"], Path("/fast/deterministic"))
        self.assertEqual(packet_dirs["rosalind_diana_wgs"], Path("/fast/rosalind"))
        self.assertEqual(
            packet_dirs["facets_scarhrd_blocked"],
            Path("/fast/blocked/facets_scarhrd_blocked"),
        )
        self.assertEqual(
            manifest_paths["hrdetect_blocked"],
            Path("/fast/blocked/hrdetect_blocked/report_manifest.json"),
        )


if __name__ == "__main__":
    unittest.main()
