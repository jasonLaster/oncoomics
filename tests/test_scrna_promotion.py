import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from diana_omics.scrna_io import write_json

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("scrna_platform_controller", ROOT / "scripts/scrna_platform.py")
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class FakeClientError(Exception):
    response = {"Error": {"Code": "PreconditionFailed"}}


class VersionedS3:
    exceptions = SimpleNamespace(ClientError=FakeClientError)

    def __init__(self, run):
        self.objects = {f"public/scrna/runs/test-only/{name}": (run / name).read_bytes()
                        for name in ("run_manifest.json", "artifact_index.json")}
        self.writes = []

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]]), "VersionId": "test-version"}

    def put_object(self, **kwargs):
        assert kwargs["IfNoneMatch"] == "*" and kwargs["ServerSideEncryption"] == "AES256"
        self.writes.append(kwargs["Key"])
        if kwargs["Key"] in self.objects:
            raise FakeClientError()
        self.objects[kwargs["Key"]] = kwargs["Body"]


def test_quarantined_run_never_writes_or_reads_release_objects(monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "assess", lambda *args: False)
    assert controller.promote(object(), "test-only", tmp_path, None) is False


def test_admitted_control_publishes_once_and_verifies_versioned_bytes(monkeypatch, tmp_path):
    # Fabricated control tests S3 mechanics; it bypasses assessment and is not scientific evidence.
    monkeypatch.setattr(controller, "ROOT", tmp_path)
    monkeypatch.setattr(controller, "assess", lambda *args: True)
    run = tmp_path / "results/scrna/test-only"
    validation = tmp_path / "results/scrna/validation/test-only"
    run.mkdir(parents=True)
    validation.mkdir(parents=True)
    write_json(run / "run_manifest.json", {"run_id": "test-only"})
    write_json(run / "artifact_index.json", [])
    write_json(validation / "release_decision.json", {"decision": "admitted", "production_ready": True})
    s3 = VersionedS3(run)
    assert controller.promote(s3, "test-only", tmp_path, None)
    key = "public/scrna/releases/test-only/release_manifest.json"
    payload = json.loads(s3.objects[key])
    assert payload["controls"]["artifact_index.json"]["version_id"] == "test-version"
    assert controller.promote(s3, "test-only", tmp_path, None)  # Same evidence: idempotent.
    previous = s3.objects[key]
    write_json(validation / "release_decision.json", {"decision": "admitted", "production_ready": True, "changed_evidence": True})
    with pytest.raises(ValueError, match="different evidence"):
        controller.promote(s3, "test-only", tmp_path, None)
    assert s3.objects[key] == previous


def test_changed_remote_controls_cannot_be_promoted(monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "ROOT", tmp_path)
    monkeypatch.setattr(controller, "assess", lambda *args: True)
    run = tmp_path / "results/scrna/test-only"
    validation = tmp_path / "results/scrna/validation/test-only"
    run.mkdir(parents=True)
    validation.mkdir(parents=True)
    write_json(run / "run_manifest.json", {"run_id": "test-only"})
    write_json(run / "artifact_index.json", [])
    write_json(validation / "release_decision.json", {"decision": "admitted"})
    s3 = VersionedS3(run)
    s3.objects["public/scrna/runs/test-only/run_manifest.json"] = b"changed"
    with pytest.raises(ValueError, match="matching versioned"):
        controller.promote(s3, "test-only", tmp_path, None)
    assert not s3.writes
