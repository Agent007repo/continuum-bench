# ContinuumBench

We build a measurement-first foundation for auditable model placement across device, emulated edge and cloud tiers. Quality, latency, energy and data-boundary constraints remain separate. This independent project is motivated by the TU Delft vacancy and f-inference's public computing-continuum objective. It has no measured model findings yet.

```bash
make setup
make test
uv run cbench smoke
make analyze
```

The smoke command writes a labelled synthetic record. It does not load a model or measure energy. [Method](docs/method.md), [limitations](docs/limitations.md), [protocol draft](PREREGISTRATION.md), [Mac preflight](docs/RUNBOOK_full_benchmark.md), [source register](docs/sources.json), [report skeleton](paper/report.tex), [status](STATUS.md).

## Current evidence

The initial library integrates bracketed power samples, rejects sampling gaps, preserves energy provenance, checks routing constraints and refuses unverified sovereignty evidence. Tests use synthetic fixtures. Actual metering adapters, pilots, model selection and confirmatory experiments are pending. `make bench-full` deliberately fails until the prerequisites are implemented and reviewed.

## How this was built

AI coding assistants produced this foundation from Samarth's research brief. His Mac measurements, calibration labels, design review and final wording review are pending. These independent projects have no affiliation with or endorsement from TU Delft, TU/e, TNO, f-inference or LLM4LM and use no internal material.

## Related work by the same author

TrustTrace studies requirements and architectural evidence in an authored logistics case. Companion repository: https://github.com/Agent007repo/trusttrace. The sovereignty scorecard is a proposed instrument; neither project currently supplies measured cross-project evidence.
