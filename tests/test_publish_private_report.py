from __future__ import annotations

import argparse
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

    def args(self, *, apply: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            packet_dir=self.packet,
            method_id=self.method_id,
            destination_prefix="",
            receipt_output=self.receipt_path,
            forbidden_token=[],
            forbidden_tokens_file=[],
            region=MODULE.REGION,
            apply=apply,
        )


class FakeAws:
    def __init__(self) -> None:
        self.public: dict[str, dict[str, object]] = {}
        self.put_calls: list[list[str]] = []
        self.preexisting_history: list[dict[str, object]] = []
        self.literal_null_version = False
        self.wrong_checksum = False

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
            self.public[key] = {
                "VersionId": "null" if self.literal_null_version else f"private-v{len(self.public) + 1}",
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
        return dict(self.public[key])

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
    def execute(self, fixture: Fixture, fake: FakeAws, *, apply: bool = False) -> dict[str, object]:
        with (
            mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json),
            mock.patch.object(MODULE, "head_object", side_effect=fake.head_object),
            mock.patch.object(MODULE, "version_history", side_effect=fake.version_history),
        ):
            return MODULE.run(fixture.args(apply=apply))

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
            result = self.execute(fixture, fake, apply=True)

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["passed_count"], 8)
            self.assertEqual(len(fake.put_calls), 8)
            for call in fake.put_calls:
                self.assertEqual(FakeAws.value(call, "--if-none-match"), "*")
                self.assertEqual(FakeAws.value(call, "--server-side-encryption"), "aws:kms")
                self.assertEqual(FakeAws.value(call, "--ssekms-key-id"), MODULE.PRIVATE_KMS_KEY_ARN)
                self.assertEqual(FakeAws.value(call, "--checksum-algorithm"), "SHA256")

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

            with self.assertRaisesRegex(ValueError, "prior history"):
                self.execute(fixture, fake, apply=True)

            self.assertEqual(fake.put_calls, [])
            self.assertEqual(json.loads(fixture.receipt_path.read_text())["status"], "failed")

    def test_apply_rejects_null_destination_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws()
            fake.literal_null_version = True

            with self.assertRaisesRegex(ValueError, "non-null VersionId"):
                self.execute(fixture, fake, apply=True)

            self.assertEqual(json.loads(fixture.receipt_path.read_text())["status"], "failed")

    def test_apply_rejects_destination_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws()
            fake.wrong_checksum = True

            with self.assertRaisesRegex(ValueError, "destination verification failed"):
                self.execute(fixture, fake, apply=True)


if __name__ == "__main__":
    unittest.main()
