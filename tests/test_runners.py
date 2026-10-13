import json

import httpx
import pytest

from continuum_bench.runners import LocalHTTPRunner, MockRunner, manifest, write_mock


def test_mock_does_not_claim_tokens_or_energy(tmp_path):
    reply = MockRunner().generate("hello")
    assert reply.provenance == "synthetic:mock" and reply.ttft_s is None
    write_mock(tmp_path / "nested/run.json")
    assert json.loads((tmp_path / "nested/run.json").read_text())["provenance"] == "synthetic:mock"


def test_remote_endpoints_disabled():
    with pytest.raises(ValueError):
        LocalHTTPRunner("https://api.example.com", "unverified")


def test_http_adapter_records_observable_metrics(monkeypatch):
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "response"}}], "usage": {"completion_tokens": 2}},
        request=httpx.Request("POST", "http://localhost"),
    )
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)
    result = LocalHTTPRunner("http://127.0.0.1:8080", "fixture-model").generate("hello")
    assert result.output_tokens == 2 and result.ttft_s is None
    assert result.latency_s >= 0


def test_manifest_requires_revision(monkeypatch):
    with pytest.raises(ValueError):
        manifest({}, "unverified/model", "main")
    monkeypatch.setattr("continuum_bench.runners.platform.platform", lambda: "fixture-os")
    monkeypatch.setattr(
        "continuum_bench.runners.subprocess.check_output",
        lambda args: b"abc\n" if "rev-parse" in args else b"",
    )
    info = manifest({"seed": 1}, "synthetic/fixture", "a" * 40)
    assert len(info["config_sha256"]) == 64 and info["energy"] == "not-collected"
