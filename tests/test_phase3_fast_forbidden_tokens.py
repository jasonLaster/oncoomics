from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import validate_phase3_fast_forbidden_tokens as command
from diana_omics.commands.phase3_wgs.render_phase3_fast_input_manifest import ManifestError


class Phase3FastForbiddenTokenTests(unittest.TestCase):
    def test_normalizes_forbidden_token_array(self) -> None:
        self.assertEqual(
            ["E019", "personalis"],
            command.normalize_forbidden_tokens(json.dumps([" personalis ", "E019", "E019"])),
        )

    def test_rejects_missing_malformed_or_empty_inventory(self) -> None:
        for raw in (None, "", " ", "{", "{}", "[]", '[""]', '["E019", 1]', '["E"]', '["E019\\nDRF"]'):
            with self.subTest(raw=raw):
                with self.assertRaises(ManifestError):
                    command.normalize_forbidden_tokens(raw)

    def test_main_writes_canonical_json_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "forbidden_tokens.json"

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_FORBIDDEN_TOKENS_JSON_B64": base64.b64encode(
                        json.dumps(["DRF-PSN49561", " E019 "]).encode()
                    ).decode(),
                    "PHASE3_WGS_FAST_FORBIDDEN_TOKENS_OUTPUT": str(output),
                },
            ):
                command.main()

            self.assertEqual(["DRF-PSN49561", "E019"], json.loads(output.read_text(encoding="utf-8")))

    def test_rejects_malformed_base64_environment_value(self) -> None:
        with patch.dict("os.environ", {"PHASE3_WGS_FAST_FORBIDDEN_TOKENS_JSON_B64": "not base64!"}):
            with self.assertRaisesRegex(ManifestError, "Base64-encoded UTF-8 JSON"):
                command.raw_forbidden_tokens_from_environment()


if __name__ == "__main__":
    unittest.main()
