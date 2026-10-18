import json

import httpx
import pytest

from continuum_bench.streaming import LocalStreamingRunner, StreamFailure


def runner(events, status=200, content_type="text/event-stream"):
    def handler(request):
        payload = json.loads(request.content)
        assert payload["stream"] and payload["seed"] == 7
        return httpx.Response(status, content=events, headers={"content-type": content_type})

    return LocalStreamingRunner(
        "http://127.0.0.1:8080", "unit-fixture", transport=httpx.MockTransport(handler)
    )


def event(content=None, finish=None):
    return (
        "data: "
        + json.dumps(
            {"choices": [{"index": 0, "delta": {"content": content}, "finish_reason": finish}]}
        )
        + "\n\n"
    )


def test_role_events_do_not_establish_first_token(monkeypatch):
    stream = (
        event()
        + event("Hello ")
        + event("fixture", "stop")
        + 'data: {"choices":[],"usage":{"completion_tokens":2}}\n\ndata: [DONE]\n\n'
    )
    clock = iter([10.0, 10.3, 11.0])
    monkeypatch.setattr("continuum_bench.streaming.time.monotonic", lambda: next(clock))
    reply = runner(stream).generate("fixture prompt", seed=7)
    assert reply.text == "Hello fixture" and reply.latency_s == 1
    assert reply.ttft_s == pytest.approx(0.3) and reply.first_content_s == 10.3
    assert reply.output_tokens == 2 and reply.finish_reason == "stop"
    assert len(reply.raw_events) == 5


def test_empty_and_truncated_completions_are_distinguished():
    empty = runner(event(finish="stop") + "data: [DONE]").generate("fixture", seed=7)
    assert empty.ttft_s is None and empty.text == ""
    truncated = runner(event("fixture", "length") + "data: [DONE]\n\n").generate("fixture", seed=7)
    assert truncated.finish_reason == "length"


@pytest.mark.parametrize(
    "stream",
    [
        event("partial"),
        event("partial") + "data: malformed\n\n",
        event("partial") + 'data: {"error":"fixture"}\n\n',
        event("partial") + event(finish="tool_calls") + "data: [DONE]\n\n",
        event("partial", "stop") + event("late") + "data: [DONE]\n\n",
        'data: {"usage":{"completion_tokens":true}}\n\n',
        'data: {"choices":[{},{}]}\n\n',
    ],
)
def test_failures_retain_partial_raw_events(stream):
    with pytest.raises(StreamFailure) as caught:
        runner(stream).generate("fixture", seed=7)
    assert caught.value.raw_events
    assert caught.value.request_end_s >= caught.value.request_start_s


def test_http_errors_and_wrong_media_type():
    for status, media in [
        (302, "text/event-stream"),
        (500, "text/event-stream"),
        (200, "application/json"),
    ]:
        with pytest.raises(StreamFailure):
            runner("{}", status, media).generate("fixture", seed=7)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1",
        "http://api.example.com",
        "http://user:password@localhost",
        "http://localhost?route=remote",
        "http://localhost/v1",
        "http://localhost#fragment",
    ],
)
def test_external_or_ambiguous_endpoints_rejected(endpoint):
    with pytest.raises(ValueError):
        LocalStreamingRunner(endpoint, "fixture")


def test_invalid_request_and_model_fail_before_network():
    with pytest.raises(ValueError):
        LocalStreamingRunner("http://localhost", " ")
    r = LocalStreamingRunner("http://localhost", "fixture")
    with pytest.raises(ValueError):
        r.generate(" ")
    with pytest.raises(ValueError):
        r.generate("fixture", max_tokens=0)


def test_network_interruption_retains_unterminated_sse_data():
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"choices": []}\n'
            raise httpx.ReadError("fixture disconnect")

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Interrupted()
        )
    )
    r = LocalStreamingRunner("http://localhost", "fixture", transport=transport)
    with pytest.raises(StreamFailure) as caught:
        r.generate("fixture")
    assert caught.value.raw_events == ('{"choices": []}',)
