# Reproduce

Use Python 3.12 and uv. Run `make setup`, then `make test`. This installs from the committed lockfile. `make analyze` regenerates the honest pending-state artefact. `make docs` builds the documentation locally. `make report` requires `pdflatex` and compiles a report skeleton, not a completed research report.

Do not run paid calls in this milestone. Never paste keys into chat or commit `.env`. Install the gitleaks binary and run `gitleaks git --redact`; the workflow contains the same history-scanning gate. Local gitleaks execution is separately reported.

Before publication we require a clean-clone check on macOS, a successful hosted workflow, verified literature and material licences, human review, and a completed report. None is inferred from a Linux test pass.
