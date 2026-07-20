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
SCRIPT = SCRIPT_DIR / "publish_reviewed_public_report.py"
SPEC = importlib.util.spec_from_file_location("publish_reviewed_public_report", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checksum(value: bytes) -> str:
    return base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")


def report_kind_extras(method_id: str, support: dict[str, str]) -> dict[str, object]:
    report_kind = MODULE.METHOD_CONTRACTS[method_id]["report_kind"]
    if report_kind == "blocked_method":
        return {
            "alias_scope": "unit",
            "blockers": ["method not run"],
            "classification_authorization": "no_call",
            "explicit_no_patient_result": True,
            "generated_at": "2026-07-19T00:00:00+00:00",
            "intended_computation": "blocked unit cross-check",
            "interpretation_status": "blocked",
            "next_gate": "review the executable route",
            "patient_result": "not generated",
            "prerequisites": ["validated runtime"],
            "run_id": "unit",
            "source_report_binding_scope": "unit",
            "sources": [],
        }
    if report_kind == "comparative_synthesis":
        return {
            "agreement_disagreement_sha256": support.get(
                "agreement_disagreement.csv",
                "a" * 64,
            ),
            "classification_authorization": "no_call",
            "generated_at": "2026-07-19T00:00:00+00:00",
            "interpretation_status": "no_call",
            "subject_alias": MODULE.SUBJECT_ALIAS,
        }
    if report_kind == "executable_crosscheck_method":
        return {"route": {"status": "not_run"}}
    return {}


class Fixture:
    def __init__(self, root: Path, method_id: str = "rosalind_diana_wgs") -> None:
        self.root = root
        self.method_id = method_id
        self.files = tuple(sorted(MODULE.METHOD_CONTRACTS[method_id]["files"]))
        self.private_base_prefix = (
            f"runs/{MODULE.SUBJECT_ALIAS}/{MODULE.RUN_ID}/reports/{method_id}/"
        )
        self.packet = root / "packet"
        self.packet.mkdir()
        self.receipt_path = root / "private-publication.json"
        self.output_path = root / "public-publication.json"
        self.payloads: dict[str, bytes] = {}
        self._write_packet()
        self.rebuild_receipt()

    def _write_packet(self) -> None:
        for name in self.files:
            if name == "report_manifest.json":
                continue
            path = self.packet / name
            if name == "report.md":
                path.write_text("# Reviewed HRD evidence\n\nOverall HRD remains no_call.\n")
            elif name.endswith(".json"):
                path.write_text(json.dumps({"status": "partial_evidence", "file": name}) + "\n")
            elif name.endswith(".csv"):
                path.write_text("field,value\nstatus,partial_evidence\n")
            else:
                path.write_text("# Reviewed support\n")
        support = {
            name: digest((self.packet / name).read_bytes())
            for name in self.files
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
            **report_kind_extras(self.method_id, support),
        }
        (self.packet / "report_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )

    def rebuild_receipt(self) -> None:
        self.payloads = {name: (self.packet / name).read_bytes() for name in self.files}
        rows = []
        for index, name in enumerate(self.files, 1):
            payload = self.payloads[name]
            sha = digest(payload)
            rows.append(
                {
                    "relative_path": name,
                    "version_id": f"private-version-{index}",
                    "bytes": len(payload),
                    "sha256": sha,
                    "checksum_sha256": checksum(payload),
                    "checksum_type": "FULL_OBJECT",
                    "server_side_encryption": "aws:kms",
                    "kms_key_id": MODULE.PRIVATE_KMS_KEY_ARN,
                    "status": "passed",
                    "checks": dict(MODULE.PRIVATE_RECEIPT_OBJECT_CHECKS),
                }
            )
        revision = MODULE.canonical_packet_digest(rows)
        self.private_prefix = f"{self.private_base_prefix}revisions/{revision}/"
        for row in rows:
            key = self.private_prefix + row["relative_path"]
            row["bucket"] = MODULE.PRIVATE_BUCKET
            row["key"] = key
            row["uri"] = f"s3://{MODULE.PRIVATE_BUCKET}/{key}"
        receipt = {
            "schema_version": 1,
            "status": "passed",
            "generated_at_utc": MODULE.now(),
            "apply": True,
            "subject_alias": MODULE.SUBJECT_ALIAS,
            "run_id": MODULE.RUN_ID,
            "method_id": self.method_id,
            "packet_revision": revision,
            "source_packet_dir": str(self.packet.resolve()),
            "destination_prefix": f"s3://{MODULE.PRIVATE_BUCKET}/{self.private_prefix}",
            "kms_key_arn": MODULE.PRIVATE_KMS_KEY_ARN,
            "expected_files": list(self.files),
            "object_count": len(rows),
            "passed_count": len(rows),
            "forbidden_token_count": 1,
            "forbidden_token_sha256": ["b" * 64],
            "objects": rows,
            "checks": dict(MODULE.PRIVATE_RECEIPT_APPLY_CHECKS),
            "dry_run_receipt": {
                "path": str((self.root / "private-publication.dry.json").resolve()),
                "sha256": "c" * 64,
                "packet_revision": revision,
                "status": "dry_run",
            },
            "destination_final_history_count": len(rows),
            "completed_at_utc": MODULE.now(),
        }
        self.receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    def mutate_manifest(self, **updates: object) -> None:
        path = self.packet / "report_manifest.json"
        value = json.loads(path.read_text())
        value.update(updates)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        self.rebuild_receipt()

    def args(
        self,
        *,
        apply: bool = False,
        destination: str | None = None,
        private_receipt_sha256: str | None = None,
        dry_run_receipt: Path | None = None,
    ) -> argparse.Namespace:
        prefix = MODULE.PUBLIC_ROOT + MODULE.METHOD_CONTRACTS[self.method_id]["destination"]
        return argparse.Namespace(
            private_publication_receipt=self.receipt_path,
            private_publication_receipt_sha256=private_receipt_sha256
            or MODULE.sha256(self.receipt_path),
            method_id=self.method_id,
            destination_prefix=destination or f"s3://{MODULE.PUBLIC_BUCKET}/{prefix}",
            receipt_output=self.output_path,
            forbidden_token=[],
            forbidden_tokens_file=[],
            region=MODULE.REGION,
            apply=apply,
            dry_run_receipt=dry_run_receipt,
        )

    def write_dry_run_receipt(
        self,
        path: Path | None = None,
        *,
        forbidden_tokens_file: list[Path] | None = None,
    ) -> Path:
        output = path or self.root / "public-publication.dry.json"
        private_receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        _, expected, source_rows = MODULE.validate_private_receipt(
            self.receipt_path, self.method_id
        )
        tokens = MODULE.merge_forbidden_tokens(
            MODULE.DEFAULT_FORBIDDEN_TOKENS,
            files=forbidden_tokens_file or [],
        )
        prefix = MODULE.PUBLIC_ROOT + MODULE.METHOD_CONTRACTS[self.method_id]["destination"]
        receipt = {
            "schema_version": 1,
            "status": "dry_run",
            "generated_at_utc": MODULE.now(),
            "apply": False,
            "method_id": self.method_id,
            "subject_alias": MODULE.SUBJECT_ALIAS,
            "run_id": MODULE.RUN_ID,
            "classification": MODULE.CLASSIFICATION,
            "script_sha256": MODULE.sha256(Path(MODULE.__file__)),
            "private_publication_receipt": {
                "path": str(self.receipt_path.resolve()),
                "sha256": MODULE.sha256(self.receipt_path),
                "destination_prefix": private_receipt["destination_prefix"],
            },
            "destination_prefix": f"s3://{MODULE.PUBLIC_BUCKET}/{prefix}",
            "expected_files": list(expected),
            "forbidden_token_count": len(tokens),
            "forbidden_token_sha256": MODULE.forbidden_token_fingerprints(tokens),
            "source_objects": [
                MODULE.source_preflight_object(row) for row in source_rows
            ],
            "destination_objects": [],
            "destination_initial_history_count": 0,
            "checks": dict.fromkeys(MODULE.REVIEWED_PUBLIC_PREFLIGHT_CHECKS, True),
            "completed_at_utc": MODULE.now(),
        }
        output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        return output


def readdress_private_receipt(
    receipt: dict[str, object],
    method_id: str,
    revision_rows: list[dict[str, object]],
) -> None:
    revision = MODULE.canonical_packet_digest(revision_rows)
    prefix = (
        f"runs/{MODULE.SUBJECT_ALIAS}/{MODULE.RUN_ID}/reports/{method_id}/"
        f"revisions/{revision}/"
    )
    receipt["packet_revision"] = revision
    receipt["destination_prefix"] = f"s3://{MODULE.PRIVATE_BUCKET}/{prefix}"
    dry_run = receipt["dry_run_receipt"]
    assert isinstance(dry_run, dict)
    dry_run["packet_revision"] = revision

    rows = receipt["objects"]
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)
        row["key"] = prefix + str(row["relative_path"])
        row["uri"] = f"s3://{MODULE.PRIVATE_BUCKET}/{row['key']}"


class FakeAws:
    def __init__(self, fixture: Fixture) -> None:
        self.fixture = fixture
        receipt = json.loads(fixture.receipt_path.read_text())
        self.sources = {row["key"]: row for row in receipt["objects"]}
        self.public: dict[str, dict[str, object]] = {}
        self.put_calls: list[list[str]] = []
        self.get_calls: list[tuple[str, str]] = []
        self.preexisting_history: list[dict[str, object]] = []
        self.inject_delete_marker = False
        self.null_put_version = False
        self.literal_null_put_version = False
        self.boolean_put_version = False
        self.wrong_destination_checksum = False
        self.wrong_source_version = False
        self.wrong_source_kms = False
        self.boolean_source_content_length = False
        self.boolean_destination_content_length = False
        self.corrupt_download = False
        self.symlink_download = False

    def source_metadata(self, row: dict[str, object]) -> dict[str, object]:
        return {
            "VersionId": "wrong-version" if self.wrong_source_version else row["version_id"],
            "ContentLength": True if self.boolean_source_content_length else row["bytes"],
            "ChecksumType": "FULL_OBJECT",
            "ChecksumSHA256": row["checksum_sha256"],
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": "arn:aws:kms:us-east-1:000000000000:key/wrong"
            if self.wrong_source_kms
            else MODULE.PRIVATE_KMS_KEY_ARN,
            "Metadata": {"sha256": row["sha256"]},
        }

    @staticmethod
    def value(arguments: list[str], name: str) -> str:
        return arguments[arguments.index(name) + 1]

    def aws_json(self, arguments: list[str], region: str) -> dict[str, object]:
        self.assert_region(region)
        operation = tuple(arguments[:2])
        if operation == ("s3api", "get-bucket-versioning"):
            return {"Status": "Enabled"}
        if operation == ("s3api", "list-object-versions"):
            prefix = self.value(arguments, "--prefix")
            if self.preexisting_history:
                return {"Versions": self.preexisting_history, "DeleteMarkers": []}
            versions = [
                {
                    "Key": key,
                    "VersionId": row["VersionId"],
                    "IsLatest": True,
                    "Size": row["ContentLength"],
                }
                for key, row in sorted(self.public.items())
                if key.startswith(prefix)
            ]
            markers = (
                [{"Key": prefix + "deleted", "VersionId": "deleted-version", "IsLatest": True}]
                if self.inject_delete_marker and versions
                else []
            )
            return {"Versions": versions, "DeleteMarkers": markers}
        if operation == ("s3api", "head-object"):
            bucket = self.value(arguments, "--bucket")
            key = self.value(arguments, "--key")
            if bucket == MODULE.PRIVATE_BUCKET:
                return self.source_metadata(self.sources[key])
            metadata = dict(self.public[key])
            if self.boolean_destination_content_length:
                metadata["ContentLength"] = True
            return metadata
        if operation == ("s3api", "put-object"):
            self.put_calls.append(list(arguments))
            if self.null_put_version:
                return {}
            key = self.value(arguments, "--key")
            body = Path(self.value(arguments, "--body"))
            payload = body.read_bytes()
            version = f"public-version-{len(self.public) + 1}"
            metadata = json.loads(self.value(arguments, "--metadata"))
            observed_checksum = checksum(payload)
            if self.value(arguments, "--checksum-sha256") != observed_checksum:
                raise AssertionError("unexpected put-object checksum")
            if self.wrong_destination_checksum:
                observed_checksum = checksum(b"different")
            self.public[key] = {
                "VersionId": (
                    True
                    if self.boolean_put_version
                    else "null"
                    if self.literal_null_put_version
                    else version
                ),
                "ContentLength": len(payload),
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": observed_checksum,
                "ServerSideEncryption": "AES256",
                "Metadata": metadata,
                "ContentType": self.value(arguments, "--content-type"),
            }
            return {
                "VersionId": (
                    True
                    if self.boolean_put_version
                    else "null"
                    if self.literal_null_put_version
                    else version
                ),
                "ChecksumSHA256": observed_checksum,
            }
        raise AssertionError(f"unexpected AWS call: {arguments}")

    def download_exact(
        self,
        bucket: str,
        key: str,
        version_id: str,
        destination: Path,
        region: str,
    ) -> dict[str, object]:
        self.assert_region(region)
        self.get_calls.append((key, version_id))
        row = self.sources[key]
        if version_id != row["version_id"]:
            raise AssertionError("publisher did not request the receipt VersionId")
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self.fixture.payloads[str(row["relative_path"])]
        if self.symlink_download:
            redirected = destination.parent / f"{destination.name}.redirected"
            redirected.write_bytes(payload)
            destination.symlink_to(redirected)
            return self.source_metadata(row)
        destination.write_bytes(payload + (b"corrupt" if self.corrupt_download else b""))
        return self.source_metadata(row)

    def assert_region(self, region: str) -> None:
        if region != MODULE.REGION:
            raise AssertionError(f"wrong region: {region}")


class PublishReviewedPublicReportTests(unittest.TestCase):
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
            if segment in {
                'type(payload.get("schema_version")) is int',
                'payload["schema_version"] == expected',
            }:
                continue
            raw_comparisons.append(f"{node.lineno}: {segment}")

        self.assertEqual(raw_comparisons, [])

    def test_sha256_rejects_symlinked_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_source = root / "real-source.txt"
            real_source.write_text("real source\n", encoding="utf-8")
            source_link = root / "source-link.txt"
            source_link.symlink_to(real_source)

            with self.assertRaisesRegex(
                ValueError,
                "source-link.txt SHA-256 input must be a real file",
            ):
                MODULE.sha256(source_link)

            real_inputs = root / "real-inputs"
            real_inputs.mkdir()
            receipt = real_inputs / "private-publication.json"
            receipt.write_text(
                '{"status": "passed"}\n',
                encoding="utf-8",
            )
            linked_inputs = root / "linked-inputs"
            linked_inputs.symlink_to(real_inputs, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "private-publication.json SHA-256 input parent may not be a symlink",
            ):
                MODULE.sha256(linked_inputs / "private-publication.json")

    def test_report_packet_hash_rejects_symlink_after_manifest_load(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            real_load_json = MODULE.load_json
            swapped = False

            def swap_report_after_manifest_load(path: Path, label: str) -> dict:
                nonlocal swapped
                payload = real_load_json(path, label)
                if label == "report manifest" and not swapped:
                    report = fixture.packet / "report.md"
                    moved = fixture.root / "report.real.md"
                    report.rename(moved)
                    report.symlink_to(moved)
                    swapped = True
                return payload

            with (
                mock.patch.object(
                    MODULE,
                    "load_json",
                    side_effect=swap_report_after_manifest_load,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report.md SHA-256 input must be a real file",
                ),
            ):
                MODULE.validate_report_packet(
                    {name: fixture.packet / name for name in fixture.files},
                    fixture.method_id,
                    fixture.files,
                )

            self.assertTrue(swapped)

    def execute(
        self,
        fixture: Fixture,
        fake: FakeAws,
        *,
        apply: bool = False,
        dry_run_receipt: Path | None = None,
    ) -> dict[str, object]:
        with mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json), mock.patch.object(
            MODULE, "download_exact", side_effect=fake.download_exact
        ):
            return MODULE.run(
                fixture.args(
                    apply=apply,
                    dry_run_receipt=dry_run_receipt
                    or (fixture.write_dry_run_receipt() if apply else None),
                )
            )

    def test_dry_run_validates_all_exact_private_versions_without_uploading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)
            result = self.execute(fixture, fake)
            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(len(result["source_objects"]), 8)
            self.assertEqual(result["destination_objects"], [])
            self.assertEqual(len(fake.get_calls), 8)
            self.assertEqual(fake.put_calls, [])
            self.assertEqual(fixture.output_path.stat().st_mode & 0o777, 0o600)

    def test_rejects_stale_private_receipt_path_before_s3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)

            with (
                mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json),
                mock.patch.object(
                    MODULE,
                    "download_exact",
                    side_effect=fake.download_exact,
                ),
                self.assertRaisesRegex(ValueError, "SHA-256 does not match expected"),
            ):
                MODULE.run(fixture.args(private_receipt_sha256="0" * 64))

            self.assertEqual(fake.get_calls, [])
            self.assertEqual(fake.put_calls, [])

    def test_private_receipt_digest_is_bound_to_validated_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)
            original_private_receipt_sha256 = digest(fixture.receipt_path.read_bytes())
            real_validate = MODULE.validate_private_receipt_payload
            mutated = False

            def mutate_after_private_receipt_parse(
                receipt: dict[str, object],
                method_id: str,
            ) -> tuple[tuple[str, ...], list[dict[str, object]]]:
                nonlocal mutated
                result = real_validate(receipt, method_id)
                fixture.receipt_path.write_text(
                    '{"changed_after_validated_read": true}\n',
                    encoding="utf-8",
                )
                mutated = True
                return result

            with mock.patch.object(
                MODULE,
                "validate_private_receipt_payload",
                side_effect=mutate_after_private_receipt_parse,
            ):
                result = self.execute(fixture, fake)

            self.assertTrue(mutated)
            self.assertEqual(
                result["private_publication_receipt"]["sha256"],
                original_private_receipt_sha256,
            )

            self.assertEqual(fake.put_calls, [])

    def test_apply_requires_dry_run_receipt_before_s3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            args = fixture.args(apply=True)

            with (
                mock.patch.object(
                    MODULE, "aws_json", side_effect=AssertionError("AWS called")
                ),
                self.assertRaisesRegex(ValueError, "requires --dry-run-receipt"),
            ):
                MODULE.run(args)

            self.assertFalse(fixture.output_path.exists())

    def test_dry_run_receipt_is_only_valid_with_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            args = fixture.args(dry_run_receipt=fixture.write_dry_run_receipt())

            with self.assertRaisesRegex(ValueError, "only valid with --apply"):
                MODULE.run(args)

            self.assertFalse(fixture.output_path.exists())

    def test_apply_rejects_mismatched_dry_run_receipt_before_s3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            dry_receipt = fixture.write_dry_run_receipt()
            payload = json.loads(dry_receipt.read_text(encoding="utf-8"))
            payload["private_publication_receipt"]["sha256"] = "0" * 64
            dry_receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

            with (
                mock.patch.object(
                    MODULE, "aws_json", side_effect=AssertionError("AWS called")
                ),
                self.assertRaisesRegex(ValueError, "private receipt does not match"),
            ):
                MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_receipt))

            self.assertFalse(fixture.output_path.exists())

    def test_apply_rejects_changed_dry_run_source_object_before_s3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            dry_receipt = fixture.write_dry_run_receipt()
            payload = json.loads(dry_receipt.read_text(encoding="utf-8"))
            payload["source_objects"][0]["sha256"] = "0" * 64
            dry_receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

            with (
                mock.patch.object(
                    MODULE, "aws_json", side_effect=AssertionError("AWS called")
                ),
                self.assertRaisesRegex(ValueError, "source objects do not match"),
            ):
                MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_receipt))

            self.assertFalse(fixture.output_path.exists())

    def test_apply_rejects_failed_or_redirected_dry_run_receipt_before_s3(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            dry_receipt = fixture.write_dry_run_receipt()
            payload = json.loads(dry_receipt.read_text(encoding="utf-8"))
            payload["status"] = "failed"
            dry_receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

            with (
                mock.patch.object(
                    MODULE, "aws_json", side_effect=AssertionError("AWS called")
                ),
                self.assertRaisesRegex(ValueError, "contract is malformed"),
            ):
                MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_receipt))

            linked = fixture.root / "linked-dry-run.json"
            linked.symlink_to(dry_receipt)
            with self.assertRaisesRegex(ValueError, "must be a real file"):
                MODULE.run(fixture.args(apply=True, dry_run_receipt=linked))

            self.assertFalse(fixture.output_path.exists())

    def test_apply_rejects_dry_run_receipt_with_duplicate_json_object_names_before_s3(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            dry_receipt = fixture.write_dry_run_receipt()
            payload = json.loads(dry_receipt.read_text(encoding="utf-8"))
            text = json.dumps(payload, indent=2, sort_keys=True)
            status = f'  "status": "{payload["status"]}"'
            self.assertEqual(text.count(status), 1)
            text = text.replace(status, f'  "status": "failed",\n{status}', 1)
            dry_receipt.write_text(text + "\n", encoding="utf-8")

            with (
                mock.patch.object(
                    MODULE, "aws_json", side_effect=AssertionError("AWS called")
                ),
                self.assertRaisesRegex(
                    ValueError,
                    (
                        "duplicate JSON object name in "
                        "reviewed-public report dry-run receipt: status"
                    ),
                ),
            ):
                MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_receipt))

            self.assertFalse(fixture.output_path.exists())

    def test_apply_rejects_dry_run_receipt_with_extra_failed_check_before_s3(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            dry_receipt = fixture.write_dry_run_receipt()
            payload = json.loads(dry_receipt.read_text(encoding="utf-8"))
            payload["checks"]["unexpected_late_check"] = False
            dry_receipt.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(
                    MODULE, "aws_json", side_effect=AssertionError("AWS called")
                ),
                self.assertRaisesRegex(ValueError, "did not pass preflight checks"),
            ):
                MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_receipt))

            self.assertFalse(fixture.output_path.exists())

    def test_apply_rejects_dry_run_receipt_with_stale_extra_metadata_before_s3(
        self,
    ) -> None:
        cases = (
            (
                "top-level",
                lambda payload: payload.update({"stale_private_receipt": "old"}),
                "contract is malformed",
            ),
            (
                "nested private receipt",
                lambda payload: payload["private_publication_receipt"].update(
                    {"stale_path": "/tmp/old-private-receipt.json"}
                ),
                "private receipt does not match",
            ),
            (
                "float schema_version",
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "contract is malformed",
            ),
            (
                "boolean destination_initial_history_count",
                lambda payload: payload.__setitem__(
                    "destination_initial_history_count",
                    False,
                ),
                "contract is malformed",
            ),
            (
                "float destination_initial_history_count",
                lambda payload: payload.__setitem__(
                    "destination_initial_history_count",
                    0.0,
                ),
                "contract is malformed",
            ),
        )

        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                dry_receipt = fixture.write_dry_run_receipt()
                payload = json.loads(dry_receipt.read_text(encoding="utf-8"))
                mutate(payload)
                dry_receipt.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with (
                    mock.patch.object(
                        MODULE,
                        "aws_json",
                        side_effect=AssertionError("AWS called"),
                    ),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    MODULE.run(fixture.args(apply=True, dry_run_receipt=dry_receipt))

                self.assertFalse(fixture.output_path.exists())

    def test_apply_rejects_dry_run_receipt_below_symlinked_parent_before_s3(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            dry_receipt = fixture.write_dry_run_receipt()
            real_parent = fixture.root / "real-dry-run-receipts"
            real_parent.mkdir()
            moved_dry_receipt = real_parent / "public-publication.dry.json"
            dry_receipt.rename(moved_dry_receipt)
            linked_parent = fixture.root / "linked-dry-run-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with (
                mock.patch.object(
                    MODULE, "aws_json", side_effect=AssertionError("AWS called")
                ),
                self.assertRaisesRegex(ValueError, "parent may not be a symlink"),
            ):
                MODULE.run(
                    fixture.args(
                        apply=True,
                        dry_run_receipt=linked_parent
                        / "public-publication.dry.json",
                    )
                )

            self.assertFalse(fixture.output_path.exists())

    def test_apply_uses_create_only_sse_s3_sha256_and_exact_final_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)
            dry_run_receipt = fixture.write_dry_run_receipt()
            result = self.execute(
                fixture, fake, apply=True, dry_run_receipt=dry_run_receipt
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(
                result["dry_run_receipt"]["path"], str(dry_run_receipt.resolve())
            )
            self.assertEqual(
                result["dry_run_receipt"]["sha256"],
                digest(dry_run_receipt.read_bytes()),
            )
            self.assertEqual(result["dry_run_receipt"]["method_id"], fixture.method_id)
            self.assertTrue(result["checks"]["dry_run_receipt"])
            self.assertEqual(len(result["destination_objects"]), 8)
            self.assertTrue(result["checks"]["destination_exact_one_version_no_delete_history"])
            for call in fake.put_calls:
                self.assertEqual(FakeAws.value(call, "--if-none-match"), "*")
                self.assertEqual(FakeAws.value(call, "--server-side-encryption"), "AES256")
                self.assertEqual(FakeAws.value(call, "--checksum-algorithm"), "SHA256")
                key = FakeAws.value(call, "--key")
                relative = key.rsplit("/", 1)[-1]
                self.assertEqual(
                    FakeAws.value(call, "--checksum-sha256"),
                    checksum(fixture.payloads[relative]),
                )
                self.assertTrue(key.startswith(MODULE.PUBLIC_ROOT + "rosalind/"))

    def test_apply_dry_run_receipt_digest_is_bound_to_validated_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)
            dry_run_receipt = fixture.write_dry_run_receipt()
            original_dry_run_sha256 = digest(dry_run_receipt.read_bytes())
            real_source_preflight_object = MODULE.source_preflight_object
            mutated = False

            def mutate_after_dry_run_parse(
                row: dict[str, object],
            ) -> dict[str, object]:
                nonlocal mutated
                expected = real_source_preflight_object(row)
                if not mutated:
                    dry_run_receipt.write_text(
                        '{"changed_after_validated_read": true}\n',
                        encoding="utf-8",
                    )
                    mutated = True
                return expected

            with mock.patch.object(
                MODULE,
                "source_preflight_object",
                side_effect=mutate_after_dry_run_parse,
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

    def test_second_scan_rejects_unauthorized_hrd_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            (fixture.packet / "report.md").write_text(
                "This profile is HRD-positive.\n",
                encoding="utf-8",
            )
            manifest_path = fixture.packet / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["report_sha256"] = digest(
                (fixture.packet / "report.md").read_bytes()
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            fixture.rebuild_receipt()
            fake = FakeAws(fixture)

            with self.assertRaisesRegex(
                ValueError,
                "unauthorized HRD classification",
            ):
                self.execute(fixture, fake, apply=True)

            self.assertEqual(fake.put_calls, [])

    def test_second_scan_rejects_unauthorized_manifest_classification(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            manifest = json.loads(
                (fixture.packet / "report_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            manifest["review_summary"]["overall"]["statement"] = (
                "This profile is HRD-positive."
            )
            (fixture.packet / "report_manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            fixture.rebuild_receipt()
            fake = FakeAws(fixture)

            with self.assertRaisesRegex(
                ValueError,
                "unauthorized HRD classification",
            ):
                self.execute(fixture, fake, apply=True)

            self.assertEqual(fake.put_calls, [])

    def test_second_scan_rejects_wrong_report_kind(self) -> None:
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
                fixture.rebuild_receipt()
                fake = FakeAws(fixture)

                with self.assertRaisesRegex(
                    ValueError,
                    "report manifest report_kind is not exact",
                ):
                    self.execute(fixture, fake, apply=True)

                self.assertEqual(fake.put_calls, [])

    def test_second_scan_rejects_inexact_report_manifest_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.mutate_manifest(unbound_late_field=True)
            fixture.rebuild_receipt()
            fake = FakeAws(fixture)

            with self.assertRaisesRegex(
                ValueError,
                "report manifest envelope is not exact for rosalind_diana_wgs",
            ):
                self.execute(fixture, fake, apply=True)

            self.assertEqual(fake.put_calls, [])

    def test_second_scan_rejects_malformed_source_artifact_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.mutate_manifest(source_sha256={"../frozen_input": "a" * 64})
            fake = FakeAws(fixture)

            with self.assertRaisesRegex(
                ValueError,
                "malformed source-artifact ID for rosalind_diana_wgs",
            ):
                self.execute(fixture, fake, apply=True)

            self.assertEqual(fake.put_calls, [])

    def test_version_history_consumes_key_and_version_markers(self) -> None:
        pages = [
            {
                "IsTruncated": True,
                "Versions": [{"Key": "prefix/report.md", "VersionId": "v1"}],
                "DeleteMarkers": [],
                "NextKeyMarker": "prefix/report.md",
                "NextVersionIdMarker": "v1",
            },
            {
                "IsTruncated": False,
                "Versions": [],
                "DeleteMarkers": [{"Key": "prefix/old.md", "VersionId": "d1"}],
            },
        ]

        with mock.patch.object(MODULE, "aws_json", side_effect=pages) as aws_json:
            self.assertEqual(
                MODULE.version_history("bucket", "prefix/", MODULE.REGION),
                [
                    {
                        "Key": "prefix/old.md",
                        "VersionId": "d1",
                        "history_kind": "delete_marker",
                    },
                    {
                        "Key": "prefix/report.md",
                        "VersionId": "v1",
                        "history_kind": "version",
                    },
                ],
            )

        self.assertEqual(
            aws_json.call_args_list[1].args,
            (
                [
                    "s3api",
                    "list-object-versions",
                    "--bucket",
                    "bucket",
                    "--prefix",
                    "prefix/",
                    "--key-marker",
                    "prefix/report.md",
                    "--version-id-marker",
                    "v1",
                ],
                MODULE.REGION,
            ),
        )

    def test_version_history_rejects_missing_or_stalled_markers(self) -> None:
        missing_version = {
            "IsTruncated": True,
            "Versions": [],
            "DeleteMarkers": [],
            "NextKeyMarker": "prefix/report.md",
        }
        with mock.patch.object(MODULE, "aws_json", return_value=missing_version):
            with self.assertRaisesRegex(ValueError, "key/version markers"):
                MODULE.version_history("bucket", "prefix/", MODULE.REGION)

        stalled = {
            "IsTruncated": True,
            "Versions": [],
            "DeleteMarkers": [],
            "NextKeyMarker": "prefix/report.md",
            "NextVersionIdMarker": "v1",
        }
        with mock.patch.object(MODULE, "aws_json", side_effect=[stalled, stalled]):
            with self.assertRaisesRegex(ValueError, "did not advance"):
                MODULE.version_history("bucket", "prefix/", MODULE.REGION)

    def test_version_history_rejects_malformed_rows_without_sort_coercion(self) -> None:
        cases = (
            (
                "boolean Key",
                {"Versions": [{"Key": True, "VersionId": "v1"}]},
                "Key",
            ),
            (
                "empty Key",
                {"Versions": [{"Key": "", "VersionId": "v1"}]},
                "Key",
            ),
            (
                "boolean VersionId",
                {"Versions": [{"Key": "prefix/report.md", "VersionId": True}]},
                "VersionId",
            ),
            (
                "nullish delete marker VersionId",
                {"DeleteMarkers": [{"Key": "prefix/report.md", "VersionId": "null"}]},
                "VersionId",
            ),
            (
                "history kind override",
                {
                    "Versions": [
                        {
                            "Key": "prefix/report.md",
                            "VersionId": "v1",
                            "history_kind": True,
                        }
                    ]
                },
                "",
            ),
        )
        for label, page, expected_error in cases:
            with self.subTest(label=label):
                with mock.patch.object(MODULE, "aws_json", return_value=page):
                    if expected_error:
                        with self.assertRaisesRegex(ValueError, expected_error):
                            MODULE.version_history("bucket", "prefix/", MODULE.REGION)
                    else:
                        rows = MODULE.version_history(
                            "bucket", "prefix/", MODULE.REGION
                        )
                        self.assertEqual(rows[0]["history_kind"], "version")

    def test_version_history_sort_avoids_raw_string_coercion(self) -> None:
        module = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        parent_by_child = {
            child: parent
            for parent in ast.walk(module)
            for child in ast.iter_child_nodes(parent)
        }

        def in_version_history(node: ast.AST) -> bool:
            parent = parent_by_child.get(node)
            while parent is not None:
                if isinstance(parent, ast.FunctionDef):
                    return parent.name == "version_history"
                parent = parent_by_child.get(parent)
            return False

        raw_string_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and in_version_history(node)
        ]

        self.assertEqual(raw_string_coercions, [])

    def test_rejects_nonpassed_private_receipt_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            receipt = json.loads(fixture.receipt_path.read_text())
            receipt["status"] = "in_progress"
            fixture.receipt_path.write_text(json.dumps(receipt))
            with mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")):
                with self.assertRaisesRegex(ValueError, "not exact and passed"):
                    MODULE.run(fixture.args())

    def test_rejects_private_receipt_with_duplicate_json_object_names_before_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            payload = json.loads(fixture.receipt_path.read_text(encoding="utf-8"))
            text = json.dumps(payload, indent=2, sort_keys=True)
            apply = f'  "apply": {json.dumps(payload["apply"])}'
            self.assertEqual(text.count(apply), 1)
            text = text.replace(apply, f'  "apply": false,\n{apply}', 1)
            fixture.receipt_path.write_text(text + "\n", encoding="utf-8")

            with (
                mock.patch.object(
                    MODULE,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "duplicate JSON object name in private publication receipt: apply",
                ),
            ):
                MODULE.run(fixture.args())

            self.assertFalse(fixture.output_path.exists())

    def test_rejects_unallowlisted_or_reserved_private_file(self) -> None:
        for relative in ("raw.fastq.gz", "_publication"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                receipt = json.loads(fixture.receipt_path.read_text())
                receipt["objects"][0]["relative_path"] = relative
                fixture.receipt_path.write_text(json.dumps(receipt))
                with self.assertRaisesRegex(
                    ValueError, "unsafe report path|inventory|object is not exact"
                ):
                    MODULE.validate_private_receipt(fixture.receipt_path, fixture.method_id)

    def test_private_receipt_versions_must_be_exact_strings(self) -> None:
        cases = ("null", 1234567890)

        for value in cases:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                receipt = json.loads(fixture.receipt_path.read_text())
                receipt["objects"][0]["version_id"] = value
                fixture.receipt_path.write_text(json.dumps(receipt))

                with self.assertRaisesRegex(ValueError, "object is not exact"):
                    MODULE.validate_private_receipt(
                        fixture.receipt_path,
                        fixture.method_id,
                    )

    def test_private_receipt_object_hashes_must_be_exact_strings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            receipt = json.loads(fixture.receipt_path.read_text())
            numeric_digest = int("1" * 64)
            digest = "1" * 64
            receipt["objects"][0]["sha256"] = numeric_digest
            receipt["objects"][0]["checksum_sha256"] = MODULE.checksum_sha256(digest)
            readdress_private_receipt(
                receipt,
                fixture.method_id,
                [
                    {
                        **row,
                        "sha256": digest
                        if row["sha256"] == numeric_digest
                        else row["sha256"],
                    }
                    for row in receipt["objects"]
                ],
            )
            fixture.receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "object is not exact"):
                MODULE.validate_private_receipt(
                    fixture.receipt_path,
                    fixture.method_id,
                )

    def test_private_receipt_object_checks_must_be_exact(self) -> None:
        cases = (
            {"version_id": True},
            {**MODULE.PRIVATE_RECEIPT_OBJECT_CHECKS, "unexpected_late_check": True},
        )

        for checks in cases:
            with self.subTest(checks=checks), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                receipt = json.loads(fixture.receipt_path.read_text())
                receipt["objects"][0]["checks"] = checks
                fixture.receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, "object is not exact"):
                    MODULE.validate_private_receipt(
                        fixture.receipt_path,
                        fixture.method_id,
                    )

    def test_private_receipt_top_level_apply_checks_must_be_exact(self) -> None:
        cases = (
            ("non-apply receipt", lambda receipt: receipt.update({"apply": False})),
            (
                "missing dry-run binding",
                lambda receipt: receipt["checks"].pop("dry_run_receipt"),
            ),
            (
                "failed final history check",
                lambda receipt: receipt["checks"].__setitem__(
                    "destination_exact_one_version_no_delete_history",
                    False,
                ),
            ),
            (
                "unexpected late check",
                lambda receipt: receipt["checks"].__setitem__(
                    "unexpected_late_check",
                    True,
                ),
            ),
        )

        for label, mutate in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                receipt = json.loads(fixture.receipt_path.read_text())
                mutate(receipt)
                fixture.receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, "not exact and passed"):
                    MODULE.validate_private_receipt(
                        fixture.receipt_path,
                        fixture.method_id,
                    )

    def test_private_receipt_apply_envelope_must_be_exact(self) -> None:
        cases = (
            (
                "extra top-level key",
                lambda receipt: receipt.__setitem__("legacy_receipt", {}),
                "not exact and passed",
            ),
            (
                "missing dry-run summary",
                lambda receipt: receipt.pop("dry_run_receipt"),
                "not exact and passed",
            ),
            (
                "float schema_version",
                lambda receipt: receipt.__setitem__("schema_version", 1.0),
                "not exact and passed",
            ),
            (
                "extra object key",
                lambda receipt: receipt["objects"][0].__setitem__(
                    "legacy_etag", "abc123"
                ),
                "object envelope is not exact",
            ),
            (
                "stale dry-run revision",
                lambda receipt: receipt["dry_run_receipt"].__setitem__(
                    "packet_revision", "0" * 64
                ),
                "dry-run receipt summary is not exact",
            ),
        )

        for label, mutate, error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                receipt = json.loads(fixture.receipt_path.read_text())
                mutate(receipt)
                fixture.receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_private_receipt(
                        fixture.receipt_path,
                        fixture.method_id,
                    )

    def test_private_receipt_integer_fields_must_be_exact(self) -> None:
        cases = (
            (
                "object count float",
                lambda receipt: receipt.__setitem__(
                    "object_count", float(len(receipt["objects"]))
                ),
                "not exact and passed",
            ),
            (
                "passed count float",
                lambda receipt: receipt.__setitem__(
                    "passed_count", float(len(receipt["objects"]))
                ),
                "not exact and passed",
            ),
            (
                "destination final history count float",
                lambda receipt: receipt.__setitem__(
                    "destination_final_history_count",
                    float(len(receipt["objects"])),
                ),
                "not exact and passed",
            ),
            (
                "forbidden token count bool",
                lambda receipt: receipt.__setitem__("forbidden_token_count", True),
                "not exact and passed",
            ),
            (
                "object bytes bool",
                lambda receipt: (
                    receipt["objects"][0].__setitem__("bytes", True),
                    readdress_private_receipt(
                        receipt,
                        str(receipt["method_id"]),
                        [
                            {
                                **row,
                                "bytes": int(row["bytes"]),
                            }
                            for row in receipt["objects"]
                        ],
                    ),
                ),
                "object is not exact",
            ),
        )

        for label, mutate, error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                receipt = json.loads(fixture.receipt_path.read_text())
                mutate(receipt)
                fixture.receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_private_receipt(
                        fixture.receipt_path,
                        fixture.method_id,
                    )

    def test_rejects_destination_outside_exact_method_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            args = fixture.args(
                destination=f"s3://{MODULE.PUBLIC_BUCKET}/{MODULE.PUBLIC_ROOT}raw/"
            )
            with self.assertRaisesRegex(ValueError, "exact reviewed public child"):
                MODULE.run(args)

    def test_rejects_preexisting_destination_history_before_source_get(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)
            fake.preexisting_history = [
                {
                    "Key": MODULE.PUBLIC_ROOT + "rosalind/report.md",
                    "VersionId": "old",
                    "IsLatest": True,
                    "Size": 1,
                }
            ]
            with self.assertRaisesRegex(ValueError, "prior version"):
                self.execute(fixture, fake)
            self.assertEqual(fake.get_calls, [])
            self.assertEqual(json.loads(fixture.output_path.read_text())["status"], "failed")

    def test_rejects_wrong_source_version_or_kms_before_upload(self) -> None:
        for field in ("wrong_source_version", "wrong_source_kms"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                fake = FakeAws(fixture)
                setattr(fake, field, True)
                with self.assertRaisesRegex(ValueError, "exact-version head failed"):
                    self.execute(fixture, fake, apply=True)
                self.assertEqual(fake.put_calls, [])

    def test_rejects_boolean_source_content_length_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)
            fake.boolean_source_content_length = True
            with self.assertRaisesRegex(ValueError, "exact-version head failed"):
                self.execute(fixture, fake, apply=True)
            self.assertEqual(fake.put_calls, [])

    def test_source_version_checks_must_be_exact(self) -> None:
        cases = (
            {"version_id": True},
            {**MODULE.SOURCE_VERSION_CHECKS, "unexpected_late_check": True},
        )

        for checks in cases:
            with self.subTest(checks=checks):
                with self.assertRaisesRegex(ValueError, "exact-version head failed"):
                    MODULE.require_source_version_checks_exact(
                        checks,
                        "report.md",
                        "head",
                    )

    def test_local_source_checks_must_be_exact(self) -> None:
        cases = (
            {"bytes": True},
            {**MODULE.SOURCE_LOCAL_CHECKS, "unexpected_late_check": True},
        )

        for checks in cases:
            with self.subTest(checks=checks):
                with self.assertRaisesRegex(ValueError, "exact-version GET failed"):
                    MODULE.require_source_local_checks_exact(
                        checks,
                        "report.md",
                    )

    def test_apply_rejects_outdated_source_version_check_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)

            with (
                mock.patch.object(
                    MODULE,
                    "SOURCE_VERSION_CHECKS",
                    {
                        **MODULE.SOURCE_VERSION_CHECKS,
                        "unexpected_late_check": True,
                    },
                ),
                self.assertRaisesRegex(ValueError, "exact-version head failed"),
            ):
                self.execute(fixture, fake, apply=True)

            self.assertEqual(fake.put_calls, [])

    def test_apply_rejects_outdated_local_source_check_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)

            with (
                mock.patch.object(
                    MODULE,
                    "SOURCE_LOCAL_CHECKS",
                    {
                        **MODULE.SOURCE_LOCAL_CHECKS,
                        "unexpected_late_check": True,
                    },
                ),
                self.assertRaisesRegex(ValueError, "exact-version GET failed"),
            ):
                self.execute(fixture, fake, apply=True)

            self.assertEqual(fake.put_calls, [])

    def test_rejects_local_get_sha_mismatch_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)
            fake.corrupt_download = True
            with self.assertRaisesRegex(ValueError, "exact-version GET failed"):
                self.execute(fixture, fake, apply=True)
            self.assertEqual(fake.put_calls, [])

    def test_rejects_symlinked_exact_version_download_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)
            fake.symlink_download = True

            with self.assertRaisesRegex(ValueError, "must be a real file"):
                self.execute(fixture, fake, apply=True)

            self.assertEqual(fake.put_calls, [])
            self.assertEqual(
                json.loads(fixture.output_path.read_text(encoding="utf-8"))["status"],
                "failed",
            )

    def test_second_scan_rejects_forbidden_identifier_before_upload(self) -> None:
        for body in (
            "# Reviewed\n\npersonalis direct label\n",
            "# Reviewed\n\np&#101;rsonalis html entity label\n",
            "# Reviewed\n\np%65rsonalis URL-encoded label\n",
            "# Reviewed\n\np\u200dersonalis format-control label\n",
        ):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                report = fixture.packet / "report.md"
                report.write_text(body)
                fixture.mutate_manifest(report_sha256=digest(report.read_bytes()))
                fake = FakeAws(fixture)

                with self.assertRaisesRegex(ValueError, "forbidden identifier"):
                    self.execute(fixture, fake, apply=True)

                self.assertEqual(fake.put_calls, [])

    def test_second_scan_rejects_escaped_json_forbidden_identifier_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            support_name = "research_context_sources.json"
            support = fixture.packet / support_name
            support.write_text('{"note":"P\\u0065rsonalis escaped label"}\n')
            manifest_path = fixture.packet / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["support_sha256"][support_name] = digest(support.read_bytes())
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            fixture.rebuild_receipt()
            fake = FakeAws(fixture)
            with self.assertRaisesRegex(ValueError, "forbidden identifier"):
                self.execute(fixture, fake, apply=True)
            self.assertEqual(fake.put_calls, [])

    def test_second_scan_rejects_forbidden_identifier_from_file_before_upload(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            forbidden = fixture.root / "forbidden_tokens.json"
            forbidden.write_text(json.dumps(["Run-Specific-Token"]) + "\n")
            report = fixture.packet / "report.md"
            report.write_text("# Reviewed\n\nRUN-SPECIFIC-TOKEN leaked here\n")
            fixture.mutate_manifest(report_sha256=digest(report.read_bytes()))
            args = fixture.args(
                apply=True,
                dry_run_receipt=fixture.write_dry_run_receipt(
                    forbidden_tokens_file=[forbidden],
                ),
            )
            args.forbidden_tokens_file = [forbidden]
            fake = FakeAws(fixture)

            with mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json), mock.patch.object(
                MODULE, "download_exact", side_effect=fake.download_exact
            ), self.assertRaisesRegex(ValueError, "forbidden identifier"):
                MODULE.run(args)

            self.assertEqual(fake.put_calls, [])

    def test_manifest_cannot_promote_no_call_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.mutate_manifest(
                authorized_hrd_state="positive", classification_authorized=True
            )
            fake = FakeAws(fixture)
            with self.assertRaisesRegex(ValueError, "no-call contract"):
                self.execute(fixture, fake, apply=True)
            self.assertEqual(fake.put_calls, [])

    def test_manifest_cannot_mark_no_call_qc_as_passed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.mutate_manifest(classification_qc_status="passed")
            fake = FakeAws(fixture)

            with self.assertRaisesRegex(ValueError, "no-call contract"):
                self.execute(fixture, fake, apply=True)

            self.assertEqual(fake.put_calls, [])

    def test_manifest_schema_version_must_be_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.mutate_manifest(schema_version=1.0)

            with self.assertRaisesRegex(
                ValueError,
                "report manifest envelope is not exact for rosalind_diana_wgs",
            ):
                MODULE.validate_report_packet(
                    {name: fixture.packet / name for name in fixture.files},
                    fixture.method_id,
                    fixture.files,
                )

    def test_apply_rejects_null_destination_version(self) -> None:
        for flag in (
            "null_put_version",
            "literal_null_put_version",
            "boolean_put_version",
        ):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                fake = FakeAws(fixture)
                setattr(fake, flag, True)
                with self.assertRaisesRegex(ValueError, "omitted a non-null VersionId"):
                    self.execute(fixture, fake, apply=True)
                self.assertEqual(
                    json.loads(fixture.output_path.read_text())["status"], "failed"
                )

    def test_apply_rejects_destination_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)
            fake.wrong_destination_checksum = True
            with self.assertRaisesRegex(ValueError, "destination verification failed"):
                self.execute(fixture, fake, apply=True)

    def test_apply_rejects_boolean_destination_content_length(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)
            fake.boolean_destination_content_length = True
            with self.assertRaisesRegex(ValueError, "destination verification failed"):
                self.execute(fixture, fake, apply=True)
            self.assertEqual(json.loads(fixture.output_path.read_text())["status"], "failed")

    def test_public_destination_object_checks_must_be_exact(self) -> None:
        cases = (
            {"version_exact": True},
            {
                **MODULE.PUBLIC_DESTINATION_OBJECT_CHECKS,
                "unexpected_late_check": True,
            },
        )

        for checks in cases:
            with self.subTest(checks=checks):
                with self.assertRaisesRegex(
                    ValueError,
                    "public destination verification failed",
                ):
                    MODULE.require_public_destination_checks_exact(
                        checks,
                        "report.md",
                    )

    def test_final_history_size_must_be_exact_int(self) -> None:
        self.assertFalse(
            MODULE.exact_final_history(
                [
                    {
                        "history_kind": "version",
                        "Key": "reports/report.md",
                        "VersionId": "public-version-1",
                        "IsLatest": True,
                        "Size": True,
                    }
                ],
                "reports/",
                [
                    {
                        "key": "reports/report.md",
                        "version_id": "public-version-1",
                        "bytes": 1,
                    }
                ],
            )
        )

    def test_apply_rejects_outdated_public_destination_object_check_set(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)

            with (
                mock.patch.object(
                    MODULE,
                    "PUBLIC_DESTINATION_OBJECT_CHECKS",
                    {
                        **MODULE.PUBLIC_DESTINATION_OBJECT_CHECKS,
                        "unexpected_late_check": True,
                    },
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "public destination verification failed",
                ),
            ):
                self.execute(fixture, fake, apply=True)

    def test_apply_rejects_delete_marker_in_final_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fake = FakeAws(fixture)
            fake.inject_delete_marker = True
            with self.assertRaisesRegex(ValueError, "one expected version"):
                self.execute(fixture, fake, apply=True)
            self.assertEqual(json.loads(fixture.output_path.read_text())["status"], "failed")

    def test_deterministic_and_crosscheck_contracts_are_supported(self) -> None:
        for method in ("deterministic_full_wgs", "facets_scarhrd_blocked"):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary), method)
                fake = FakeAws(fixture)
                result = self.execute(fixture, fake)
                self.assertEqual(result["status"], "dry_run")
                self.assertEqual(len(result["source_objects"]), len(fixture.files))
                if method == "deterministic_full_wgs":
                    self.assertIn("crosscheck_input_plans.json", fixture.files)

    def test_existing_receipt_output_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.output_path.write_text("preserve\n")
            fake = FakeAws(fixture)
            with mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json):
                with self.assertRaises(FileExistsError):
                    MODULE.run(fixture.args())
            self.assertEqual(fixture.output_path.read_text(), "preserve\n")

    def test_receipt_output_rejects_symlinked_parent_without_writing_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary).resolve())
            real_parent = fixture.root / "real-receipts"
            real_parent.mkdir()
            linked_parent = fixture.root / "linked-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            args = fixture.args()
            args.receipt_output = linked_parent / "public-publication.json"
            fake = FakeAws(fixture)

            with mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json):
                with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                    MODULE.run(args)

            self.assertFalse((real_parent / "public-publication.json").exists())

    def test_receipt_output_rejects_nested_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-receipts"
            real_parent.mkdir()
            linked_parent = root / "linked-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            receipt = linked_parent / "missing" / "receipt.json"

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "redirected"},
                    create=True,
                )

            self.assertFalse((real_parent / "missing" / "receipt.json").exists())

    def test_receipt_output_rejects_existing_dir_below_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-receipts"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "linked-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            receipt = linked_parent / "existing" / "receipt.json"

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "redirected"},
                    create=True,
                )

            self.assertFalse((real_parent / "existing" / "receipt.json").exists())

    def test_create_receipt_removes_partial_output_after_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"

            with (
                mock.patch.object(
                    MODULE.os,
                    "fsync",
                    side_effect=OSError("synthetic fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic fsync failure"),
            ):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "preflighting"},
                    create=True,
                )

            self.assertFalse(receipt.exists())

    def test_create_receipt_fsyncs_file_and_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"

            with mock.patch.object(
                MODULE.os,
                "fsync",
                wraps=MODULE.os.fsync,
            ) as fsync:
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "preflighting"},
                    create=True,
                )

            self.assertEqual(fsync.call_count, 2)

    def test_create_receipt_removes_partial_output_after_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"

            with (
                mock.patch.object(
                    MODULE.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "preflighting"},
                    create=True,
                )

            self.assertFalse(receipt.exists())

    def test_create_receipt_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            original_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(parent: Path) -> None:
                original_fsync_directory(parent)
                receipt.write_text(
                    json.dumps({"status": "tampered"}) + "\n",
                    encoding="utf-8",
                )

            with (
                mock.patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "private output changed during write",
                ),
            ):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "preflighting"},
                    create=True,
                )

            self.assertFalse(receipt.exists())

    def test_replace_receipt_fsyncs_parent_after_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            MODULE.write_private_atomic(
                receipt,
                {"status": "preflighting"},
                create=True,
            )

            with mock.patch.object(
                MODULE,
                "fsync_directory",
                wraps=MODULE.fsync_directory,
            ) as fsync_directory:
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "dry_run"},
                    create=False,
                )

            fsync_directory.assert_called_once_with(receipt.parent)
            self.assertEqual(
                json.loads(receipt.read_text(encoding="utf-8")),
                {"status": "dry_run"},
            )

    def test_replace_receipt_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            MODULE.write_private_atomic(
                receipt,
                {"status": "preflighting"},
                create=True,
            )
            original_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(parent: Path) -> None:
                original_fsync_directory(parent)
                receipt.write_text(
                    json.dumps({"status": "tampered"}) + "\n",
                    encoding="utf-8",
                )

            with (
                mock.patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "private output changed during write",
                ),
            ):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "dry_run"},
                    create=False,
                )

            self.assertEqual(
                json.loads(receipt.read_text(encoding="utf-8")),
                {"status": "tampered"},
            )

    def test_private_receipt_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            target = fixture.receipt_path
            linked = fixture.root / "linked-receipt.json"
            linked.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "must be a real file"):
                MODULE.validate_private_receipt(linked, fixture.method_id)

    def test_private_receipt_symlink_after_file_audit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = Fixture(root)
            real_load_json = MODULE.load_json
            swapped = False

            def swap_receipt_before_parse(path: Path, label: str) -> dict[str, object]:
                nonlocal swapped
                if label == "private publication receipt" and not swapped:
                    moved = root / "private-publication.real.json"
                    path.rename(moved)
                    path.symlink_to(moved)
                    swapped = True
                return real_load_json(path, label)

            with (
                mock.patch.object(
                    MODULE,
                    "load_json",
                    side_effect=swap_receipt_before_parse,
                ),
                self.assertRaisesRegex(ValueError, "must be a real file"),
            ):
                MODULE.validate_private_receipt(
                    fixture.receipt_path,
                    fixture.method_id,
                )

            self.assertTrue(swapped)

    def test_private_receipt_below_symlinked_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            real_parent = fixture.root / "real-private-receipts"
            real_parent.mkdir()
            moved_receipt = real_parent / "private-publication.json"
            fixture.receipt_path.rename(moved_receipt)
            linked_parent = fixture.root / "linked-private-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.validate_private_receipt(
                    linked_parent / "private-publication.json",
                    fixture.method_id,
                )

    def test_rejects_private_receipt_with_unbound_packet_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            receipt = json.loads(fixture.receipt_path.read_text())

            receipt["packet_revision"] = "0" * 64
            fixture.receipt_path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, "packet revision"):
                MODULE.validate_private_receipt(fixture.receipt_path, fixture.method_id)

            fixture.rebuild_receipt()
            receipt = json.loads(fixture.receipt_path.read_text())
            receipt["destination_prefix"] = str(receipt["destination_prefix"]).replace(
                str(receipt["packet_revision"]), "1" * 64
            )
            for row in receipt["objects"]:
                row["key"] = str(row["key"]).replace(
                    str(receipt["packet_revision"]), "1" * 64
                )
                row["uri"] = str(row["uri"]).replace(
                    str(receipt["packet_revision"]), "1" * 64
                )
            fixture.receipt_path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, "packet revision"):
                MODULE.validate_private_receipt(fixture.receipt_path, fixture.method_id)


if __name__ == "__main__":
    unittest.main()
