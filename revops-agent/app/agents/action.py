"""
Action Agent — third stage of the RevOps workflow.

Responsibilities:
  - Receive ClassifiedLead with priority_score and category
  - Call LLM to generate 2-3 specific next_actions with due dates and owners
  - Generate a short follow_up_template (email subject + opening line)
  - Validate that next_actions list is not empty (retry if so)
  - Return ActionPlan list + AgentTrace
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import ValidationError

import litellm

from app.models.schemas import (
    ClassifiedLead, ActionPlan, NextAction,
    ActionPriority, LeadCategory,
    AgentTrace, AgentStatus
)
from app.utils.llm import get_model_id, get_api_base

MAX_RETRIES = 3


def _get_strategy_context(category: LeadCategory) -> str:
    """Return a strategy string for injection into the LLM system prompt."""
    if category == LeadCategory.HOT:
        return (
            "This is a HOT lead. Recommend 2-3 urgent actions within 24-48 hours. "
            "Actions should push toward deal closure. Owner role: AE (Account Executive). "
            "Priority level: urgent or high."
        )
    if category == LeadCategory.AT_RISK:
        return (
            "This is an AT_RISK lead with high value but low engagement. "
            "Recommend 2-3 recovery actions. Escalate to Manager if no response in 48h. "
            "Include at least one action with owner_role='Manager'. "
            "Priority level: urgent or high."
        )
    if category == LeadCategory.WARM:
        return (
            "This is a WARM lead. Recommend 2-3 nurture actions over 7-14 days. "
            "Focus on value demonstration and relationship building. Owner role: SDR. "
            "Priority level: medium or high."
        )
    # COLD
    return (
        "This is a COLD lead. Recommend 2 actions: one re-engagement attempt and "
        "one decision to archive if no response. Timeline: 14-30 days. "
        "Owner role: SDR. Priority level: low or medium."
    )


def _build_action_prompt(
    lead: ClassifiedLead,
    attempt: int,
    previous_error: str | None,
) -> list[dict]:
    """Build the LiteLLM messages list for a single action-plan call."""
    system_msg = (
        "You are a Revenue Operations specialist. Generate a concrete action plan "
        "for the following sales lead.\n\n"
        f"{_get_strategy_context(lead.category)}\n\n"
        "Return a JSON object with exactly these fields:\n"
        "{\n"
        '  "next_actions": [\n'
        "    {\n"
        '      "description": "specific action to take",\n'
        '      "owner_role": "AE | SDR | CSM | Manager",\n'
        '      "due_in_days": <integer, days from today>,\n'
        '      "priority": "urgent | high | medium | low"\n'
        "    }\n"
        "  ],\n"
        '  "follow_up_template": "Subject: ... | Opening: ..."\n'
        "}\n\n"
        "Rules:\n"
        "- next_actions must contain 2 to 3 items, never empty\n"
        "- due_in_days must be a positive integer\n"
        "- priority must be exactly one of: urgent, high, medium, low\n"
        '- follow_up_template must start with "Subject:" and include "| Opening:"\n'
        "- Return ONLY the JSON object, no markdown fences, no explanation"
    )

    user_msg = (
        f"Lead: {lead.company} | {lead.contact_name} ({lead.contact_email})\n"
        f"Deal: ${lead.deal_value_usd:,.0f} | Stage: {lead.deal_stage.value}\n"
        f"Score: {lead.priority_score}/100 | Category: {lead.category.value}\n"
        f"Reasoning: {lead.score_reasoning}\n"
        f"Notes: {lead.notes or 'None'}"
    )

    if previous_error is not None:
        user_msg += (
            f"\n\nIMPORTANT — Attempt {attempt} failed: {previous_error}\n"
            "next_actions must not be empty. Return valid JSON only."
        )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user",   "content": user_msg},
    ]


def _call_llm_for_action(
    messages: list[dict],
) -> tuple[dict, int | None]:
    """Call LiteLLM and return (parsed_json_dict, tokens_used_or_None)."""
    kwargs = {
        "model":       get_model_id(),
        "messages":    messages,
        "temperature": 0.3,
        "max_tokens":  512,
    }
    if get_api_base():
        kwargs["api_base"] = get_api_base()

    response = litellm.completion(**kwargs)
    content = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
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


def _parse_next_actions(raw_actions: list[dict]) -> list[NextAction]:
    """Convert raw LLM action dicts into NextAction models."""
    if not raw_actions:
        raise ValueError("next_actions is empty")

    actions = []
    for item in raw_actions:
        priority = ActionPriority(item["priority"])
        actions.append(NextAction(
            description=item["description"],
            owner_role=item["owner_role"],
            due_in_days=int(item["due_in_days"]),
            priority=priority,
        ))
    return actions


def _build_action_plan_single(
    lead: ClassifiedLead,
) -> tuple[ActionPlan, int, int | None]:
    """
    Returns (ActionPlan, retry_count, tokens_used).
    Raises RuntimeError if all retries fail.
    """
    previous_error: str | None = None
    tokens_used: int | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        messages = _build_action_prompt(lead, attempt, previous_error)
        try:
            parsed, tokens = _call_llm_for_action(messages)
            tokens_used = tokens

            next_actions = _parse_next_actions(parsed.get("next_actions", []))
            follow_up = parsed.get("follow_up_template", "")

            if not follow_up:
                raise ValueError("follow_up_template is empty")

            plan = ActionPlan(
                lead_id            = lead.id,
                company            = lead.company,
                contact_name       = lead.contact_name,
                contact_email      = lead.contact_email,
                deal_value_usd     = lead.deal_value_usd,
                deal_stage         = lead.deal_stage,
                priority_score     = lead.priority_score,
                category           = lead.category,
                score_reasoning    = lead.score_reasoning,
                next_actions       = next_actions,
                follow_up_template = follow_up,
                planned_at         = datetime.now(timezone.utc),
            )
            return plan, attempt - 1, tokens_used

        except (ValidationError, KeyError, ValueError,
                json.JSONDecodeError) as e:
            previous_error = str(e)
            continue

    raise RuntimeError(
        f"Action Agent failed for {lead.company} after {MAX_RETRIES} retries. "
        f"Last error: {previous_error}"
    )


def run_action_agent(
    classified_leads: list[ClassifiedLead],
) -> tuple[list[ActionPlan], AgentTrace]:
    """Generate action plans for all classified leads and return with AgentTrace."""
    start_time = datetime.now(timezone.utc)
    plans: list[ActionPlan] = []
    total_tokens = 0
    total_retries = 0
    errors: list[str] = []

    for lead in classified_leads:
        try:
            plan, retries, tokens = _build_action_plan_single(lead)
            plans.append(plan)
            total_retries += retries
            if tokens:
                total_tokens += tokens
        except RuntimeError as e:
            errors.append(str(e))

    end_time = datetime.now(timezone.utc)

    trace = AgentTrace(
        agent_name    = "action_agent",
        status        = AgentStatus.SUCCESS if plans else AgentStatus.FAILURE,
        start_time    = start_time,
        end_time      = end_time,
        tokens_used   = total_tokens if total_tokens > 0 else None,
        retry_count   = total_retries,
        error_message = "; ".join(errors) if errors else None,
    )

    return plans, trace


if __name__ == "__main__":
    from pathlib import Path
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from app.agents.intake import run_intake_agent, load_leads_from_file
    from app.agents.classification import run_classification_agent

    console = Console()
    console.print("[bold cyan]Running Action Agent smoke test...[/bold cyan]")

    raw = load_leads_from_file(Path("data/sample_leads.json"))
    leads, _      = run_intake_agent(raw)
    classified, _ = run_classification_agent(leads)
    plans, trace  = run_action_agent(classified)

    for plan in plans:
        actions_text = "\n".join(
            f"  [{a.priority.value.upper()}] {a.description} "
            f"(due: {a.due_in_days}d, owner: {a.owner_role})"
            for a in plan.next_actions
        )
        console.print(Panel(
            f"[bold]{plan.company}[/bold] | "
            f"Score: {plan.priority_score} | "
            f"Category: [magenta]{plan.category.value}[/magenta]\n\n"
            f"[yellow]Actions:[/yellow]\n{actions_text}\n\n"
            f"[blue]Follow-up:[/blue] {plan.follow_up_template}",
            title=plan.lead_id,
            expand=False
        ))

    console.print(
        f"\n[bold]Trace:[/bold] status={trace.status.value}, "
        f"latency={trace.latency_ms:.1f}ms, "
        f"tokens={trace.tokens_used}, "
        f"retries={trace.retry_count}"
    )
