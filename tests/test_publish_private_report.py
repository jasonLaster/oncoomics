from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SCRIPT = SCRIPT_DIR / "publish_private_report.py"
SPEC = importlib.util.spec_from_file_location("publish_private_report", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checksum(value: bytes) -> str:
    return base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")


class Fixture:
    def __init__(self, root: Path, method_id: str = "rosalind_diana_wgs") -> None:
        self.root = root
        self.method_id = method_id
        self.packet = root / "packet"
        self.packet.mkdir()
        self.receipt_path = root / "private-publication.json"
        self._write_packet()

    def _write_packet(self) -> None:
        for name in MODULE.METHOD_CONTRACTS[self.method_id]["files"]:
            path = self.packet / name
            if name == "report_manifest.json":
                continue
            if name == "report.md":
                path.write_text("# Reviewed HRD evidence\n\nOverall HRD remains no_call.\n")
            elif name.endswith(".json"):
                path.write_text(json.dumps({"status": "partial_evidence"}) + "\n")
            elif name.endswith(".csv"):
                path.write_text("field,value\nstatus,partial_evidence\n")
            else:
                path.write_text("# Reviewed support\n")

        support = {
            name: digest((self.packet / name).read_bytes())
            for name in MODULE.METHOD_CONTRACTS[self.method_id]["files"]
            if name not in {"report.md", "report_manifest.json"}
        }
        manifest = {
            "schema_version": 1,
            "method_id": self.method_id,
            "report_kind": MODULE.METHOD_CONTRACTS[self.method_id]["report_kind"],
            "evidence_status": "partial_evidence",
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "report_sha256": digest((self.packet / "report.md").read_bytes()),
            "support_sha256": support,
            "source_sha256": {"frozen_input": "a" * 64},
            "review_summary": {
                "overall": {
                    "evidence_status": "partial_evidence",
                    "authorized_hrd_state": "no_call",
                }
            },
        }
        (self.packet / "report_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    def mutate_manifest(self, **updates: object) -> None:
        path = self.packet / "report_manifest.json"
        value = json.loads(path.read_text())
        value.update(updates)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    def mutate_support_file(self, relative: str, text: str) -> None:
        path = self.packet / relative
        path.write_text(text)
        manifest_path = self.packet / "report_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["support_sha256"][relative] = digest(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    def args(
        self,
        *,
        apply: bool = False,
        dry_run_receipt: Path | None = None,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            packet_dir=self.packet,
            method_id=self.method_id,
            destination_prefix="",
            receipt_output=self.receipt_path,
            forbidden_token=[],
            forbidden_tokens_file=[],
            dry_run_receipt=dry_run_receipt,
            region=MODULE.REGION,
            apply=apply,
        )


class FakeAws:
    def __init__(self) -> None:
        self.public: dict[str, dict[str, object]] = {}
        self.put_calls: list[list[str]] = []
        self.preexisting_history: list[dict[str, object]] = []
        self.literal_null_version = False
        self.boolean_version = False
        self.wrong_checksum = False
        self.boolean_content_length = False

    @staticmethod
    def value(arguments: list[str], name: str) -> str:
        return arguments[arguments.index(name) + 1]

    def aws_json(self, arguments: list[str], region: str) -> dict[str, object]:
        if region != MODULE.REGION:
            raise AssertionError(f"wrong region: {region}")
        operation = tuple(arguments[:2])
        if operation == ("s3api", "get-bucket-versioning"):
            return {"Status": "Enabled"}
        if operation == ("s3api", "list-object-versions"):
            if self.preexisting_history:
                return {"Versions": self.preexisting_history, "DeleteMarkers": []}
            prefix = self.value(arguments, "--prefix")
            return {
                "Versions": [
                    {
                        "Key": key,
                        "VersionId": row["VersionId"],
                        "IsLatest": True,
                        "Size": row["ContentLength"],
                    }
                    for key, row in sorted(self.public.items())
                    if key.startswith(prefix)
                ],
                "DeleteMarkers": [],
            }
        if operation == ("s3api", "put-object"):
            self.put_calls.append(list(arguments))
            key = self.value(arguments, "--key")
            payload = Path(self.value(arguments, "--body")).read_bytes()
            observed_checksum = checksum(b"different" if self.wrong_checksum else payload)
            if self.value(arguments, "--checksum-sha256") != checksum(payload):
                raise AssertionError("unexpected put-object checksum")
            self.public[key] = {
                "VersionId": (
                    True
                    if self.boolean_version
                    else "null"
                    if self.literal_null_version
                    else f"private-v{len(self.public) + 1}"
                ),
                "ContentLength": len(payload),
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": observed_checksum,
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": MODULE.PRIVATE_KMS_KEY_ARN,
                "Metadata": json.loads(self.value(arguments, "--metadata")),
            }
            return {"VersionId": self.public[key]["VersionId"]}
        if operation == ("s3api", "head-object"):
            return dict(self.public[self.value(arguments, "--key")])
        raise AssertionError(f"unexpected AWS call: {arguments}")

    def head_object(
        self,
        bucket: str,
        key: str,
        region: str,
        version_id: str = "",
    ) -> dict[str, object]:
        if bucket != MODULE.PRIVATE_BUCKET:
            raise AssertionError(f"wrong bucket: {bucket}")
        if region != MODULE.REGION:
            raise AssertionError(f"wrong region: {region}")
        metadata = dict(self.public[key])
        if self.boolean_content_length:
            metadata["ContentLength"] = True
        return metadata

    def version_history(
        self,
        bucket: str,
        prefix: str,
        region: str,
    ) -> list[dict[str, object]]:
        if bucket != MODULE.PRIVATE_BUCKET:
            raise AssertionError(f"wrong bucket: {bucket}")
        if region != MODULE.REGION:
            raise AssertionError(f"wrong region: {region}")
        if self.preexisting_history:
            return self.preexisting_history
        return [
            {
                "history_kind": "version",
                "Key": key,
                "VersionId": row["VersionId"],
                "IsLatest": True,
                "Size": row["ContentLength"],
            }
            for key, row in sorted(self.public.items())
            if key.startswith(prefix)
        ]


class PublishPrivateReportTests(unittest.TestCase):
    def test_schema_versions_are_exact_json_integers(self) -> None:
        for value in (True, 1.0, "1", 2, None):
            with self.subTest(value=value):
                self.assertFalse(
                    MODULE.exact_schema_version({"schema_version": value})
                )

        self.assertTrue(MODULE.exact_schema_version({"schema_version": 1}))

    def test_schema_guards_use_exact_integer_helper(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(SCRIPT))

        raw_comparisons = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "schema_version" not in segment:
                continue
            raw_comparisons.append(f"{node.lineno}: {segment}")

        self.assertEqual(raw_comparisons, [])

    def write_dry_run_receipt(self, fixture: Fixture) -> Path:
        output = fixture.root / "private-publication.dry.json"
        args = fixture.args()
        args.receipt_output = output
        with mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")):
            MODULE.run(args)
        return output

    def execute(
        self,
        fixture: Fixture,
        fake: FakeAws,
        *,
        apply: bool = False,
        dry_run_receipt: Path | None = None,
    ) -> dict[str, object]:
        with (
            mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json),
            mock.patch.object(MODULE, "head_object", side_effect=fake.head_object),
            mock.patch.object(MODULE, "version_history", side_effect=fake.version_history),
        ):
            return MODULE.run(
                fixture.args(apply=apply, dry_run_receipt=dry_run_receipt)
            )

    def test_dry_run_validates_allowlisted_packet_without_uploading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            with mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")):
                result = MODULE.run(fixture.args())

            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["object_count"], 8)
            self.assertEqual(result["passed_count"], 0)
            self.assertEqual(fixture.receipt_path.stat().st_mode & 0o777, 0o600)

    def test_apply_uploads_exact_kms_objects_and_writes_public_compatible_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws()
            dry_run_receipt = self.write_dry_run_receipt(fixture)
            result = self.execute(
                fixture,
                fake,
                apply=True,
                dry_run_receipt=dry_run_receipt,
            )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(
                result["dry_run_receipt"]["path"],
                str(dry_run_receipt.resolve()),
            )
            self.assertEqual(
                result["dry_run_receipt"]["packet_revision"],
                result["packet_revision"],
            )
            self.assertEqual(result["passed_count"], 8)
            self.assertEqual(len(fake.put_calls), 8)
            for call in fake.put_calls:
                self.assertEqual(FakeAws.value(call, "--if-none-match"), "*")
                self.assertEqual(FakeAws.value(call, "--server-side-encryption"), "aws:kms")
                self.assertEqual(FakeAws.value(call, "--ssekms-key-id"), MODULE.PRIVATE_KMS_KEY_ARN)
                self.assertEqual(FakeAws.value(call, "--checksum-algorithm"), "SHA256")
                body = Path(FakeAws.value(call, "--body"))
                self.assertEqual(FakeAws.value(call, "--checksum-sha256"), checksum(body.read_bytes()))

            receipt = json.loads(fixture.receipt_path.read_text())
            reviewed_public = importlib.util.spec_from_file_location(
                "publish_reviewed_public_report",
                SCRIPT_DIR / "publish_reviewed_public_report.py",
            )
            assert reviewed_public and reviewed_public.loader
            public_module = importlib.util.module_from_spec(reviewed_public)
            reviewed_public.loader.exec_module(public_module)
            _, expected, rows = public_module.validate_private_receipt(fixture.receipt_path, fixture.method_id)
            self.assertEqual(tuple(receipt["expected_files"]), expected)
            self.assertEqual(len(rows), 8)

    def test_apply_dry_run_receipt_digest_is_bound_to_validated_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws()
            dry_run_receipt = self.write_dry_run_receipt(fixture)
            original_dry_run_sha256 = digest(dry_run_receipt.read_bytes())
            real_load = MODULE.load_json_with_sha256
            mutated = False

            def mutate_after_parse(
                path: Path,
                label: str,
            ) -> tuple[dict[str, object], str]:
                nonlocal mutated
                result = real_load(path, label)
                if label == "private report dry-run receipt" and not mutated:
                    dry_run_receipt.write_text(
                        '{"changed_after_validated_read": true}\n',
                        encoding="utf-8",
                    )
                    mutated = True
                return result

            with mock.patch.object(
                MODULE,
                "load_json_with_sha256",
                side_effect=mutate_after_parse,
            ):
                result = self.execute(
                    fixture,
                    fake,
                    apply=True,
                    dry_run_receipt=dry_run_receipt,
                )

            self.assertTrue(mutated)
            self.assertEqual(
                result["dry_run_receipt"]["sha256"],
                original_dry_run_sha256,
            )

    def test_rejects_source_hash_for_packet_local_support_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary), "comparative_hrd_synthesis")
            manifest_path = fixture.packet / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_sha256"] = {"agreement_disagreement.csv": "a" * 64}
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "source hash differs"):
                MODULE.validate_packet_dir(
                    fixture.packet,
                    "comparative_hrd_synthesis",
                    ("E019", "DRF-", "Personalis", "Echo"),
                )

    def test_rejects_extra_file_or_forbidden_token_before_aws(self) -> None:
        for mutate, message in (
            (lambda fixture: (fixture.packet / "raw.fastq.gz").write_text("raw\n"), "inventory"),
            (
                lambda fixture: (fixture.packet / "report.md").write_text("personalis\n"),
                "forbidden identifier",
            ),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                mutate(fixture)
                with (
                    self.assertRaisesRegex(ValueError, message),
                    mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
                ):
                    MODULE.run(fixture.args())

    def test_rejects_packet_dir_below_symlinked_parent_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = Fixture(root)
            real_parent = root / "real-packets"
            real_parent.mkdir()
            moved_packet = real_parent / "packet"
            fixture.packet.rename(moved_packet)
            linked_parent = root / "linked-packets"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            fixture.packet = linked_parent / "packet"

            with (
                self.assertRaisesRegex(
                    ValueError, "packet directory parent may not be a symlink"
                ),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(fixture.args())

            self.assertFalse(fixture.receipt_path.exists())

    def test_rejects_unauthorized_hrd_classification_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            report = fixture.packet / "report.md"
            report.write_text("This profile is HRD-positive.\n", encoding="utf-8")
            fixture.mutate_manifest(report_sha256=digest(report.read_bytes()))

            with (
                self.assertRaisesRegex(ValueError, "unauthorized HRD classification"),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(fixture.args())

    def test_rejects_forbidden_token_from_file_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = Fixture(root)
            tokens = root / "forbidden_tokens.json"
            tokens.write_text('["Unit-Run-Private-Token"]\n')
            report = fixture.packet / "report.md"
            report.write_text("No-call report with Unit-Run-Private-Token.\n")
            fixture.mutate_manifest(report_sha256=digest(report.read_bytes()))
            args = fixture.args()
            args.forbidden_tokens_file = [tokens]

            with (
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
                self.assertRaisesRegex(ValueError, "forbidden identifier token"),
            ):
                MODULE.run(args)

    def test_rejects_unauthorized_manifest_classification_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            manifest = json.loads((fixture.packet / "report_manifest.json").read_text(encoding="utf-8"))
            manifest["review_summary"]["overall"]["statement"] = "This profile is HRD-positive."
            (fixture.packet / "report_manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with (
                self.assertRaisesRegex(ValueError, "unauthorized HRD classification"),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(fixture.args())

    def test_manifest_kind_must_match_method_before_aws(self) -> None:
        cases = {
            "missing": None,
            "wrong": "comparative_synthesis",
        }
        for label, report_kind in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                manifest_path = fixture.packet / "report_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if report_kind is None:
                    del manifest["report_kind"]
                else:
                    manifest["report_kind"] = report_kind
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with (
                    self.assertRaisesRegex(
                        ValueError,
                        "report manifest report_kind is not exact",
                    ),
                    mock.patch.object(
                        MODULE,
                        "aws_json",
                        side_effect=AssertionError("AWS called"),
                    ),
                ):
                    MODULE.run(fixture.args())

    def test_rejects_encoded_forbidden_token_before_aws(self) -> None:
        for encoded in (
            "p&#101;rsonalis\n",
            "p%65rsonalis\n",
            "p\u200dersonalis\n",
        ):
            with self.subTest(encoded=encoded), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                (fixture.packet / "report.md").write_text(encoded)

                with (
                    self.assertRaisesRegex(ValueError, "forbidden identifier"),
                    mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
                ):
                    MODULE.run(fixture.args())

    def test_manifest_cannot_promote_no_call_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.mutate_manifest(
                authorized_hrd_state="positive",
                classification_authorized=True,
            )
            with (
                self.assertRaisesRegex(ValueError, "no-call contract"),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(fixture.args())

    def test_manifest_cannot_mark_no_call_qc_as_passed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.mutate_manifest(classification_qc_status="passed")

            with (
                self.assertRaisesRegex(ValueError, "no-call contract"),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(fixture.args())

    def test_apply_rejects_preexisting_destination_history_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws()
            fake.preexisting_history = [{"Key": "old", "VersionId": "old", "IsLatest": True, "Size": 1}]
            dry_run_receipt = self.write_dry_run_receipt(fixture)

            with self.assertRaisesRegex(ValueError, "prior history"):
                self.execute(
                    fixture,
                    fake,
                    apply=True,
                    dry_run_receipt=dry_run_receipt,
                )

            self.assertEqual(fake.put_calls, [])
            self.assertEqual(json.loads(fixture.receipt_path.read_text())["status"], "failed")

    def test_apply_rejects_null_destination_version(self) -> None:
        for flag in ("literal_null_version", "boolean_version"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                fake = FakeAws()
                setattr(fake, flag, True)
                dry_run_receipt = self.write_dry_run_receipt(fixture)

                with self.assertRaisesRegex(ValueError, "non-null VersionId"):
                    self.execute(
                        fixture,
                        fake,
                        apply=True,
                        dry_run_receipt=dry_run_receipt,
                    )

                self.assertEqual(
                    json.loads(fixture.receipt_path.read_text())["status"],
                    "failed",
                )

    def test_apply_rejects_destination_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws()
            fake.wrong_checksum = True
            dry_run_receipt = self.write_dry_run_receipt(fixture)

            with self.assertRaisesRegex(ValueError, "destination verification failed"):
                self.execute(
                    fixture,
                    fake,
                    apply=True,
                    dry_run_receipt=dry_run_receipt,
                )

    def test_apply_rejects_boolean_destination_content_length(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws()
            fake.boolean_content_length = True
            dry_run_receipt = self.write_dry_run_receipt(fixture)

            with self.assertRaisesRegex(
                ValueError,
                "private destination verification failed",
            ):
                self.execute(
                    fixture,
                    fake,
                    apply=True,
                    dry_run_receipt=dry_run_receipt,
                )

            self.assertEqual(json.loads(fixture.receipt_path.read_text())["status"], "failed")

    def test_private_destination_object_checks_must_be_exact(self) -> None:
        cases = (
            {"version_id": True},
            {
                **MODULE.PRIVATE_RECEIPT_OBJECT_CHECKS,
                "unexpected_late_check": True,
            },
        )

        for checks in cases:
            with self.subTest(checks=checks):
                with self.assertRaisesRegex(
                    ValueError,
                    "private destination verification failed",
                ):
                    MODULE.require_private_object_checks_exact(
                        checks,
                        "report.md",
                    )

    def test_apply_rejects_outdated_destination_object_check_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws()
            dry_run_receipt = self.write_dry_run_receipt(fixture)

            with (
                mock.patch.object(
                    MODULE,
                    "PRIVATE_RECEIPT_OBJECT_CHECKS",
                    {
                        **MODULE.PRIVATE_RECEIPT_OBJECT_CHECKS,
                        "unexpected_late_check": True,
                    },
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "private destination verification failed",
                ),
            ):
                self.execute(
                    fixture,
                    fake,
                    apply=True,
                    dry_run_receipt=dry_run_receipt,
                )

    def test_apply_requires_matching_dry_run_receipt_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            with (
                self.assertRaisesRegex(ValueError, "requires --dry-run-receipt"),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(fixture.args(apply=True))

            dry_run_receipt = self.write_dry_run_receipt(fixture)
            fixture.mutate_support_file("next_actions.md", "# Changed no-call next actions\n")

            with (
                self.assertRaisesRegex(ValueError, "does not match this apply"),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_run_receipt))

    def test_apply_rejects_failed_or_redirected_dry_run_receipts_before_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = Fixture(root)
            dry_run_receipt = self.write_dry_run_receipt(fixture)
            failed = json.loads(dry_run_receipt.read_text())
            failed["status"] = "failed"
            dry_run_receipt.write_text(json.dumps(failed, indent=2, sort_keys=True) + "\n")

            with (
                self.assertRaisesRegex(ValueError, "contract is malformed"),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_run_receipt))

            real_receipt = root / "real-dry-run.json"
            dry_run_receipt.replace(real_receipt)
            dry_run_receipt.symlink_to(real_receipt)

            with (
                self.assertRaisesRegex(ValueError, "must be a real file"),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_run_receipt))

    def test_apply_rejects_dry_run_receipt_with_duplicate_json_object_names_before_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            dry_run_receipt = self.write_dry_run_receipt(fixture)
            payload = json.loads(dry_run_receipt.read_text(encoding="utf-8"))
            text = json.dumps(payload, indent=2, sort_keys=True)
            status = f'  "status": "{payload["status"]}"'
            self.assertEqual(text.count(status), 1)
            text = text.replace(status, f'  "status": "failed",\n{status}', 1)
            dry_run_receipt.write_text(text + "\n", encoding="utf-8")

            with (
                self.assertRaisesRegex(
                    ValueError,
                    (
                        "duplicate JSON object name in "
                        "private report dry-run receipt: status"
                    ),
                ),
                mock.patch.object(
                    MODULE, "aws_json", side_effect=AssertionError("AWS called")
                ),
            ):
                MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_run_receipt))

            self.assertFalse(fixture.receipt_path.exists())

    def test_apply_rejects_dry_run_receipt_with_stale_packet_checks_before_aws(
        self,
    ) -> None:
        cases = {
            "extra": lambda checks: checks.__setitem__("unexpected_late_check", False),
            "missing_report_kind": lambda checks: checks.pop(
                "packet_report_kind_exact",
            ),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                dry_run_receipt = self.write_dry_run_receipt(fixture)
                payload = json.loads(dry_run_receipt.read_text(encoding="utf-8"))
                mutate(payload["checks"])
                dry_run_receipt.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with (
                    self.assertRaisesRegex(ValueError, "did not pass packet checks"),
                    mock.patch.object(
                        MODULE,
                        "aws_json",
                        side_effect=AssertionError("AWS called"),
                    ),
                ):
                    MODULE.run(
                        fixture.args(
                            apply=True,
                            dry_run_receipt=dry_run_receipt,
                        )
                    )

                self.assertFalse(fixture.receipt_path.exists())

    def test_apply_rejects_dry_run_receipt_with_stale_extra_metadata_before_aws(
        self,
    ) -> None:
        cases = (
            (
                "extra top-level",
                lambda payload: payload.__setitem__(
                    "stale_packet_revision",
                    "0" * 64,
                ),
            ),
            (
                "float schema_version",
                lambda payload: payload.__setitem__("schema_version", 1.0),
            ),
        )

        for label, mutate in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                dry_run_receipt = self.write_dry_run_receipt(fixture)
                payload = json.loads(dry_run_receipt.read_text(encoding="utf-8"))
                mutate(payload)
                dry_run_receipt.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with (
                    self.assertRaisesRegex(ValueError, "contract is malformed"),
                    mock.patch.object(
                        MODULE,
                        "aws_json",
                        side_effect=AssertionError("AWS called"),
                    ),
                ):
                    MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_run_receipt))

                self.assertFalse(fixture.receipt_path.exists())

    def test_apply_rejects_dry_run_receipt_with_non_exact_counts_before_aws(
        self,
    ) -> None:
        cases = (
            ("object_count", 8.0),
            ("object_count", "8"),
            ("passed_count", False),
            ("passed_count", 0.0),
            ("passed_count", "0"),
            ("forbidden_token_count", 4.0),
            ("forbidden_token_count", "4"),
        )

        for field, value in cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                dry_run_receipt = self.write_dry_run_receipt(fixture)
                payload = json.loads(dry_run_receipt.read_text(encoding="utf-8"))
                payload[field] = value
                dry_run_receipt.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with (
                    self.assertRaisesRegex(ValueError, "contract is malformed"),
                    mock.patch.object(
                        MODULE,
                        "aws_json",
                        side_effect=AssertionError("AWS called"),
                    ),
                ):
                    MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_run_receipt))

                self.assertFalse(fixture.receipt_path.exists())

    def test_apply_rejects_dry_run_receipt_below_symlinked_parent_before_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = Fixture(root)
            dry_run_receipt = self.write_dry_run_receipt(fixture)
            real_parent = root / "real-dry-run-receipts"
            real_parent.mkdir()
            moved_receipt = real_parent / "private-publication.dry.json"
            dry_run_receipt.rename(moved_receipt)
            linked_parent = root / "linked-dry-run-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with (
                self.assertRaisesRegex(
                    ValueError,
                    "private report dry-run receipt parent may not be a symlink",
                ),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(
                    fixture.args(
                        apply=True,
                        dry_run_receipt=linked_parent
                        / "private-publication.dry.json",
                    )
                )


if __name__ == "__main__":
    unittest.main()
