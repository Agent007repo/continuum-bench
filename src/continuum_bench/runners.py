"""Mock and loopback HTTP foundation. Real benchmark orchestration is pending."""

import hashlib
import json
import platform
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class Reply:
    text: str
    latency_s: float
    output_tokens: int | None
    ttft_s: float | None
    provenance: str


class Runner(Protocol):
    def generate(self, prompt: str) -> Reply: ...


class MockRunner:
    def generate(self, prompt: str) -> Reply:
        return Reply("synthetic:" + prompt[:20], 0.0, None, None, "synthetic:mock")


class LocalHTTPRunner:
    def __init__(self, endpoint: str, model: str) -> None:
        url = urlparse(endpoint)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Only loopback HTTP supported; cloud usage is disabled")
        self.endpoint = endpoint.rstrip("/")
        self.model = model

    def generate(self, prompt: str) -> Reply:
        start = time.monotonic()
        response = httpx.post(
            self.endpoint + "/v1/chat/completions",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 128,
            },
            timeout=120,
            follow_redirects=False,
        )
        response.raise_for_status()
        data = response.json()
        text = str(data["choices"][0]["message"]["content"])
        tokens = data.get("usage", {}).get("completion_tokens")
        # Non-streaming responses cannot establish TTFT.
        return Reply(
            text,
            time.monotonic() - start,
            tokens if isinstance(tokens, int) else None,
            None,
            "measured:http-client-latency",
        )


def manifest(config: dict[str, object], model_repo: str, revision: str) -> dict[str, object]:
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("Require exact 40-character model revision, not main/latest")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"]))
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {
        "git_sha": sha,
        "working_tree_dirty": dirty,
        "timestamp": datetime.now(UTC).isoformat(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "model_repo": model_repo,
        "revision": revision,
        "config_sha256": hashlib.sha256(encoded).hexdigest(),
        "hardware_details": "pending user preflight",
        "energy": "not-collected",
    }


def write_mock(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = asdict(MockRunner().generate("Smoke test only"))
    path.write_text(json.dumps(row, indent=2) + "\n")
