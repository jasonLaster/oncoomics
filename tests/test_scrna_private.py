"""Cloud-control tests use fabricated controls, never biological qualification evidence."""
import hashlib
import io
import json

import pytest

from diana_omics.scrna_io import sha256_file
from diana_omics.scrna_private import BUCKET, KMS_KEY, _put, collect_private, digest_json, run_prefix, signed_capabilities, storage_guard
from diana_omics.scrna_trust import COUNT_AUDIT_CHECKS, PATIENT_REQUIRED_GATES, REQUIRED_CASE_REVIEWS, REQUIRED_REPORTS, assess_case

ClientError = pytest.importorskip("botocore.exceptions").ClientError


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.versions = {}
        self.blocks = {name: True for name in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")}
        self.policy_public = False
        self.versioning = "Enabled"
        self.aborted = False
        self.posts = []

    def get_public_access_block(self, **kwargs):
        return {"PublicAccessBlockConfiguration": self.blocks}

    def get_bucket_policy_status(self, **kwargs):
        return {"PolicyStatus": {"IsPublic": self.policy_public}}

    def get_bucket_encryption(self, **kwargs):
        return {"ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": KMS_KEY}, "BucketKeyEnabled": False}]}}

    def get_bucket_versioning(self, **kwargs):
        return {"Status": self.versioning}

    def put_object(self, **kwargs):
        key = kwargs["Key"]
        if kwargs.get("IfNoneMatch") == "*" and key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        data = kwargs["Body"]
        if hasattr(data, "read"):
            data = data.read()
        version = "version-" + str(len(self.versions))
        self.objects[key] = version
        self.versions[(key, version)] = data
        return {"VersionId": version}

    def head_object(self, **kwargs):
        return {"VersionId": self.objects[kwargs["Key"]]}

    def get_object(self, **kwargs):
        key = kwargs["Key"]
        version = kwargs.get("VersionId", self.objects.get(key))
        return {"VersionId": version, "Body": io.BytesIO(self.versions[(key, version)]), "ServerSideEncryption": "aws:kms", "SSEKMSKeyId": KMS_KEY}

    def create_multipart_upload(self, **kwargs):
        return {"UploadId": "upload-1"}

    def upload_part(self, **kwargs):
        raise RuntimeError("simulated connection loss")

    def abort_multipart_upload(self, **kwargs):
        self.aborted = True

    def generate_presigned_url(self, operation, **kwargs):
        assert operation == "get_object" and kwargs["ExpiresIn"] == 7200
        return "https://example.invalid/signed"

    def generate_presigned_post(self, **kwargs):
        self.posts.append(kwargs)
        return {"url": "https://example.invalid/upload", "fields": kwargs["Fields"]}


@pytest.mark.parametrize("change", ["block", "public", "unversioned"])
def test_storage_guard_denies_weakened_privacy(change):
    s3 = FakeS3()
    if change == "block":
        s3.blocks["BlockPublicPolicy"] = False
    elif change == "public":
        s3.policy_public = True
    else:
        s3.versioning = "Suspended"
    with pytest.raises(ValueError, match="guard failed"):
        storage_guard(s3)


def test_immutable_upload_checks_actual_bytes_not_metadata():
    s3 = FakeS3()
    data = b"source bytes"
    sha = hashlib.sha256(data).hexdigest()
    key = "private/scrna/intakes/test/source"
    first = _put(s3, key, io.BytesIO(data), sha, len(data))
    assert _put(s3, key, io.BytesIO(data), sha, len(data)) == first
    s3.versions[(key, first["version_id"])] = b"corrupt bytes"
    with pytest.raises(ValueError, match="do not match"):
        _put(s3, key, io.BytesIO(data), sha, len(data))


def test_multipart_failure_aborts_and_never_claims_complete():
    s3 = FakeS3()
    with pytest.raises(RuntimeError, match="connection loss"):
        _put(s3, "private/scrna/intakes/test/source", io.BytesIO(b"small injected failed part"), "0" * 64, 65 * 1024**2)
    assert s3.aborted
    assert not s3.objects


