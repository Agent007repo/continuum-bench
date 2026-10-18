# Related work and verification register

We distinguish reading an abstract from reviewing a complete paper. `sources.json` records which primary pages were opened, the narrow claim supported, and the retrieval date. Failed retrievals support no external claim.

The report's related work covers the energy of AI and of local LLM inference, quantisation, model routing and cascades, confidence calibration, first-token answer scoring, edge and continuum computing, and sovereignty by design. Where a source was read only as an abstract, `sources.json` says so, and the report relies on it for no more than that abstract states.

The bibliography is checked by `scripts/check_citations.py`, which resolves each DOI or arXiv identifier and compares the registered title with the cited one. The latest result is in `results/raw/citation-check.json`.
