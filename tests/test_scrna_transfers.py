"""Fault injection for private transfers; signed capabilities are fabricated secrets."""
import hashlib
from types import SimpleNamespace

import pytest
import requests

from diana_omics.scrna_private import KMS_KEY, download_signed, upload_signed


class Response:
    def __init__(self, blocks, status=200, version="v1", range_header=None):
        self.blocks = blocks
        self.status_code = status
        self.headers = {"x-amz-version-id": version, "x-amz-server-side-encryption": "aws:kms", "x-amz-server-side-encryption-aws-kms-key-id": KMS_KEY}
        if range_header:
            self.headers["Content-Range"] = range_header

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, **kwargs):
        for block in self.blocks:
            if isinstance(block, Exception):
                raise block
            yield block


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    data = b"complete-source-bytes"
    item = {"key": "private/scrna/intakes/test/data", "version_id": "v1", "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    caps = {"inputs": [{"key": item["key"], "version_id": "v1", "url": "https://example.invalid/secret-token"}]}
    return data, item, caps


def test_interrupted_download_resumes_exact_pinned_bytes(source, monkeypatch, tmp_path):
    data, item, caps = source
    responses = [Response([data[:8], requests.ConnectionError("secret-token")]), Response([data[8:]], 206, range_header=f"bytes 8-{len(data)-1}/{len(data)}")]
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs)
        return responses.pop(0)
    monkeypatch.setattr(requests, "get", get)
    destination = tmp_path / "data"
    download_signed(caps, item, destination)
    assert destination.read_bytes() == data
    assert calls[0]["headers"] == {} and calls[1]["headers"] == {"Range": "bytes=8-"}


@pytest.mark.parametrize("bad", ["version", "range", "checksum", "denied"])
def test_signed_download_cannot_accept_wrong_version_range_bytes_or_access(source, monkeypatch, tmp_path, bad):
    data, item, caps = source
    response = Response([b"wrong" if bad == "checksum" else data], status=403 if bad == "denied" else 200, version="other" if bad == "version" else "v1")
    responses = [Response([data[:8], requests.ConnectionError("secret-token")]), Response([data[8:]], 206, range_header="bytes 0-20/21")] if bad == "range" else [response]
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: responses.pop(0))
    with pytest.raises(ValueError) as caught:
        download_signed(caps, item, tmp_path / "data")
    assert "secret-token" not in str(caught.value)
    assert not responses


def test_download_retries_are_bounded_and_errors_omit_token(source, monkeypatch, tmp_path):
    _, item, caps = source
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise requests.ConnectionError("https://example.invalid/secret-token")
    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(RuntimeError, match="three attempts") as caught:
        download_signed(caps, item, tmp_path / "data")
    assert len(calls) == 3 and "secret-token" not in str(caught.value)


@pytest.mark.parametrize("first_status", [503, 403])
def test_upload_restarts_body_on_retry_but_never_bypasses_denial(source, monkeypatch, tmp_path, first_status):
    data, _, _ = source
    path = tmp_path / "artifact"
    path.write_bytes(data)
    caps = {"output_prefix": "private/scrna/runs/test/", "output": {"url": "https://example.invalid/secret-token", "fields": {"x-amz-server-side-encryption": "aws:kms"}}}
    bodies = []
    def post(url, **kwargs):
        bodies.append(kwargs["data"].to_string())
        return SimpleNamespace(status_code=first_status if len(bodies) == 1 else 201, headers={"x-amz-version-id": "v2"})
    monkeypatch.setattr(requests, "post", post)
    if first_status == 403:
        with pytest.raises(RuntimeError):
            upload_signed(caps, caps["output_prefix"] + "data", path)
        assert len(bodies) == 1
    else:
        receipt = upload_signed(caps, caps["output_prefix"] + "data", path)
        assert len(bodies) == 2 and all(data in body for body in bodies)
        assert receipt["version_id"] == "v2" and receipt["sha256"] == hashlib.sha256(data).hexdigest()
