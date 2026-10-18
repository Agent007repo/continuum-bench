# Pre-pilot decisions v0.1, 14 October 2026

Identity: ContinuumBench/pre-pilot/2026-10-14/v0.1. These are assistant-prepared proposals for Samarth's review. They supplement the unchanged draft v0 and do not freeze confirmatory experiments. No pilot, Mac observation, gold labels or results exist.

| Decision | Proposed rule | Freeze requirement |
|---|---|---|
| Initial execution boundary | Device-only pilot after read-only Mac preflight | Hardware/OS, working-set limit, backend and power adapter verified |
| Model inventory | Compare six candidate configurations; filter by observed feasibility | Exact revisions, licence terms, tokenizer/weights/conversion hashes; no untested memory-fit claim |
| Tasks and splits | Three target sectors plus a general QA control | Verified rights and deterministic sampling; pilot/confirmatory item sets disjoint |
| Repetitions and thermal order | Preserve draft's five repetitions and separate warm-up; block and randomise order | Seed, block schedule, thermal/swapping exclusion and cooldown rule committed before collection |
| Energy | Retain raw component samples; align monotonic request clock; stratify by provenance | Channel coverage, idle windows, sampling/gap caps and clock adapter verified |
| Performance | Separate queue/observable request latency from true first-token latency | Streaming adapter and timestamp definitions verified; do not invent TTFT from non-streaming calls |
| Sovereignty | Keep licence, operator jurisdiction, execution location and retention as separate source assertions | Unknown residency remains unknown; vendor name alone grants no residency score |
| Routing | Use only prior train/validation estimates; retain held-out quality for scoring | Explicit parameter-size inventory and disjoint fitting/calibration/test records |
| Thresholds | X energy reduction and Y quality loss remain unset | Select from separate pilot feasibility; commit immutable v1 before confirmatory data |
| Remote spending | Paid providers remain disabled and no special-category upload is proposed | Explicit allowed boundary and combined EUR25 limit would still apply |

The current local HTTP runner is non-streaming and localhost-only. Existing synthetic tests validate software calculations, not these measurement decisions. Docker on the same Mac remains an emulation; it cannot establish independent edge-hardware performance. API energy may be a source-backed estimate later, never a device measurement. Confirmatory collection stays blocked until the complete new v1 and manifests are committed. Future changes require a new dated document and explicit deviation record.
