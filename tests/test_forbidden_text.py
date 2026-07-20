from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_refuses_forbidden_token_file_replaced_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tokens = root / "forbidden_tokens.json"
            target = root / "redirected_tokens.json"
            tokens.write_text('["DirectIdentifier"]\n', encoding="utf-8")
            target.write_text('["RedirectedIdentifier"]\n', encoding="utf-8")
            real_require = MODULE.require_real_forbidden_token_file
            swapped = False

            def swap_leaf_after_preflight(path: Path) -> None:
                nonlocal swapped
                real_require(path)
                if path == tokens and not swapped:
                    swapped = True
                    tokens.unlink()
                    tokens.symlink_to(target)

            with mock.patch.object(
                MODULE,
                "require_real_forbidden_token_file",
                side_effect=swap_leaf_after_preflight,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "forbidden-token file changed during read",
                ):
                    MODULE.merge_forbidden_tokens([], files=[tokens])

    def test_file_forbidden_tokens_share_json_normalization_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tokens = root / "forbidden_tokens.json"
            tokens.write_text(
                '["DirectIdentifier", "personalis", "DirectIdentifier"]\n',
                encoding="utf-8",
            )

            self.assertEqual(
                MODULE.forbidden_tokens_from_file(tokens),
                ["DirectIdentifier", "personalis"],
            )

            for value in ('["ab"]', '["personalis\\u0000"]'):
                with self.subTest(value=value):
                    tokens.write_text(value + "\n", encoding="utf-8")

                    with self.assertRaisesRegex(
                        ValueError,
                        "forbidden-token file must contain a valid non-empty JSON string array",
                    ):
                        MODULE.forbidden_tokens_from_file(tokens)

    def test_explicit_forbidden_tokens_share_normalization_policy(self) -> None:
        self.assertEqual(
            MODULE.merge_forbidden_tokens(
                [" DirectIdentifier ", "personalis", "DirectIdentifier"]
            ),
            ("DirectIdentifier", "personalis"),
        )

        cases = (
            ("blank", ["  "], "forbidden token\\[0\\] must be a non-empty string"),
            ("short", ["ab"], "forbidden token\\[0\\] must be at least 3 characters"),
            (
                "control",
                ["personalis\u0000"],
                "forbidden token\\[0\\] must not contain control characters",
            ),
        )
        for name, tokens, message in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, message):
                    MODULE.merge_forbidden_tokens(tokens)


if __name__ == "__main__":
    unittest.main()
