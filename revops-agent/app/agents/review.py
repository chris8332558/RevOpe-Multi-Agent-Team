"""
Review Agent — fourth and final stage of the RevOps workflow.

Responsibilities:
  - Compute PipelineHealthSummary from ActionPlans (deterministic)
  - Call LLM to generate QA review_notes on action plan consistency
  - Call LLM to generate formatted markdown_report dashboard
  - Assemble and return the final WorkflowReport + AgentTrace

Two LLM calls are used intentionally:
  Call 1 → review_notes (JSON, short, focused on QA logic)
  Call 2 → markdown_report (free text, focused on formatting)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import litellm

from app.models.schemas import (
    ActionPlan, WorkflowReport, PipelineHealthSummary,
    LeadCategory, AgentTrace, AgentStatus
)
from app.utils.llm import get_model_id, get_api_base

MAX_RETRIES = 3


def _compute_health_summary(
    plans: list[ActionPlan],
) -> PipelineHealthSummary:
    """Compute all PipelineHealthSummary fields deterministically from plans."""
    total_leads = len(plans)

    hot_count      = sum(1 for p in plans if p.category == LeadCategory.HOT)
    warm_count     = sum(1 for p in plans if p.category == LeadCategory.WARM)
    cold_count     = sum(1 for p in plans if p.category == LeadCategory.COLD)
    at_risk_count  = sum(1 for p in plans if p.category == LeadCategory.AT_RISK)
    incomplete_count = sum(
        1 for p in plans if "incomplete" in p.score_reasoning.lower()
    )

    total_pipeline_value_usd   = sum(p.deal_value_usd for p in plans)
    at_risk_pipeline_value_usd = sum(
        p.deal_value_usd for p in plans if p.category == LeadCategory.AT_RISK
    )

    if total_leads > 0:
        raw_score = (
            50
            + (hot_count / total_leads) * 30
            - (at_risk_count / total_leads) * 25
            - (cold_count / total_leads) * 15
        )
    else:
        raw_score = 50

    pipeline_health_score = max(0, min(100, int(raw_score)))

    return PipelineHealthSummary(
        total_leads=total_leads,
        hot_count=hot_count,
        warm_count=warm_count,
        cold_count=cold_count,
        at_risk_count=at_risk_count,
        incomplete_count=incomplete_count,
        total_pipeline_value_usd=total_pipeline_value_usd,
        at_risk_pipeline_value_usd=at_risk_pipeline_value_usd,
        pipeline_health_score=pipeline_health_score,
    )


def _call_llm(
    messages: list[dict],
    max_tokens: int = 512,
) -> tuple[str, int | None]:
    """
    Call LiteLLM and return (raw_content_string, tokens_used_or_None).
    Does NOT parse JSON — callers handle parsing.
    """
    kwargs = {
        "model":       get_model_id(),
        "messages":    messages,
        "temperature": 0.2,
        "max_tokens":  max_tokens,
    }
    if get_api_base():
        kwargs["api_base"] = get_api_base()

    response = litellm.completion(**kwargs)
    content  = response.choices[0].message.content.strip()

    tokens = None
    try:
        tokens = response.usage.total_tokens
    except Exception:
        pass

    return content, tokens


def _build_review_notes_prompt(
    plans: list[ActionPlan],
    summary: PipelineHealthSummary,
) -> list[dict]:
    """Build the messages list for the review_notes LLM call."""
    system_msg = (
        "You are a Revenue Operations Manager performing a QA review.\n"
        "Analyze the action plans and pipeline summary, then return a JSON object:\n"
        "{\n"
        '  "review_notes": "2-4 sentences of QA observations"\n'
        "}\n\n"
        "Focus on:\n"
        "- Are action urgency levels consistent with lead categories?\n"
        "- Are at-risk leads getting appropriate escalation?\n"
        "- Any patterns worth flagging to the sales team?\n"
        "- Is the pipeline health score reasonable given the mix?\n\n"
        "Return ONLY the JSON object. No markdown. No extra fields."
    )

    plan_lines = "\n".join(
        f"- {p.company} [{p.category.value}, score={p.priority_score}]: "
        f"{len(p.next_actions)} actions, first due in {p.next_actions[0].due_in_days}d"
        for p in plans
    )

    user_msg = (
        f"Pipeline Health Score: {summary.pipeline_health_score}/100\n"
        f"Total leads: {summary.total_leads}\n"
        f"Hot: {summary.hot_count} | Warm: {summary.warm_count} | "
        f"Cold: {summary.cold_count} | At-risk: {summary.at_risk_count}\n"
        f"Total pipeline value: ${summary.total_pipeline_value_usd:,.0f}\n"
        f"At-risk value: ${summary.at_risk_pipeline_value_usd:,.0f}\n\n"
        f"Action Plans Summary:\n{plan_lines}"
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user",   "content": user_msg},
    ]


def _build_markdown_prompt(
    plans: list[ActionPlan],
    summary: PipelineHealthSummary,
    review_notes: str,
    top_plans: list[ActionPlan],
) -> list[dict]:
    """Build the messages list for the markdown_report LLM call."""
    system_msg = (
        "You are a Revenue Operations analyst. Generate a clean markdown dashboard "
        "report for the operator. Use proper markdown formatting.\n\n"
        "The report must contain these sections in order:\n"
        "1. # RevOps Pipeline Dashboard\n"
        "   - Generated timestamp\n"
        "   - Pipeline Health Score (show as X/100)\n"
        "2. ## Pipeline Summary\n"
        "   - Stats table: Total leads, Hot, Warm, Cold, At-risk\n"
        "   - Total pipeline value and at-risk value\n"
        "3. ## Top Priority Leads\n"
        "   - For each of the top 5 leads: company, score, category, next action\n"
        "4. ## QA Review Notes\n"
        "   - The review_notes text provided\n"
        "5. ## All Action Plans\n"
        "   - For each lead: company, score, category, all actions with due dates\n\n"
        "Use markdown tables where appropriate. Be concise but complete.\n"
        "Return ONLY the markdown text, no JSON wrapping."
    )

    top_plans_text = "\n".join(
        f"  Company: {p.company}\n"
        f"  Score: {p.priority_score} | Category: {p.category.value}\n"
        f"  Actions: " + "; ".join(
            f"{a.description} (due {a.due_in_days}d, {a.owner_role})"
            for a in p.next_actions
        )
        for p in top_plans
    )

    all_plans_text = "\n".join(
        f"  Company: {p.company}\n"
        f"  Score: {p.priority_score} | Category: {p.category.value}\n"
        f"  Actions: " + "; ".join(
            f"{a.description} (due {a.due_in_days}d, {a.owner_role})"
            for a in p.next_actions
        )
        for p in plans
    )

    user_msg = (
        f"Generated at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"Health Summary:\n{json.dumps(summary.model_dump(), indent=2, default=str)}\n\n"
        f"Review Notes: {review_notes}\n\n"
        f"Top Priority Leads:\n{top_plans_text}\n\n"
        f"All Plans:\n{all_plans_text}"
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user",   "content": user_msg},
    ]


def _get_review_notes(
    plans: list[ActionPlan],
    summary: PipelineHealthSummary,
) -> tuple[str, int | None]:
    """
    Returns (review_notes_string, tokens_used).
    Retries up to MAX_RETRIES if JSON parsing fails.
    Falls back to a default string if all retries fail.
    """
    previous_error: str | None = None
    tokens_used: int | None = None

    for _ in range(1, MAX_RETRIES + 1):
        messages = _build_review_notes_prompt(plans, summary)
        if previous_error:
            messages[1]["content"] += (
                f"\n\nPrevious attempt failed: {previous_error}. "
                "Return ONLY a JSON object with key 'review_notes'."
            )
        try:
            content, tokens = _call_llm(messages, max_tokens=256)
            tokens_used = tokens

            # strip markdown fences
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            parsed = json.loads(content)
            notes  = parsed["review_notes"]
            if not notes:
                raise ValueError("review_notes is empty")
            return notes, tokens_used

        except Exception as e:
            previous_error = str(e)
            continue

    # fallback
    return (
        f"QA review unavailable after {MAX_RETRIES} attempts. "
        f"Pipeline health score: {summary.pipeline_health_score}/100. "
        f"Manual review recommended for {summary.at_risk_count} at-risk lead(s).",
        tokens_used,
    )


def _get_markdown_report(
    plans: list[ActionPlan],
    summary: PipelineHealthSummary,
    review_notes: str,
    top_plans: list[ActionPlan],
) -> tuple[str, int | None]:
    """
    Returns (markdown_string, tokens_used).
    Single attempt only — markdown generation rarely fails validation.
    Falls back to a minimal template if LLM call fails.
    """
    try:
        messages = _build_markdown_prompt(plans, summary, review_notes, top_plans)
        content, tokens = _call_llm(messages, max_tokens=1024)
        if not content:
            raise ValueError("Empty markdown response")
        return content, tokens
    except Exception as e:
        fallback = f"""# RevOps Pipeline Dashboard

Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
Pipeline Health Score: {summary.pipeline_health_score}/100

