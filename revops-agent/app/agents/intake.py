"""
Intake Agent — first stage of the RevOps workflow.

Responsibilities:
  - Load raw lead data from a JSON file or a list of dicts
  - Validate each record against the RawLead schema
  - Normalize fields (strip whitespace, lowercase email)
  - Flag incomplete leads (missing last_activity_date)
  - Return ValidatedLead list + AgentTrace

Does NOT call any LLM. All logic is deterministic Python.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.models.schemas import (
    RawLead, ValidatedLead, AgentTrace, AgentStatus
)


def _normalize_raw(data: dict) -> dict:
    """Clean a raw lead dict before Pydantic validation."""
    cleaned = {}
    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip()
        cleaned[key] = value

    if "contact_email" in cleaned and isinstance(cleaned["contact_email"], str):
        cleaned["contact_email"] = cleaned["contact_email"].lower()

    if cleaned.get("last_activity_date") == "":
        cleaned["last_activity_date"] = None

    return cleaned


def _build_validated_lead(raw: RawLead) -> ValidatedLead:
    """Convert a valid RawLead into a ValidatedLead with warnings."""
    is_incomplete = raw.last_activity_date is None
    validation_notes: list[str] = []

    if is_incomplete:
        validation_notes.append(
            "Missing last_activity_date — will be treated as inactive"
        )
    if raw.days_in_current_stage > 60:
        validation_notes.append(
            f"Lead has been in {raw.deal_stage} for {raw.days_in_current_stage} days — may be stale"
        )
    if raw.deal_value_usd == 0:
        validation_notes.append("Deal value is zero — verify with AE")

    return ValidatedLead(
        id=raw.id,
        company=raw.company,
        contact_name=raw.contact_name,
        contact_email=raw.contact_email,
        deal_value_usd=raw.deal_value_usd,
        deal_stage=raw.deal_stage,
        last_activity_date=raw.last_activity_date,
        days_in_current_stage=raw.days_in_current_stage,
        notes=raw.notes,
        is_incomplete=is_incomplete,
        validation_notes=validation_notes,
        validated_at=datetime.now(timezone.utc),
    )


def run_intake_agent(
    raw_data: list[dict],
) -> tuple[list[ValidatedLead], AgentTrace]:
    """Process a list of raw lead dicts and return validated leads plus a trace."""
    start_time = datetime.now(timezone.utc)
    validated: list[ValidatedLead] = []
    skipped = 0
    errors: list[str] = []

    for item in raw_data:
        cleaned = _normalize_raw(item)
        try:
            raw_lead = RawLead.model_validate(cleaned)
        except ValidationError as e:
            skipped += 1
            errors.append(
                f"Skipped lead {item.get('id', 'unknown')}: {e.error_count()} validation error(s)"
            )
            continue

        validated_lead = _build_validated_lead(raw_lead)
        validated.append(validated_lead)

    end_time = datetime.now(timezone.utc)

    trace = AgentTrace(
        agent_name="intake_agent",
        status=AgentStatus.SUCCESS if validated else AgentStatus.FAILURE,
        start_time=start_time,
        end_time=end_time,
        tokens_used=None,
        retry_count=0,
        error_message="; ".join(errors) if errors else None,
    )

    return validated, trace


def load_leads_from_file(path: str | Path) -> list[dict]:
    """Load raw lead dicts from a JSON file. Raises FileNotFoundError or
    json.JSONDecodeError if the file is missing or malformed."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    from pathlib import Path
    from rich.console import Console
    from rich.table import Table

    console = Console()
    raw = load_leads_from_file(Path("data/sample_leads.json"))
    leads, trace = run_intake_agent(raw)

    table = Table(title="Intake Agent Results")
    table.add_column("ID", style="cyan")
    table.add_column("Company")
    table.add_column("Incomplete", style="yellow")
    table.add_column("Warnings")

    for lead in leads:
        table.add_row(
            lead.id,
            lead.company,
            str(lead.is_incomplete),
            str(len(lead.validation_notes))
        )

    console.print(table)
    console.print(f"\n[bold]Trace:[/bold] status={trace.status.value}, "
                  f"latency={trace.latency_ms:.1f}ms, "
                  f"skipped leads logged in error_message")
    if trace.error_message:
        console.print(f"[red]Errors:[/red] {trace.error_message}")
