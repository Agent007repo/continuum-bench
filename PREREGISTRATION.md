# ContinuumBench preregistration draft v0

Prepared 2026-10-13. Status: NOT FROZEN FOR FULL EXPERIMENTS. This file is retained as the pre-pilot design. Freeze a new immutable v1 after pilot review and before any confirmatory measurement; log deviations separately. The CLI refuses full runs in this state.

RQ1: What quality, latency, energy and memory trade-offs occur across tested local model configurations on the M1 Max?

RQ2: How sensitive are deployment rankings to a proposed sovereignty instrument's dimensions and weights?

RQ3: Which placement policies meet quality, latency and data-boundary constraints while reducing local measured energy relative to always-largest local inference?

Proposed design: three target domains and a general control, stratified item sampling, five repetitions per model/item/configuration and a separate warm-up. Bootstrap by item, preserving repeated-measure clusters, and report paired effect sizes, medians and p95. Energy populations must remain stratified by provenance. API energy is never treated as measured. Do not use the proposed sovereignty score as a legal determination.

Pilot-only work will estimate feasibility and choose a practical energy-reduction threshold X and allowed quality-loss threshold Y before freezing v1. Neither threshold has been chosen or measured. Use disjoint pilot and confirmatory item sets. Freeze exact model revisions, licences, quantisation, context/output lengths, sampling intervals, idle subtraction, missing-sample handling, thermal exclusion, swapping detection and analysis code before confirmatory collection.

Exclusion plan to finalise: any swapping, missing power samples beyond the allowed gap, model errors and thermal violations are recorded with reasons; no cherry-picking of slow runs. Randomise or block configuration order to limit thermal confounding. No remote inference for special-category data without an explicitly verified allowed boundary.

Mock energy and mock quality are always synthetic. Package power is a device component measurement, not wall energy; absence of CPU/GPU/ANE coverage must be recorded. Cloud residency, operator jurisdiction and data retention are separate assertions requiring source-backed verification.

Full experiments are blocked pending the Mac preflight, verified model/dataset inventory, pilot, freeze and metering validation. Current code is a tested foundation, not a complete benchmark harness.