def test_signed_policy_constrains_destination_encryption_size_and_expiry():
    s3 = FakeS3()
    source_contract = {"fabricated": True}
    identity = digest_json(source_contract)
    key = f"private/scrna/intakes/{identity}/intake_bundle.json"
    bundle = json.dumps({"intake_id": identity, "source_contract": source_contract, "objects": []}).encode()
    response = s3.put_object(Key=key, Body=bundle)
    receipt = {"intake_id": identity, "bundle": {"bucket": BUCKET, "key": key, "version_id": response["VersionId"], "size_bytes": len(bundle), "sha256": hashlib.sha256(bundle).hexdigest()}}
    capabilities = signed_capabilities(s3, receipt, "run-001")
    policy = s3.posts[0]
    assert policy["Bucket"] == BUCKET and policy["Key"] == "private/scrna/runs/run-001/${filename}"
    assert policy["ExpiresIn"] == 7200
    assert {"x-amz-server-side-encryption": "aws:kms"} in policy["Conditions"]
    assert {"x-amz-server-side-encryption-aws-kms-key-id": KMS_KEY} in policy["Conditions"]
    assert ["content-length-range", 0, 1024**3] in policy["Conditions"]
    assert not any("AWS_SECRET" in key for key in capabilities)


def fabricated_run(root, upstream=False):
    """Minimal fake immutable run for admission mechanics; never a benchmark."""
    root.mkdir()
    (root / "source").mkdir()
    (root / "source/scrna.py").write_text("fabricated science source")
    (root / "conda-explicit.txt").write_text("fabricated environment")
    method = {"scientific_sources": {"scrna.py": sha256_file(root / "source/scrna.py")}, "conda_explicit_sha256": sha256_file(root / "conda-explicit.txt")}
    method["method_sha256"] = digest_json(method)
    contract = {"evidence_lane": "patient_research", "species": "Homo sapiens", "tissue": "breast tumor", "material": "whole_cell",
                "captures": [{"capture_id": "test-cap-001", "chemistry": "3prime_v3", "reference": "test-reference", "reference_sha256": "1" * 64, "clinical_subtype": "TNBC"}]}
    if upstream:
        contract["captures"][0]["count_origin"] = {"qualified_for_patient": False}
    metrics = {"test-cap-001": {"gates": {key: True for key in PATIENT_REQUIRED_GATES | {"capture_metadata_resolved", "chemistry_metadata_resolved"}}, "ambient_rna_status": "estimated_review_required"}}
    for filename, value in {"input_contract.json": contract, "method_identity.json": method, "qc_summary.json": metrics, "intake_inspection.json": {}, "source_hashes.json": {}}.items():
        (root / filename).write_text(json.dumps(value))
    index = [{"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(root.rglob("*")) if path.is_file()]
    (root / "artifact_index.json").write_text(json.dumps(index))
    manifest = {"status": "complete", "evidence_lane": "patient_research", "intake_id": digest_json(contract), "artifact_index_sha256": sha256_file(root / "artifact_index.json"), "method_sha256": method["method_sha256"]}
    (root / "run_manifest.json").write_text(json.dumps(manifest))
    return method, contract, metrics


def test_case_without_qualification_remains_provisional_and_does_not_require_author_truth(tmp_path):
    run = tmp_path / "run"
    fabricated_run(run)
    result = assess_case(run)
    assert result["decision"] == "provisional_hold" and result["clinical_ready"] is False
    assert not any("published" in text or "subtypes" in text for text in result["blockers"])
    assert len(result["blockers"]) == 3


def test_case_tampered_checkpoint_and_stale_audit_fail_closed(tmp_path):
    run = tmp_path / "run"
    fabricated_run(run)
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"status": "counts_integrity_pass", "intake_id": "wrong", "artifact_index_sha256": sha256_file(run / "artifact_index.json"), "captures": {"test-cap-001": dict.fromkeys(COUNT_AUDIT_CHECKS, True)}}))
    with pytest.raises(ValueError, match="incomplete/stale"):
        assess_case(run, audit=audit)
    (run / "qc_summary.json").write_text("changed")
    with pytest.raises(ValueError, match="integrity"):
        assess_case(run)


