# Limitations

**One machine, component power.** All measurements come from one Apple M1 Max. `powermetrics` reports CPU, GPU and ANE power; DRAM, display, fans and power-supply losses are not included, so these are component figures, not wall-plug or lifecycle energy. Energy in a cell is apportioned evenly across its requests.

**Emulated and unexecuted tiers.** The edge tier is the same Mac's CPU with four threads. It says something about CPU versus GPU on this chip, not about real edge servers. The cloud tier was characterised from provider documentation for the sovereignty scorecard and never executed; its energy is unknown.

**Task and scoring.** Items are multiple-choice and yes/no/maybe questions from MMLU, PubMedQA and ARC, scored by first-token label mass. That measures a model's ranked answer, not free-text quality. Automotive has no verified dataset and is a stated gap. Public benchmarks may overlap with training data.

**Exclusions.** Two of 27 cells (qwen1.5b-q4 on the edge tier, two domains) recorded system-wide memory page-outs during the cell and are excluded from latency and energy, as pre-registered. The counter covers the whole machine, so it flags memory pressure, not necessarily the benchmark process. Their accuracy is kept.

**Routing.** The H3 policy met both thresholds on point estimates, but both intervals cross their thresholds; the test split appears easier for the small model than validation, so the test accuracy loss is probably an underestimate; and apportioning energy by item wall time instead of evenly puts the saving just below 25%. Support is tentative at best. The H3 candidate set excluded single-configuration baselines, a rule stated after the fact in `DEVIATIONS.md`. The oracle is an unattainable bound that uses test labels.

**Clock alignment.** Power-sample times are reconstructed with up to half a second of uncertainty. For the short 0.5B cells this moves energy by up to about 8%, more than the choice of idle window does; conclusions about the 7B and edge cells are barely affected.

**Fixed run order.** Configurations ran in a fixed order rather than randomised. No thermal warnings were logged, but any drift would fall on the later cells.

**Sovereignty.** The scorecard is a normative instrument. Its ranking follows from the rubric, which a different organisation could reasonably set differently. No score establishes GDPR compliance or legal independence.

**Routing energy: offline estimate versus live measurement.** All policies were compared by replaying recorded per-item outputs and per-cell energy. Only the selected cascade was then run live (three rounds against always-7B, 18 October). Live, it saved a measured 24%, below both the 25% threshold and the 29% offline estimate, so the replay overstated the saving. The live run was added after the confirmatory analysis and is logged in `DEVIATIONS.md`.
