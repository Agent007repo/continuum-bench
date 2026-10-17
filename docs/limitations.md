# Limitations

**One machine, component power.** All measurements come from one Apple M1 Max. `powermetrics` reports CPU, GPU and ANE power; DRAM, display, fans and power-supply losses are not included, so these are component figures, not wall-plug or lifecycle energy. Energy in a cell is apportioned evenly across its requests.

**Emulated and unexecuted tiers.** The edge tier is the same Mac's CPU with four threads. It says something about CPU versus GPU on this chip, not about real edge servers. The cloud tier was characterised from provider documentation for the sovereignty scorecard and never executed; its energy is unknown.

**Task and scoring.** Items are multiple-choice and yes/no/maybe questions from MMLU, PubMedQA and ARC, scored by first-token label mass. That measures a model's ranked answer, not free-text quality. Automotive has no verified dataset and is a stated gap. Public benchmarks may overlap with training data.

**Exclusions.** Two of 27 cells (qwen1.5b-q4 on the edge tier, two domains) recorded memory page-outs and are excluded from latency and energy, as pre-registered. Their accuracy is kept.

**Routing.** The H3 policy saved energy on point estimates within the tolerance, but the accuracy confidence interval crosses the 5-point tolerance, so support is tentative. The oracle is an unattainable bound that uses test labels.

**Sovereignty.** The scorecard is a normative instrument. Its ranking follows from the rubric, which a different organisation could reasonably set differently. No score establishes GDPR compliance or legal independence.

**Routing was evaluated offline.** Policies were replayed over the recorded per-item outputs and energy of each configuration. No live routed run was executed, so the overhead of loading or switching models at serving time is not measured.
