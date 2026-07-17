from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

INVENTORY_SCRIPT = SCRIPT_DIR / "hrd_report_inventory.py"
INVENTORY_SPEC = importlib.util.spec_from_file_location(
    "hrd_report_inventory", INVENTORY_SCRIPT
)
assert INVENTORY_SPEC and INVENTORY_SPEC.loader
INVENTORY = importlib.util.module_from_spec(INVENTORY_SPEC)
INVENTORY_SPEC.loader.exec_module(INVENTORY)

PUBLISH_SCRIPT = SCRIPT_DIR / "publish_reviewed_public_report.py"
PUBLISH_SPEC = importlib.util.spec_from_file_location(
    "publish_reviewed_public_report", PUBLISH_SCRIPT
)
assert PUBLISH_SPEC and PUBLISH_SPEC.loader
PUBLISH = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(PUBLISH)

BLOCKED_SCRIPT = SCRIPT_DIR / "generate_blocked_hrd_crosscheck_reports.py"
BLOCKED_SPEC = importlib.util.spec_from_file_location(
    "generate_blocked_hrd_crosscheck_reports", BLOCKED_SCRIPT
)
assert BLOCKED_SPEC and BLOCKED_SPEC.loader
BLOCKED = importlib.util.module_from_spec(BLOCKED_SPEC)
BLOCKED_SPEC.loader.exec_module(BLOCKED)

STAGE_SCRIPT = SCRIPT_DIR / "stage_hrd_crosscheck_report.py"
STAGE_SPEC = importlib.util.spec_from_file_location(
    "stage_hrd_crosscheck_report", STAGE_SCRIPT
)
assert STAGE_SPEC and STAGE_SPEC.loader
STAGE = importlib.util.module_from_spec(STAGE_SPEC)
STAGE_SPEC.loader.exec_module(STAGE)


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
            {
                method["method_id"]: method["directory"]
                for method in BLOCKED.METHODS
            },
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


if __name__ == "__main__":
    unittest.main()
