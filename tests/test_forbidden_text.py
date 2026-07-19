from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import publish_private_report as PRIVATE_PUBLISHER  # noqa: E402
import publish_reviewed_public_report as PUBLIC_PUBLISHER  # noqa: E402
import render_ai_synthesis_runbook as AI_RUNBOOK  # noqa: E402
import render_post_success_runbook as POST_SUCCESS_RUNBOOK  # noqa: E402
import render_source_report_freeze_runbook as SOURCE_FREEZE_RUNBOOK  # noqa: E402
import validate_phase3_fast_report_packets as PHASE3_PACKET_VALIDATOR  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "forbidden_text", SCRIPT_DIR / "forbidden_text.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ForbiddenTextTests(unittest.TestCase):
    def test_static_forbidden_tokens_have_one_source_of_truth(self) -> None:
        self.assertEqual(
            MODULE.DEFAULT_FORBIDDEN_TOKENS,
            PUBLIC_PUBLISHER.DEFAULT_FORBIDDEN_TOKENS,
        )
        self.assertEqual(
            MODULE.DEFAULT_FORBIDDEN_TOKENS,
            PRIVATE_PUBLISHER.DEFAULT_FORBIDDEN_TOKENS,
        )
        self.assertEqual(MODULE.DEFAULT_FORBIDDEN_TOKENS, AI_RUNBOOK.FORBIDDEN_TOKENS)
        self.assertEqual(
            MODULE.DEFAULT_FORBIDDEN_TOKENS,
            PHASE3_PACKET_VALIDATOR.FORBIDDEN_TOKENS,
        )
        self.assertEqual(
            POST_SUCCESS_RUNBOOK.forbidden_flags(),
            AI_RUNBOOK.forbidden_flags(),
        )
        self.assertEqual(
            SOURCE_FREEZE_RUNBOOK.forbidden_flags(),
            AI_RUNBOOK.forbidden_flags(),
        )

    def test_normalized_scan_text_decodes_identifier_obfuscation(self) -> None:
        for value in (
            "p&#101;rsonalis",
            "p%65rsonalis",
            "p%2565rsonalis",
            "p\u200dersonalis",
        ):
            with self.subTest(value=value):
                self.assertEqual(MODULE.normalized_scan_text(value), "personalis")

    def test_forbidden_token_fingerprints_are_stable_and_normalized(self) -> None:
        expected = hashlib.sha256(
            b"diana-ai-review-forbidden-v1\0personalis"
        ).hexdigest()

        self.assertEqual(
            MODULE.forbidden_token_fingerprints(
                ["p&#101;rsonalis", "DRF-PSN49561"]
            ),
            sorted(
                [
                    expected,
                    hashlib.sha256(
                        b"diana-ai-review-forbidden-v1\0drf-psn49561"
                    ).hexdigest(),
                ]
            ),
        )

    def test_unauthorized_hrd_classification_scans_normalized_text(self) -> None:
        for value in (
            "This profile is HRD-positive.",
            "This profile is H&#82;D-positive.",
            "This profile is H%52D-positive.",
            "The case is homologous recombination deficient.",
        ):
            with self.subTest(value=value):
                self.assertTrue(MODULE.has_unauthorized_hrd_classification(value))

        self.assertFalse(
            MODULE.has_unauthorized_hrd_classification(
                "Authorized HRD state: `no_call`."
            )
        )

    def test_refuses_forbidden_token_file_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-parent"
            real_existing = real_parent / "existing"
            real_existing.mkdir(parents=True)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            tokens = linked_parent / "existing" / "forbidden_tokens.json"
            (real_existing / "forbidden_tokens.json").write_text(
                '["DirectIdentifier"]\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "forbidden-token file parent may not be a symlink",
            ):
                MODULE.merge_forbidden_tokens([], files=[tokens])


if __name__ == "__main__":
    unittest.main()
