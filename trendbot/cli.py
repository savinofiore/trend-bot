"""Command-line interface: ``trendbot run | reconcile | report``."""

from __future__ import annotations

import logging
import os
import sys

import typer

from trendbot.config import RuntimeSettings
from trendbot.execution.engine import ExecutionEngine
from trendbot.execution.reconciler import reconcile
from trendbot.wiring import build_deps

app = typer.Typer(add_completion=False, help="Trend-following execution engine.")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _resolve_dry_run(dry_run: bool | None) -> bool:
    """Env is the default; an explicit --dry-run/--no-dry-run flag overrides it."""
    settings = RuntimeSettings.from_env()
    if dry_run is None:
        return settings.dry_run
    if dry_run is False and os.getenv("TRENDBOT_NON_INTERACTIVE") != "1":
        typer.confirm("Disable dry-run and send REAL orders?", abort=True)
    return dry_run


@app.command()
def run(
    dry_run: bool = typer.Option(None, "--dry-run/--no-dry-run", help="Override DRY_RUN env."),
    once: bool = typer.Option(False, "--once", help="Run a single cycle and exit."),
) -> None:
    """Run the execution loop (or a single cycle with --once)."""
    base = RuntimeSettings.from_env()
    settings = RuntimeSettings(
        dry_run=_resolve_dry_run(dry_run),
        testnet=base.testnet,
        reconcile_interval_sec=base.reconcile_interval_sec,
        post_only_timeout_sec=base.post_only_timeout_sec,
        idle_poll_sec=base.idle_poll_sec,
        halt_file=base.halt_file,
    )
    engine = ExecutionEngine(build_deps(settings))
    engine.install_signal_handlers()
    sys.exit(engine.run(once=once))


@app.command("reconcile")
def reconcile_cmd() -> None:
    """Print exchange vs stored divergences. Never trades. Always safe."""
    deps = build_deps(RuntimeSettings.from_env())
    positions = deps.client.fetch_positions()
    divergences = reconcile(positions, {})
    typer.echo(f"exchange positions: {len(positions)}")
    for symbol, pos in positions.items():
        typer.echo(f"  {symbol}: qty={pos.qty} avg={pos.avg_price}")
    for div in divergences:
        typer.echo(f"DIVERGENCE {div}")


@app.command()
def report(date: str = typer.Option(None, "--date", help="YYYY-MM-DD; defaults to today.")) -> None:
    """Recompute and send the daily report (useful for backfill)."""
    deps = build_deps(RuntimeSettings.from_env())
    positions = deps.client.fetch_positions()
    equity = deps.client.fetch_wallet_balance().total_equity
    lines = [f"Daily report {date or 'today'}", f"equity={equity}"]
    lines += [f"{s}: {p.qty}" for s, p in positions.items()]
    deps.notifier.send("\n".join(lines))
    typer.echo("\n".join(lines))


if __name__ == "__main__":
    app()
