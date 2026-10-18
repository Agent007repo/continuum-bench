# Research questions

**RQ1.** What accuracy, latency, energy and memory trade-offs occur across local model configurations and placement tiers on one Apple M1 Max? Answered by the confirmatory Mac run (six configurations, GPU and emulated CPU edge tiers, 450 items).

**RQ2.** How sensitive are deployment rankings to the dimensions and weights of a sovereignty scorecard? Answered by a six-dimension rubric with cited evidence and 5000 random weightings.

**RQ3.** Can a routing policy cut energy per request without losing much accuracy? Tested as H3: the best non-oracle policy, chosen on validation, saves at least 25% of estimated energy per request versus always using Qwen2.5-7B on the GPU, with at most a 5-point accuracy loss, on held-out test items. Thresholds were set from a disjoint pilot and committed before confirmatory data.

Results are in [results](results.md); the frozen protocol is `docs/protocols/2026-10-17-mac-v1.md` in the repository.
