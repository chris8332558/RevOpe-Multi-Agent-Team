"""
Demo runner — end-to-end RevOps pipeline walkthrough.

Will:
- Load sample leads from data/sample_leads.json
- Run the full Intake → Classification → Action → Review pipeline
- Render a prioritized operator dashboard to the terminal using Rich
- Print per-agent timing and token usage summaries
"""
from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.rule import Rule
from rich.panel import Panel

from app.agents.intake import load_leads_from_file
from app.workflows.revops_workflow import run_revops_pipeline

console = Console()


def main() -> None:
    # ── Section 1: Load data ────────────────────────────────────────────────
    console.print(Panel(
        "[bold cyan]RevOps Multi-Agent Pipeline[/bold cyan]\n"
        "Intake → Classification → Action → Review",
        subtitle="powered by Agno + LiteLLM",
        expand=False,
    ))

    raw = load_leads_from_file(Path("data/sample_leads.json"))
    console.print(f"[dim]Loaded {len(raw)} leads from data/sample_leads.json[/dim]\n")

    # ── Section 2: Run pipeline ─────────────────────────────────────────────
    console.print(Rule("[bold]Pipeline Execution[/bold]"))
    run_revops_pipeline(raw)

    # ── Section 3: Load latest log and render observability table ───────────
    log_files = sorted(Path("outputs").glob("workflow_*.json"))
    if not log_files:
        console.print("[yellow]No log file found in outputs/[/yellow]")
        return
    latest_log = json.loads(log_files[-1].read_text())

    console.print(Rule("[bold]Observability Summary[/bold]"))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Agent")
    table.add_column("Status")
    table.add_column("Latency (ms)", justify="right")
    table.add_column("Tokens",       justify="right")
    table.add_column("Retries",      justify="right")
    table.add_column("Errors")

    for t in latest_log["traces"]:
        status_str = (
            "[green]success[/green]" if t["status"] == "success"
            else "[red]failure[/red]"
        )

        latency_ms = t["latency_ms"]
        latency_str = (
            f"[yellow]{latency_ms:.0f}[/yellow]" if latency_ms > 3000
            else f"{latency_ms:.0f}"
        )

        tokens = t["tokens"]
        tokens_str = "[dim]—[/dim]" if tokens is None else str(tokens)

        retries = t["retries"]
        retries_str = f"[red]{retries}[/red]" if retries > 0 else "[dim]0[/dim]"

        error = t["error"]
        error_str = f"[red]{error}[/red]" if error is not None else "[dim]-[/dim]"

        table.add_row(
            t["agent"],
            status_str,
            latency_str,
            tokens_str,
            retries_str,
            error_str,
        )

    console.print(table)

    console.print(
        f"\n[bold]Total workflow latency:[/bold] "
        f"{latest_log['total_workflow_latency_ms']:.0f}ms"
    )
    console.print(
        f"[bold]Total tokens used:[/bold] "
        f"{latest_log['total_tokens']}"
    )
    console.print(
        f"[bold]Log saved to:[/bold] [dim]{log_files[-1]}[/dim]"
    )

    if latest_log["health_summary"] is not None:
        h = latest_log["health_summary"]
        console.print(
            f"\n[bold]Pipeline health score:[/bold] "
            f"[green]{h['pipeline_health_score']}/100[/green] | "
            f"Hot: {h['hot_count']} | "
            f"Warm: {h['warm_count']} | "
            f"Cold: {h['cold_count']} | "
            f"At-risk: {h['at_risk_count']}"
        )


if __name__ == "__main__":
    main()
