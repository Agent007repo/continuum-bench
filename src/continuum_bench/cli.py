from pathlib import Path

import typer

from continuum_bench.runners import write_mock

app = typer.Typer()


@app.command()
def smoke(output: Path = Path("results/local/synthetic_smoke.json")) -> None:
    write_mock(output)
    typer.echo(
        f"Synthetic pipeline check written to {output}; no energy or model quality measured."
    )


@app.command()
def full() -> None:
    typer.echo(
        "Full benchmark blocked: Mac preflight, verified materials, pilot, frozen v1 and metering validation required."
    )
    raise typer.Exit(2)
