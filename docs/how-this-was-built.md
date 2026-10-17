# How this was built

**Who did what.** Samarth set the research brief, the constraints (one Mac, under an hour of compute, no paid APIs) and the go/no-go decisions, including the choice of the full confirmatory run after the pilot. He ran every measurement on his own MacBook Pro (M1 Max, 64 GB) on 17 October 2026, typing his password into Terminal himself for `powermetrics`. AI coding assistants (Anthropic's Claude) proposed the protocol, wrote the benchmark runner, analysis scripts, tests and report drafts, and checked every reference against Crossref or arXiv. Samarth's final review of the report wording is the last step before release.

**How numbers get into the text.** Every figure in the README, `docs/results.md` and the report is written by `scripts/analyze_mac.py` from the raw per-item records and the `powermetrics` log in `results/mac/`. Nothing is typed in by hand. Each number carries its provenance: measured (device tier), measured on an emulated tier (edge), or characterised from documentation (cloud, sovereignty evidence).

**What changed along the way.** The study first targeted hosted CI runners, then moved to the Mac once a probe showed runners expose no energy counters. Every later change (prebuilt Metal wheel after a download timeout, single-turn prompts after a chat-template error, a discarded and repeated pilot) is dated in [`DEVIATIONS.md`](../DEVIATIONS.md). Thresholds for H3 were set from the pilot and committed before the confirmatory run.

These are independent projects. They are not affiliated with, endorsed by, or built using internal material from TU Delft, TU/e, TNO or any consortium named in them. They use public models, public datasets and original code.
