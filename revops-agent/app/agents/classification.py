"""
Classification Agent — second stage of the RevOps workflow.

Responsibilities:
  - Compute a deterministic pre-score from lead fields (no LLM)
  - Call LLM to produce final priority_score (0-100), category, and reasoning
  - Validate LLM output against ClassifiedLead schema
  - Retry up to 3 times if output fails validation (Failure Scenario #2)
  - Fall back to pre-score if all retries exhausted
  - Return ClassifiedLead list + AgentTrace
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pydantic import ValidationError

import litellm

from app.models.schemas import (
    ValidatedLead, ClassifiedLead, LeadCategory,
    AgentTrace, AgentStatus
)
from app.utils.llm import get_model_id, get_api_base

MAX_RETRIES = 3


def _compute_pre_score(lead: ValidatedLead) -> int:
    """Deterministic rule-based score from 0–100. No LLM, no side effects."""
    # A. Deal stage score (max 30 pts)
    stage_scores = {
        "negotiation":   30,
        "proposal":      22,
        "qualification": 14,
        "prospecting":   6,
    }
    a = stage_scores.get(lead.deal_stage.value, 0)

    # B. Deal value score (max 30 pts)
    v = lead.deal_value_usd
    if v >= 100_000:
        b = 30
    elif v >= 50_000:
        b = 22
    elif v >= 20_000:
        b = 14
    elif v >= 5_000:
        b = 8
    else:
        b = 2

    # C. Recency score (max 30 pts)
    if lead.last_activity_date is None:
        c = 0
    else:
        days_since = (date.today() - lead.last_activity_date).days
        if days_since <= 3:
            c = 30
        elif days_since <= 7:
            c = 24
        elif days_since <= 14:
            c = 18
        elif days_since <= 30:
            c = 10
        elif days_since <= 60:
            c = 4
        else:
            c = 0

    # D. Stage velocity penalty (max -10 pts)
    if lead.days_in_current_stage > 45:
        d = -10
    elif lead.days_in_current_stage > 30:
        d = -5
    else:
        d = 0

    return max(0, min(100, a + b + c + d))


def _determine_category(score: int, lead: ValidatedLead) -> LeadCategory:
    """Map a score + lead context to a LeadCategory. First match wins."""
    if score >= 70:
        return LeadCategory.HOT
    if score < 30:
        return LeadCategory.COLD
    if lead.last_activity_date is not None:
        days_since = (date.today() - lead.last_activity_date).days
        if days_since > 30 and lead.deal_value_usd >= 30_000:
            return LeadCategory.AT_RISK
    return LeadCategory.WARM


def _build_classification_prompt(
    lead: ValidatedLead,
    pre_score: int,
    attempt: int,
    previous_error: str | None,
) -> list[dict]:
    """Build the LiteLLM messages list for a single classification call."""
    system_msg = (
        "You are a Revenue Operations analyst. Analyze the sales lead and return "
        "a JSON object with exactly these fields:\n"
        "  - priority_score: integer between 0 and 100 (inclusive)\n"
        "  - category: one of \"hot\", \"warm\", \"cold\", \"at_risk\"\n"
        "  - score_reasoning: one sentence explaining the score\n\n"
        "Rules:\n"
        "  - priority_score MUST be an integer, not a float\n"
        "  - priority_score MUST be between 0 and 100 inclusive\n"
        "  - category MUST be exactly one of: hot, warm, cold, at_risk\n"
        "  - Return ONLY the JSON object, no markdown, no explanation"
    )

    user_msg = (
        f"Lead details:\n"
        f"- Company: {lead.company}\n"
        f"- Contact: {lead.contact_name} ({lead.contact_email})\n"
        f"- Deal value: ${lead.deal_value_usd:,.0f}\n"
        f"- Deal stage: {lead.deal_stage.value}\n"
        f"- Days in current stage: {lead.days_in_current_stage}\n"
        f"- Last activity: {lead.last_activity_date or 'Unknown (incomplete lead)'}\n"
        f"- Incomplete lead: {lead.is_incomplete}\n"
        f"- Notes: {lead.notes or 'None'}\n"
        f"- Validation warnings: {', '.join(lead.validation_notes) or 'None'}\n\n"
        f"Pre-computed rule-based score: {pre_score}/100\n"
        f"Use this as a starting reference, but apply your own judgment."
    )

    if previous_error is not None:
        user_msg += (
            f"\n\nIMPORTANT — Previous attempt {attempt} failed validation with this error:\n"
            f"{previous_error}\n"
            f"You MUST fix this. Return valid JSON only. priority_score must be 0–100."
        )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user",   "content": user_msg},
    ]


def _call_llm_for_classification(
    messages: list[dict],
) -> tuple[dict, int | None]:
    """Call LiteLLM and return (parsed_json_dict, tokens_used_or_None)."""
    kwargs = {
        "model":       get_model_id(),
        "messages":    messages,
        "temperature": 0.1,
        "max_tokens":  256,
    }
    if get_api_base():
        kwargs["api_base"] = get_api_base()

    response = litellm.completion(**kwargs)

    content = response.choices[0].message.content.strip()

    # Strip markdown code fences if present (```json ... ```)
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    parsed = json.loads(content)

    tokens = None
    try:
        tokens = response.usage.total_tokens
    except Exception:
        pass

    return parsed, tokens


def _classify_single_lead(
    lead: ValidatedLead,
) -> tuple[ClassifiedLead, int, int | None]:
    """
    Returns (ClassifiedLead, retry_count, tokens_used).
    Falls back to pre-score if all LLM retries fail.
    """
    pre_score = _compute_pre_score(lead)
    previous_error: str | None = None
    tokens_used: int | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        messages = _build_classification_prompt(lead, pre_score, attempt, previous_error)
        try:
            parsed, tokens = _call_llm_for_classification(messages)
            tokens_used = tokens

            classified = ClassifiedLead(
                **lead.model_dump(),
                priority_score  = int(parsed["priority_score"]),
                category        = parsed["category"],
                score_reasoning = parsed["score_reasoning"],
                classified_at   = datetime.now(timezone.utc),
            )
            return classified, attempt - 1, tokens_used

        except Exception as e:
            previous_error = str(e)
            continue

    # All retries exhausted → deterministic fallback
    category = _determine_category(pre_score, lead)
    fallback = ClassifiedLead(
        **lead.model_dump(),
        priority_score  = pre_score,
        category        = category,
        score_reasoning = (
            f"LLM classification failed after {MAX_RETRIES} attempts. "
            f"Using rule-based score: {pre_score}/100."
        ),
        classified_at   = datetime.now(timezone.utc),
    )
    return fallback, MAX_RETRIES, tokens_used


def run_classification_agent(
    validated_leads: list[ValidatedLead],
) -> tuple[list[ClassifiedLead], AgentTrace]:
    """Classify all validated leads and return results with an AgentTrace."""
    start_time = datetime.now(timezone.utc)
    classified: list[ClassifiedLead] = []
    total_tokens = 0
    total_retries = 0
    errors: list[str] = []

    for lead in validated_leads:
        try:
            result, retries, tokens = _classify_single_lead(lead)
            classified.append(result)
            total_retries += retries
            if tokens:
                total_tokens += tokens
        except Exception as e:
            errors.append(f"Failed to classify {lead.id}: {e}")

    end_time = datetime.now(timezone.utc)

    trace = AgentTrace(
        agent_name    = "classification_agent",
        status        = AgentStatus.SUCCESS if classified else AgentStatus.FAILURE,
        start_time    = start_time,
        end_time      = end_time,
        tokens_used   = total_tokens if total_tokens > 0 else None,
        retry_count   = total_retries,
        error_message = "; ".join(errors) if errors else None,
    )

    return classified, trace


if __name__ == "__main__":
    from pathlib import Path
    from rich.console import Console
    from rich.table import Table
    from app.agents.intake import run_intake_agent, load_leads_from_file

    console = Console()
    console.print("[bold cyan]Running Classification Agent smoke test...[/bold cyan]")

    raw = load_leads_from_file(Path("data/sample_leads.json"))
    leads, intake_trace = run_intake_agent(raw)
    classified, trace = run_classification_agent(leads)

    table = Table(title="Classification Results")
    table.add_column("ID",       style="cyan")
    table.add_column("Company")
    table.add_column("Score",    style="bold")
    table.add_column("Category", style="magenta")
    table.add_column("Reasoning")

    for cl in classified:
        table.add_row(
            cl.id,
            cl.company,
            str(cl.priority_score),
            cl.category.value,
            cl.score_reasoning[:60] + "..."
        )

    console.print(table)
    console.print(
        f"\n[bold]Trace:[/bold] status={trace.status.value}, "
        f"latency={trace.latency_ms:.1f}ms, "
        f"tokens={trace.tokens_used}, "
        f"retries={trace.retry_count}"
    )
