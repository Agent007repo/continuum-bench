.PHONY: setup test analyze docs report bench-smoke bench-full
setup:
	uv sync --frozen
test:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src
	uv run pytest --cov=continuum_bench --cov-report=term-missing --cov-report=xml --junitxml=results/raw/software-checks/junit.xml
	uv run python scripts/integrity.py
analyze:
	uv run python scripts/analyze.py
docs:
	uv run mkdocs build --strict
report:
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error report.tex
bench-smoke:
	uv run pytest tests/scenarios -q
bench-full:
	uv run cbench full
