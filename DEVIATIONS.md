# Deviations

Dated deviations from the 13 October draft preregistration (`PREREGISTRATION.md`, kept unchanged and checksum-pinned) and from the executed Mac protocol. The executed design is `docs/protocols/2026-10-17-mac-v1.md`; the draft is superseded by it.

## 2026-10-17: Executed design moves to the Mac

Recorded before any Mac measurement. The cloud-runner draft (`configs/2026-10-17-cloud-v1.json`) was never run. The executed design is [`docs/protocols/2026-10-17-mac-v1.md`](docs/protocols/2026-10-17-mac-v1.md): measured component power instead of CPU-time estimates, a Metal device tier and an emulated CPU edge tier, and no executed cloud tier. Items, scoring, splits, routing policies and the H3 wording are unchanged.

## 2026-10-17 22:15 IST: prebuilt Metal wheel instead of a source build

Recorded before any Mac measurement. The source build of llama-cpp-python 0.3.16 failed because the PyPI download timed out on the Mac's network. We use the project's own prebuilt Metal wheel for the same version from its `v0.3.16-metal` GitHub release, pinned by SHA-256 in the protocol config. Same library version; the binary was compiled by the project rather than on the Mac.

## 2026-10-17 22:25 IST: single-turn prompt layout for all models

Recorded before any confirmatory data. In the Mac pilot, Mistral-7B-Instruct-v0.3's embedded chat template raised an error on a separate system message. All models now receive one user message holding the instruction and the question (the same rule the TrustTrace B10 pilot adopted for the same reason). The whole pilot is rerun with this layout; the earlier partial pilot cells (five Qwen configurations, device tier) are discarded because they used the old layout.

## 2026-10-18: Corrections and clarifications recorded after an independent review

Recorded after the confirmatory data were collected and analysed. None changes a result; each corrects or completes the record.

1. **Erratum in the frozen H3 wording.** `configs/2026-10-17-mac-v1.json` and `v1.1.json` name the H3 baseline as "always-largest-local-model (qwen7b-q4, edge)". That tier label was carried over from the cloud draft. qwen7b-q4 runs only on the device tier in the same file, and the protocol note (`docs/protocols/2026-10-17-mac-v1.md`, committed before data), the paper and the analysis code all use qwen7b-q4 on the device tier. The earlier entry above that says the H3 wording is unchanged should be read with this correction. The frozen JSON is left as committed.
2. **Departures from the 13 October draft that were not logged at the time.** The draft proposed five repetitions per model, item and configuration; the executed design scores each item once and replays 10 items per confirmatory cell five times for timing stability. It proposed randomising or blocking configuration order; cells ran in a fixed order (device configurations small to large, then edge), so any thermal drift would fall on the later 7B and edge cells; `pmset` thermal state was logged before every cell and showed no warnings. It proposed a rule for missing power samples beyond an allowed gap; none was implemented, and window coverage was not used to exclude cells. It proposed three target domains plus a control; two target domains plus the control were run, because automotive had no verified, licence-clear, automatically scorable dataset. RQ3 in the draft named latency constraints; H3 has none, and latency is reported but not constrained. The draft proposed a cluster bootstrap for repeated runs; with one scored pass per item, the analysis uses a plain item bootstrap.
3. **H3 candidate set.** The analysis selects the H3 policy among non-oracle routing policies (cascades, learned router, constraint-aware optimiser, static rule), not among single-configuration baselines. The protocol lists the baselines with the routing policies but does not say whether they are candidates. Including them would not change the selection: on validation, always Qwen2.5-1.5B loses more than the 5-point tolerance.
4. **Energy for routing is estimated.** Policy energy is replayed from measured per-cell means, not measured from routed runs, as the protocol's own H3 wording ("estimated energy") says. Earlier README and abstract text called it measured; this is corrected.
5. **Sensitivity checks added after the fact.** Clock alignment (half-second shift of power-sample times) and apportioning cell energy by item wall time instead of evenly are reported in `results/derived/mac_summary.json` under `energy_sensitivity` and `h3_saving_pct_wall_time_apportioned`. Under wall-time apportionment the H3 saving falls just below the 25% threshold; the paper reports this.
6. **Pilot figures typed by hand.** The `pilot_observations` and rationale in `configs/2026-10-17-mac-v1.1.json` were written by hand from the pilot output when the thresholds were set. Pilot accuracy and energy for always Qwen2.5-7B were recomputed from `results/mac/pilot/` during the review and match; the other pilot figures there have not been recomputed.

## 2026-10-18 (afternoon): Live routing validation added

Not in the frozen protocol; added after the confirmatory analysis and after the independent review, to test the offline energy replay. `scripts/live_route.py` loads Qwen2.5-1.5B and Qwen2.5-7B (both 4-bit, GPU) together and runs the 135 test items under always-7B and under the margin cascade with the validation-tuned threshold (0.98, unchanged), alternating in three rounds, with `powermetrics` and a fresh 60 s idle baseline. Nothing was tuned on these runs. Result: a measured saving of 23.3 to 24.8% per round, below the 25% threshold, against 29.3% estimated offline. We therefore report H3 as not supported on measured energy. The run recorded one system-wide page-out over about five minutes. Raw data are in `results/mac/live/`.