def test_qualification_needs_independently_approved_digest(tmp_path):
    run = tmp_path / "run"
    fabricated_run(run)
    certificate = tmp_path / "certificate.json"
    certificate.write_text(json.dumps({"status": "reviewed"}))
    with pytest.raises(ValueError, match="approved SHA"):
        assess_case(run, certificate=certificate)


def test_collector_rejects_duplicate_index_before_creating_destination(tmp_path):
    s3 = FakeS3()
    prefix = run_prefix("run-001")
    item = {"path": "data.txt", "sha256": "0" * 64, "size_bytes": 0}
    index = json.dumps([item, item]).encode()
    r = s3.put_object(Key=prefix + "artifact_index.json", Body=index)
    manifest = {"run_id": "run-001", "status": "complete", "evidence_lane": "patient_research", "artifact_index_sha256": hashlib.sha256(index).hexdigest(), "artifact_versions": {"artifact_index.json": r["VersionId"]}}
    s3.put_object(Key=prefix + "run_manifest.json", Body=json.dumps(manifest).encode())
    destination = tmp_path / "collected"
    with pytest.raises(ValueError, match="Duplicate"):
        collect_private(s3, "run-001", destination)
    assert not destination.exists()


@pytest.mark.parametrize("gap", [None, "overlap", "scope", "expired", "incomplete_review", "count_origin"])
def test_method_qualification_and_patient_review_are_separate_bound_gates(tmp_path, gap):
    run = tmp_path / "run"
    method, _, _ = fabricated_run(run, upstream=gap == "count_origin")
    index_sha = sha256_file(run / "artifact_index.json")
    manifest = json.loads((run / "run_manifest.json").read_text())
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"status": "counts_integrity_pass", "intake_id": manifest["intake_id"], "artifact_index_sha256": index_sha,
                                 "captures": {"test-cap-001": dict.fromkeys(COUNT_AUDIT_CHECKS, True)}}))
    reports = {}
    for name in REQUIRED_REPORTS:
        path = tmp_path / (name + ".txt")
        path.write_text("Fabricated admission mechanics test. No biological evidence or qualification.")
        reports[name] = {"status": "validated", "reviewer": "test_operator", "source": "fabricated test", "path": path.name, "sha256": sha256_file(path)}
    reports["matched_external_validation"].update(training_donors=["train"], evaluation_donors=["eval1", "eval2", "eval3"], training_studies=["train_study"], evaluation_studies=["eval_study"])
    certificate = {"status": "reviewed", "reviewer": "test_operator", "method_sha256": method["method_sha256"], "claim": "postcount_qc_and_coarse_marker_hints",
                   "expires_at": "2100-01-01T00:00:00Z", "reports": reports, "scope": {"species": "Homo sapiens", "tissue": "breast tumor", "material": "whole_cell",
                   "chemistries": ["3prime_v3"], "references": ["test-reference"], "reference_sha256": ["1" * 64], "clinical_subtypes": ["TNBC"]}}
    review = {"status": "reviewed", "reviewer": "test_operator", "artifact_index_sha256": index_sha, "method_sha256": method["method_sha256"], "checks": dict.fromkeys(REQUIRED_CASE_REVIEWS, True)}
    if gap == "overlap":
        reports["matched_external_validation"]["evaluation_donors"][0] = "train"
    elif gap == "scope":
        certificate["scope"]["reference_sha256"] = ["2" * 64]
    elif gap == "expired":
        certificate["expires_at"] = "2000-01-01T00:00:00Z"
    elif gap == "incomplete_review":
        review["checks"]["qc_losses"] = 1  # Truthy must not substitute for a reviewed boolean.
    cert_path, review_path = tmp_path / "cert.json", tmp_path / "review.json"
    cert_path.write_text(json.dumps(certificate))
    review_path.write_text(json.dumps(review))
    result = assess_case(run, cert_path, sha256_file(cert_path), review_path, audit)
    assert result["decision"] == ("reviewed_research" if gap is None else "provisional_hold")
    assert result["method_qualified"] is (gap in {None, "incomplete_review", "count_origin"})
    assert result["clinical_ready"] is False