## Pipeline Summary
- Total leads: {summary.total_leads}
- Hot: {summary.hot_count} | Warm: {summary.warm_count}
- Cold: {summary.cold_count} | At-risk: {summary.at_risk_count}
- Total pipeline value: ${summary.total_pipeline_value_usd:,.0f}

## QA Review Notes
{review_notes}

## Note
Full markdown report unavailable: {e}
"""
        return fallback, None


def run_review_agent(
    action_plans: list[ActionPlan],
) -> tuple[WorkflowReport, AgentTrace]:
    """Produce the final WorkflowReport and AgentTrace from all action plans."""
    start_time   = datetime.now(timezone.utc)
    total_tokens = 0

    # Step 1: deterministic health summary
    summary = _compute_health_summary(action_plans)

    # Step 2: top 5 by priority_score descending
    top_plans = sorted(
        action_plans,
        key=lambda p: p.priority_score,
        reverse=True,
    )[:5]

    # Step 3: LLM call 1 — review notes
    review_notes, tokens1 = _get_review_notes(action_plans, summary)
    if tokens1:
        total_tokens += tokens1

    # Step 4: LLM call 2 — markdown report
    markdown_report, tokens2 = _get_markdown_report(
        action_plans, summary, review_notes, top_plans
    )
    if tokens2:
        total_tokens += tokens2

    # Step 5: assemble WorkflowReport
    report = WorkflowReport(
        top_priority_leads = top_plans,
        all_action_plans   = action_plans,
        health_summary     = summary,
        review_notes       = review_notes,
        markdown_report    = markdown_report,
    )

    end_time = datetime.now(timezone.utc)

    trace = AgentTrace(
        agent_name    = "review_agent",
        status        = AgentStatus.SUCCESS,
        start_time    = start_time,
        end_time      = end_time,
        tokens_used   = total_tokens if total_tokens > 0 else None,
        retry_count   = 0,
        error_message = None,
    )

    return report, trace


if __name__ == "__main__":
    from pathlib import Path
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.rule import Rule
    from app.agents.intake import run_intake_agent, load_leads_from_file
    from app.agents.classification import run_classification_agent
    from app.agents.action import run_action_agent

    console = Console()
    console.print("[bold cyan]Running Review Agent smoke test...[/bold cyan]")

    raw           = load_leads_from_file(Path("data/sample_leads.json"))
    leads, _      = run_intake_agent(raw)
    classified, _ = run_classification_agent(leads)
    plans, _      = run_action_agent(classified)
    report, trace = run_review_agent(plans)

    console.print(Rule("[bold]Pipeline Health Summary[/bold]"))
    h = report.health_summary
    console.print(
        f"Health Score: [bold green]{h.pipeline_health_score}/100[/bold green] | "
        f"Hot: {h.hot_count} | Warm: {h.warm_count} | "
        f"Cold: {h.cold_count} | At-risk: {h.at_risk_count}"
    )
    console.print(
        f"Pipeline Value: ${h.total_pipeline_value_usd:,.0f} | "
        f"At-risk Value: ${h.at_risk_pipeline_value_usd:,.0f}"
    )

    console.print(Rule("[bold]QA Review Notes[/bold]"))
    console.print(report.review_notes)

    console.print(Rule("[bold]Markdown Report Preview[/bold]"))
    console.print(Markdown(report.markdown_report))

    console.print(Rule("[bold]Trace[/bold]"))
    console.print(
        f"status={trace.status.value}, "
        f"latency={trace.latency_ms:.1f}ms, "
        f"tokens={trace.tokens_used}"
    )
