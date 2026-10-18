# Reproduce

## Analysis (no model, no Mac needed)

Use Python 3.12 and uv from the repository root.

```bash
make setup     # install from the committed lockfile
make test      # lint, format, strict typing, tests, integrity checks
make analyze   # regenerate every derived number, table, figure and generated paragraph
make report    # build paper/report.pdf (needs pdflatex)
```

`make analyze` reads only the committed raw records in `results/mac/` (per-item rows, cell manifests, the `powermetrics` log and run markers).

## Re-running the measurements

This needs an Apple Silicon Mac, the GGUF files pinned in `configs/2026-10-17-mac-v1.json` (repository, revision, file name and SHA-256 for each), `llama-cpp-python` 0.3.16 with Metal (the protocol pins the project's prebuilt wheel by SHA-256), and administrator rights for `powermetrics`.

1. Start power sampling in its own terminal and leave it running:
   `sudo powermetrics --samplers cpu_power,gpu_power,ane_power -i 200 -o powermetrics.txt`
2. Record a 60 s idle baseline with the machine untouched, writing `idle_start` and `idle_end` epoch times to a markers file.
3. Run each cell, for example:

```bash
python scripts/bench_run.py --config qwen7b-q4 --tier device \
  --domains healthcare,digital_industries,general_control \
  --phase confirmatory --protocol configs/2026-10-17-mac-v1.json \
  --models-dir /path/to/models --out results/mac/confirmatory
```

Use `--tier edge` for the CPU tier and `--phase pilot --no-replay` for pilot cells. Each cell writes per-item rows, a timing-replay file and a manifest with its epoch windows, page-out counts and thermal state. Place `powermetrics.txt` and the markers file in `results/mac/`, then run `make analyze`.

Results will differ in detail on other hardware and macOS versions; the protocol records the host used here in `results/mac/host.txt`.

## Safety

No paid API is used. Never commit `.env` or keys; CI runs gitleaks over the full history.
