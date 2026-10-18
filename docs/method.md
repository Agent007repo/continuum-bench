# Method

The executed design is the Mac protocol frozen on 17 October 2026 (`docs/protocols/2026-10-17-mac-v1.md` and `configs/2026-10-17-mac-v1.json`), with thresholds set from a pilot in `v1.1` before confirmatory data. Departures from the earlier draft are dated in `DEVIATIONS.md`.

**Tiers.** Device: llama.cpp with Metal, all layers on the GPU, 8 threads. Emulated edge: the same Mac's CPU, 4 threads, no GPU. Cloud: characterised from documentation for the sovereignty scorecard, not executed.

**Items and scoring.** 15 pilot and 150 confirmatory items per domain from pinned revisions of PubMedQA and MMLU medicine subjects (healthcare), MMLU computer security, electrical engineering and college computer science (digital industries), and ARC-Challenge (general control). Each item is scored with one forward pass: the answer label with the highest first-token probability mass among the top 20 tokens. This measures ranked knowledge, not free-text answers.

**Energy.** `powermetrics` samples CPU, GPU and ANE power every 200 ms for the whole run, after a 60 s idle baseline. For each cell (configuration, tier, domain), energy per request is the duration-weighted mean combined power of samples wholly inside the cell's main-pass window, minus idle power, times the window length, divided by the number of items. Sample times are reconstructed from cumulative elapsed time anchored to one-second header timestamps, so alignment is uncertain by up to half a second; the effect is reported as a sensitivity. Cells in which system-wide page-outs increased are excluded from latency and energy.

**Statistics.** 95% intervals are 2000-resample percentile bootstraps over items (seed 20261017). Comparisons between policies are paired on the same items.

**Routing.** Items are split per domain into train, validation and test (50/20/30, seeded). The learned router's weights are fit on train; cascade thresholds, the router threshold and the optimiser are tuned on validation; the H3 policy is selected on validation; test is used once. Policy energy is estimated by pricing each item at its configuration's measured per-cell mean, and the selected policy was then also run live on the Mac (`scripts/live_route.py`), alternating with always-7B blocks over three rounds, to measure its energy directly. The oracle uses test labels and is an unattainable upper bound.

**Code.** `scripts/bench_run.py` runs a cell on the Mac; `scripts/analyze_mac.py` computes every derived number, table and figure from `results/mac/`. The library under `src/continuum_bench/` holds the earlier, tested energy and routing building blocks; the Mac analysis re-implements the parts it needs and is covered by its own tests in `tests/test_analyze_mac.py`.
