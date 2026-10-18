# Independent review, 18 October 2026

Before release, a separate AI agent that had not seen the work being produced reviewed this repository as a sceptical supervisor would. It worked on a copy, checked 21 numbers against `results/derived/mac_summary.json` or the raw records (all matched), and confirmed that `make test`, `make analyze`, `make docs` and `make report` pass and that `make analyze` reproduces every generated file byte for byte. Its findings and what was done about them are below.

## Blocking findings and responses

| Finding | Response |
| :--- | :--- |
| The frozen H3 JSON names the baseline as qwen7b-q4 on the edge tier, a tier it never ran on. | Dated erratum in `DEVIATIONS.md`; the frozen file is left as committed. The protocol note, paper and code all used the device tier. |
| Routing energy was called measured, but it is replayed from per-cell means. | README, results page, abstract, figure axis and method text now say estimated, and explain the replay. |
| Only the accuracy interval was reported for H3; the energy interval also crosses its threshold. | Both intervals are reported in percent, and the text says neither clears its threshold. |
| `paper/generated/discussion.tex` was hand-written and contradicted the data (escalation, size of savings, Mistral vs 1.5B). | The discussion is now generated from the analysis output; escalation rates and the paired Mistral vs Qwen 1.5B difference (no difference) are computed. |
| Several pages still described a project without data. | `DEVIATIONS.md`, `IMPORT_LINEAGE.md`, `CITATION.cff`, `docs/method.md`, `docs/reproduce.md` and `docs/research-questions.md` rewritten. `PREREGISTRATION.md` is checksum-pinned and left unchanged; `DEVIATIONS.md` now says it is superseded. |
| Departures from the 13 October draft were not logged. | Logged in one dated entry: repetitions, run order, missing-sample rule, domains, latency constraint and bootstrap type. |
| AI-drafted application material would have been published. | Removed from the repository and kept privately. Vacancy and supervisor-targeting lines removed from `docs/sources.json` and `docs/related-work.md`. |
| The test split favours the small model, which was not disclosed; the H3 candidate rule was unstated. | Per-split differences are reported in the paper, and the candidate rule is logged as an after-the-fact clarification. |

## Other changes made

- Fixed a variable-shadowing bug that recorded the optimiser's choice wrongly in the summary JSON.
- Added tests for the analysis helpers (`tests/test_analyze_mac.py`).
- Added two sensitivity checks: a half-second clock shift (up to about 8% for the 0.5B cells) and apportioning energy by item wall time (H3 saving 24.6%, just under the threshold). Both are reported.
- Redrew the figure as two panels so that full-set configurations and test-split policies are not mixed; added a legend and marked the oracle as unattainable.
- Reworded the swap exclusion as system-wide page-outs and narrowed the edge-tier finding to the two 0.5B configurations with four CPU threads.
- Narrowed "every number is produced by code" to the generated parts, and named the hand-written ones.
- Related work extended with on-device LLM energy, GPU energy measurement, selective prediction and first-token scoring validity; all 36 references verified.

## Not changed, and why

- Thresholds, splits and the selected policy are unchanged: changing them after seeing test results would be worse than reporting their limits.
- A live routed run was not executed; the offline replay is disclosed.
