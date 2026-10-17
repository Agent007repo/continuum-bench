# Deviations

No research experiments have been run. Record dated deviations here after freezing a protocol.

## 2026-10-17: Executed design moves to the Mac

Recorded before any Mac measurement. The cloud-runner draft (`configs/2026-10-17-cloud-v1.json`) was never run. The executed design is [`docs/protocols/2026-10-17-mac-v1.md`](docs/protocols/2026-10-17-mac-v1.md): measured component power instead of CPU-time estimates, a Metal device tier and an emulated CPU edge tier, and no executed cloud tier. Items, scoring, splits, routing policies and the H3 wording are unchanged.

## 2026-10-17 22:15 IST: prebuilt Metal wheel instead of a source build

Recorded before any Mac measurement. The source build of llama-cpp-python 0.3.16 failed because the PyPI download timed out on the Mac's network. We use the project's own prebuilt Metal wheel for the same version from its `v0.3.16-metal` GitHub release, pinned by SHA-256 in the protocol config. Same library version; the binary was compiled by the project rather than on the Mac.

## 2026-10-17 22:25 IST: single-turn prompt layout for all models

Recorded before any confirmatory data. In the Mac pilot, Mistral-7B-Instruct-v0.3's embedded chat template raised an error on a separate system message. All models now receive one user message holding the instruction and the question (the same rule the TrustTrace B10 pilot adopted for the same reason). The whole pilot is rerun with this layout; the earlier partial pilot cells (five Qwen configurations, device tier) are discarded because they used the old layout.
