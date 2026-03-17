"""
RevOps Workflow — Agno Step-based Workflow orchestrating the 4-agent pipeline.

Pipeline (4 sequential steps):
  Intake → Classification → Action → Review

Design:
  - Each agent is wrapped as a Step executor function
  - WorkflowState (Pydantic) stored in session_state for type-safe handoffs
  - AgentTrace collected per step for observability
  - Structured JSON log written to outputs/
  - Compatible with Agno Agent OS UI

Note on session_state access (agno 2.5.9):
  StepInput carries state via step_input.workflow_session.session_data,
  not a top-level session_state attribute. _get_sd() / _set_sd() abstract
  this so step functions remain readable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agno.workflow.workflow import Workflow
from agno.workflow.step import Step, StepInput, StepOutput  # type: ignore[attr-defined]

from app.models.schemas import (
    WorkflowState, RawLead,
)
from app.agents.intake import run_intake_agent
from app.agents.classification import run_classification_agent
from app.agents.action import run_action_agent
from app.agents.review import run_review_agent

LOGS_DIR = Path("outputs")


# ── Session-data helpers ───────────────────────────────────────────────────────
# In agno 2.5.9, step-level shared state lives at:
#   step_input.workflow_session.session_data  (Dict[str, Any] | None)
# These two helpers centralise access so step functions stay clean.

def _get_sd(step_input: StepInput) -> dict[str, Any]:
    """Return the mutable session_state dict, initialising it if needed.

    In agno 2.5.9, workflow.session_state is stored at:
        session.session_data["session_state"]
    so we return that nested dict (not session_data itself).
    """
    ws = getattr(step_input, "workflow_session", None)
    if ws is None:
        # Fallback: use additional_data as a state carrier
        if step_input.additional_data is None:
            step_input.additional_data = {}
        return step_input.additional_data
    if ws.session_data is None:
        ws.session_data = {}
    if "session_state" not in ws.session_data:
        ws.session_data["session_state"] = {}
    return ws.session_data["session_state"]


def _set_sd(step_input: StepInput, key: str, value: Any) -> None:
    """Write a key into session_data."""
    _get_sd(step_input)[key] = value


# ── Module-level helpers ───────────────────────────────────────────────────────

def _is_parseable(raw: dict) -> bool:
    """
    Quick pre-check: return True if the dict has minimum required keys.
    Filters completely malformed records before WorkflowState init.
    """
    required = {
        "id", "company", "contact_name", "contact_email",
        "deal_value_usd", "deal_stage", "days_in_current_stage",
    }
    return required.issubset(raw.keys())


def _save_log(state: WorkflowState) -> Path:
    """
    Serialize WorkflowState to a structured JSON log file.
    Writes to outputs/workflow_{workflow_id}_{timestamp}.json
    """
    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = LOGS_DIR / f"workflow_{state.workflow_id[:8]}_{timestamp}.json"

    payload = {
        "workflow_id": state.workflow_id,
        "started_at": state.started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "total_leads": len(state.raw_leads),
        "traces": [
            {
                "agent": t.agent_name,
                "status": t.status.value,
                "latency_ms": round(t.latency_ms, 1),
                "tokens": t.tokens_used,
                "retries": t.retry_count,
                "error": t.error_message,
            }
            for t in state.traces
        ],
        "health_summary": (
            state.report.health_summary.model_dump()
            if state.report else None
        ),
        "total_workflow_latency_ms": round(
            sum(t.latency_ms for t in state.traces), 1
        ),
        "total_tokens": sum(
            t.tokens_used for t in state.traces if t.tokens_used
        ),
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return filename


def _get_or_init_state(step_input: StepInput) -> WorkflowState:
    """
    Retrieve WorkflowState from session_data.
    Raises RuntimeError if the intake step has not run yet.
    """
    sd = _get_sd(step_input)
    raw = sd.get("workflow_state")
    if raw is None:
        raise RuntimeError("WorkflowState not found in session_data")
    if isinstance(raw, WorkflowState):
        return raw
    return WorkflowState.model_validate(raw)


def _save_state(step_input: StepInput, state: WorkflowState) -> None:
    """Serialise and write WorkflowState back into session_data."""
    _set_sd(step_input, "workflow_state", state.model_dump(mode="json"))


# ── Step executors ─────────────────────────────────────────────────────────────

def intake_step_fn(step_input: StepInput) -> StepOutput:
    """
    Step 1: Parse raw leads from session_data, validate and normalise.
    Initialises WorkflowState in session_data for downstream steps.
    """
    try:
        sd = _get_sd(step_input)
        raw_data = sd.get("raw_leads", [])

        # run_intake_agent handles per-lead validation internally
        # (catches ValidationError per lead, skips bad ones)
        validated, trace = run_intake_agent(raw_data)

        # Build WorkflowState from successfully validated leads
        raw_leads = [
            RawLead(
                id=v.id, company=v.company, contact_name=v.contact_name,
                contact_email=v.contact_email, deal_value_usd=v.deal_value_usd,
                deal_stage=v.deal_stage, last_activity_date=v.last_activity_date,
                days_in_current_stage=v.days_in_current_stage, notes=v.notes,
            )
            for v in validated
        ]
        state = WorkflowState(raw_leads=raw_leads)
        state.validated_leads = validated
        state.add_trace(trace)

        _set_sd(step_input, "workflow_state", state.model_dump(mode="json"))

        return StepOutput(
            content=(
                f"Intake complete — "
                f"{len(validated)} valid, "
                f"{len(raw_data) - len(validated)} skipped | "
                f"latency: {trace.latency_ms:.0f}ms"
            )
        )
    except Exception as e:
        return StepOutput(content=f"Intake failed: {e}", success=False)


def classification_step_fn(step_input: StepInput) -> StepOutput:
    """
    Step 2: Score and categorise validated leads.
    """
    try:
        state = _get_or_init_state(step_input)

        classified, trace = run_classification_agent(state.validated_leads)
        state.classified_leads = classified
        state.add_trace(trace)

        categories: dict[str, int] = {}
        for cl in classified:
            categories[cl.category.value] = (
                categories.get(cl.category.value, 0) + 1
            )

        _save_state(step_input, state)

        return StepOutput(
            content=(
                f"Classification complete — "
                f"{categories} | "
                f"retries: {trace.retry_count} | "
                f"latency: {trace.latency_ms:.0f}ms | "
                f"tokens: {trace.tokens_used}"
            )
        )
    except Exception as e:
        return StepOutput(content=f"Classification failed: {e}", success=False)


def action_step_fn(step_input: StepInput) -> StepOutput:
    """
    Step 3: Generate next-action plans for classified leads.
    """
    try:
        state = _get_or_init_state(step_input)

        plans, trace = run_action_agent(state.classified_leads)
        state.action_plans = plans
        state.add_trace(trace)

        _save_state(step_input, state)

        return StepOutput(
            content=(
                f"Action complete — "
                f"{len(plans)} action plans | "
                f"retries: {trace.retry_count} | "
                f"latency: {trace.latency_ms:.0f}ms | "
                f"tokens: {trace.tokens_used}"
            )
        )
    except Exception as e:
        return StepOutput(content=f"Action failed: {e}", success=False)


def review_step_fn(step_input: StepInput) -> StepOutput:
    """
    Step 4: Generate operator dashboard and save structured log.
    """
    try:
        state = _get_or_init_state(step_input)

        report, trace = run_review_agent(state.action_plans)
        state.report = report
        state.add_trace(trace)

        _save_state(step_input, state)

        log_path    = _save_log(state)
        total_latency = sum(t.latency_ms for t in state.traces)
        total_tokens  = sum(t.tokens_used for t in state.traces if t.tokens_used)

        return StepOutput(
            content=(
                f"Review complete — "
                f"health score: {report.health_summary.pipeline_health_score}/100 | "
                f"total latency: {total_latency:.0f}ms | "
                f"total tokens: {total_tokens} | "
                f"log: {log_path}\n\n"
                f"{report.markdown_report}"
            )
        )
    except Exception as e:
        return StepOutput(content=f"Review failed: {e}", success=False)


# ── Workflow factory ───────────────────────────────────────────────────────────

def create_revops_workflow() -> Workflow:
    """
    Factory function that creates the RevOps Workflow with 4 sequential steps.
    """
    return Workflow(
        name="RevOps Pipeline",
        description=(
            "Revenue Operations pipeline: validates, classifies, and generates "
            "action plans for sales leads, producing a prioritized operator dashboard."
        ),
        steps=[
            Step(name="Intake",         executor=intake_step_fn),
            Step(name="Classification", executor=classification_step_fn),
            Step(name="Action",         executor=action_step_fn),
            Step(name="Review",         executor=review_step_fn),
        ],
    )


def run_revops_pipeline(raw_leads: list[dict]) -> None:
    """
    Convenience function to create and run the full pipeline.
    Pre-loads raw_leads into session_state, then streams output.

    Usage:
        from app.workflows.revops_workflow import run_revops_pipeline
        run_revops_pipeline(raw_data)
    """
    workflow = create_revops_workflow()
    workflow.session_state = {"raw_leads": raw_leads}
    workflow.print_response(
        "Process sales leads through RevOps pipeline",
        stream=True,
        markdown=True,
    )
