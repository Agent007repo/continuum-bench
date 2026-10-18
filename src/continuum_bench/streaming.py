"""Loopback SSE client. Timings are client-observed; no energy is collected."""

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class StreamingReply:
    text: str
    latency_s: float
    ttft_s: float | None
    output_tokens: int | None
    finish_reason: str
    request_start_s: float
    request_end_s: float
    first_content_s: float | None
    raw_events: tuple[str, ...]
    provenance: str = "measured:http-client-stream"


class StreamFailure(ValueError):
    def __init__(self, message: str, events: list[str], start: float, end: float) -> None:
        super().__init__(message)
        self.raw_events = tuple(events)
        self.request_start_s = start
        self.request_end_s = end


class LocalStreamingRunner:
    def __init__(
        self, endpoint: str, model: str, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Only a plain loopback HTTP server root is allowed")
        if not model.strip():
            raise ValueError("Model identifier required")
        self.endpoint, self.model, self.transport = endpoint.rstrip("/"), model, transport

    def generate(self, prompt: str, *, seed: int = 0, max_tokens: int = 128) -> StreamingReply:
        if not prompt.strip() or max_tokens < 1:
            raise ValueError("Nonempty prompt and positive output budget required")
        start = time.monotonic()
        events: list[str] = []
        pieces: list[str] = []
        first: float | None = None
        tokens: int | None = None
        finish: str | None = None
        done = False
        pending: list[str] = []

        def consume(data: str) -> None:
            nonlocal first, tokens, finish, done
            events.append(data)
            if len(data) > 1_000_000 or sum(map(len, events)) > 8_000_000:
                raise ValueError("Streaming response exceeded bounded record size")
            if data == "[DONE]":
                done = True
                return
            chunk: Any = json.loads(data)
            if not isinstance(chunk, dict) or chunk.get("error"):
                raise ValueError("Malformed chunk or server error")
            usage = chunk.get("usage")
            if usage is not None:
                if not isinstance(usage, dict):
                    raise ValueError("Malformed usage")
                count = usage.get("completion_tokens")
                if count is not None:
                    if type(count) is not int or count < 0:
                        raise ValueError("Invalid completion-token count")
                    tokens = count
            choices = chunk.get("choices", [])
            if not isinstance(choices, list) or len(choices) > 1:
                raise ValueError("Only one completion choice is supported")
            if choices:
                choice = choices[0]
                if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                    raise ValueError("Invalid completion choice")
                delta = choice.get("delta", {})
                if not isinstance(delta, dict):
                    raise ValueError("Malformed content delta")
                content = delta.get("content")
                if content is not None:
                    if not isinstance(content, str) or (content and finish is not None):
                        raise ValueError("Invalid content or content after finish")
                    if content:
                        if first is None:
                            first = time.monotonic()
                        pieces.append(content)
                reason = choice.get("finish_reason")
                if reason is not None:
                    if reason not in {"stop", "length"} or finish is not None:
                        raise ValueError("Unsupported or repeated finish reason")
                    finish = reason

        try:
            with httpx.Client(
                transport=self.transport, trust_env=False, follow_redirects=False, timeout=120
            ) as client:
                with client.stream(
                    "POST",
                    self.endpoint + "/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": True,
                        "stream_options": {"include_usage": True},
                        "temperature": 0,
                        "seed": seed,
                        "max_tokens": max_tokens,
                    },
                    follow_redirects=False,
                ) as response:
                    response.raise_for_status()
                    if (
                        response.headers.get("content-type", "").split(";")[0]
                        != "text/event-stream"
                    ):
                        raise ValueError("Expected an SSE content type")
                    for line in response.iter_lines():
                        if line == "":
                            if pending:
                                data = "\n".join(pending)
                                pending = []
                                consume(data)
                                if done:
                                    break
                        elif line.startswith("data:"):
                            pending.append(line[5:].removeprefix(" "))
                            if sum(map(len, pending)) > 1_000_000:
                                raise ValueError(
                                    "Incomplete SSE event exceeded bounded record size"
                                )
                    if pending and not done:
                        data = "\n".join(pending)
                        pending = []
                        consume(data)
            end = time.monotonic()
            if not done or finish is None:
                raise ValueError("Interrupted stream or missing finish event")
            return StreamingReply(
                "".join(pieces),
                end - start,
                first - start if first is not None else None,
                tokens,
                finish,
                start,
                end,
                first,
                tuple(events),
            )
        except (httpx.HTTPError, ValueError, TypeError) as error:
            if pending:
                events.append("\n".join(pending))
            raise StreamFailure(str(error), events, start, time.monotonic()) from error
