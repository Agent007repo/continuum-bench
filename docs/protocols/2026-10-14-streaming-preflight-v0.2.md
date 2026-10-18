# Streaming and Mac preflight supplement v0.2, 14 October 2026

Identity: ContinuumBench/tooling/2026-10-14/v0.2. This document supplements the unchanged initial protocol and pre-pilot v0.1. It is an implementation proposal awaiting hardware/backend validation and human review. No native Mac inference, metering, pilot or confirmatory experiment has occurred.

## Read-only capability inventory

Run `uv run python scripts/mac_preflight.py` from the repository root on your Mac. It checks Darwin before issuing commands, records OS/Python, free disk, installed memory, hardware model, CPU brand and available powermetrics help. Unsupported commands retain their failure. The output uses exclusive creation under `results/local/`; it cannot overwrite an earlier inventory. It does not query a serial number, invoke sudo, capture power, download weights or call a model. Review home-directory paths before sharing the JSON. Do not share credentials.

The inventory is a prerequisite, not evidence that a model fits memory or that an energy channel is valid. Metal working-set limits, sampler coverage, idle calibration, clock alignment, swapping and thermal behavior still need native checks. This environment cannot produce them.

## Client timing implementation

`continuum_bench.streaming.LocalStreamingRunner` accepts only plain HTTP loopback server roots and uses the existing locked HTTPX dependency. Environment proxy settings and redirects are disabled. It requests one streamed chat completion with explicit model, seed, output cap and temperature. Paid/remote endpoints are rejected by this client.

Request latency starts just before HTTP client setup and ends after the streamed response closes; it includes setup/transport/queue/decode work visible to this client. `ttft_s` is time to **first nonempty content delta observed by the client**, using a monotonic clock. Role-only/empty events do not start that timestamp. This is an observable first-content proxy, not an independently measured backend token timestamp. Empty successful completions have no TTFT. Backend token counts are nullable and are not inferred from text length.

SSE payloads are retained, including partial events on interruption. Only a single choice and `stop`/`length` finish reasons are supported; `length` remains visibly truncated. HTTP errors, malformed data, server errors, post-finish content, absent completion/finish markers and unsupported finish reasons fail with preserved partial events and request bounds. Event recording is bounded; this is not a guarantee against arbitrary oversized network frames. HTTP headers and wire-byte arrival times are not recorded. No automatic retry or resume is implemented.

## Evidence and remaining gates

Tests exercise synthetic HTTP transports and controlled clocks only. They establish parser behavior and timing arithmetic, not model performance, memory suitability, determinism, sovereignty, energy or compatibility with a native server version. The server process, model revision/conversion hashes and tokenizer must be captured in a future runtime manifest. This module is not yet wired into a full trial orchestrator, power sampler or routing experiment. The older non-streaming runner cannot supply TTFT.

Primary implementation references opened on 14 October 2026: [HTTPX streaming documentation](https://www.python-httpx.org/quickstart/#streaming-responses) and [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). These links support interface consultation only; no licence or runtime validation is inferred from them.

Freeze the chosen adapter/version, native calibration, pilot/confirmatory split, thermal/swapping rules, raw-record format and retry/resumption policy in a new v1 before confirmatory collection. Full benchmark collection remains blocked; report skeletons contain no research results.
