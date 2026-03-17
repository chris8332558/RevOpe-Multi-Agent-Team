"""
Pydantic v2 schemas for the RevOps pipeline.

Defines the typed contracts between all four agents:
  RawLead → ValidatedLead → ClassifiedLead → ActionPlan → WorkflowReport

Also defines WorkflowState (shared state across the workflow) and
AgentTrace (per-call observability records).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────────


class DealStage(str, Enum):
    PROSPECTING = "prospecting"
    QUALIFICATION = "qualification"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"


class LeadCategory(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    AT_RISK = "at_risk"


class ActionPriority(str, Enum):
    URGENT = "urgent"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AgentStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"


# ── RawLead ───────────────────────────────────────────────────────────────────


class RawLead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    company: str
    contact_name: str
    contact_email: str
    deal_value_usd: float
    deal_stage: DealStage
    last_activity_date: date | None
    days_in_current_stage: int
    notes: str = ""

    @field_validator("deal_value_usd")
    @classmethod
    def deal_value_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"deal_value_usd must be >= 0, got {v}")
        return v

    @field_validator("days_in_current_stage")
    @classmethod
    def days_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"days_in_current_stage must be >= 0, got {v}")
        return v

    @field_validator("contact_email")
    @classmethod
    def email_contains_at(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError(f"contact_email must contain '@', got '{v}'")
        return v


# ── ValidatedLead ─────────────────────────────────────────────────────────────


class ValidatedLead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # RawLead fields (copied explicitly — no inheritance)
    id: str
    company: str
    contact_name: str
    contact_email: str
    deal_value_usd: float
    deal_stage: DealStage
    last_activity_date: date | None
    days_in_current_stage: int
    notes: str = ""

    # Intake Agent additions
    is_incomplete: bool
    validation_notes: list[str]
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("deal_value_usd")
    @classmethod
    def deal_value_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"deal_value_usd must be >= 0, got {v}")
        return v

    @field_validator("days_in_current_stage")
    @classmethod
    def days_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"days_in_current_stage must be >= 0, got {v}")
        return v

    @field_validator("contact_email")
    @classmethod
    def email_contains_at(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError(f"contact_email must contain '@', got '{v}'")
        return v


# ── ClassifiedLead ────────────────────────────────────────────────────────────


class ClassifiedLead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # ValidatedLead fields (copied explicitly — no inheritance)
    id: str
    company: str
    contact_name: str
    contact_email: str
    deal_value_usd: float
    deal_stage: DealStage
    last_activity_date: date | None
    days_in_current_stage: int
    notes: str = ""
    is_incomplete: bool
    validation_notes: list[str]
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Classification Agent additions
    priority_score: int
    category: LeadCategory
    score_reasoning: str
    classified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("deal_value_usd")
    @classmethod
    def deal_value_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"deal_value_usd must be >= 0, got {v}")
        return v

    @field_validator("days_in_current_stage")
    @classmethod
    def days_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"days_in_current_stage must be >= 0, got {v}")
        return v

    @field_validator("contact_email")
    @classmethod
    def email_contains_at(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError(f"contact_email must contain '@', got '{v}'")
        return v

    @field_validator("priority_score")
    @classmethod
    def score_in_range(cls, v: int) -> int:
        if not (0 <= v <= 100):
            raise ValueError(f"priority_score must be between 0 and 100, got {v}")
        return v


# ── NextAction ────────────────────────────────────────────────────────────────


class NextAction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    description: str
    owner_role: str
    due_in_days: int
    priority: ActionPriority


# ── ActionPlan ────────────────────────────────────────────────────────────────


class ActionPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Selective ClassifiedLead fields needed by Review Agent
    lead_id: str
    company: str
    contact_name: str
    contact_email: str
    deal_value_usd: float
    deal_stage: DealStage
    priority_score: int
    category: LeadCategory
    score_reasoning: str

    # Action Agent additions
    next_actions: list[NextAction]
    follow_up_template: str
    planned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("next_actions")
    @classmethod
    def next_actions_not_empty(cls, v: list[NextAction]) -> list[NextAction]:
        if not v:
            raise ValueError("next_actions must contain at least one action")
        return v


# ── PipelineHealthSummary ─────────────────────────────────────────────────────


class PipelineHealthSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_leads: int
    hot_count: int
    warm_count: int
    cold_count: int
    at_risk_count: int
    incomplete_count: int
    total_pipeline_value_usd: float
    at_risk_pipeline_value_usd: float
    pipeline_health_score: int

    @field_validator("pipeline_health_score")
    @classmethod
    def health_score_in_range(cls, v: int) -> int:
        if not (0 <= v <= 100):
            raise ValueError(f"pipeline_health_score must be between 0 and 100, got {v}")
        return v


# ── WorkflowReport ────────────────────────────────────────────────────────────


class WorkflowReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    top_priority_leads: list[ActionPlan]
    all_action_plans: list[ActionPlan]
    health_summary: PipelineHealthSummary
    review_notes: str
    markdown_report: str


# ── AgentTrace ────────────────────────────────────────────────────────────────


class AgentTrace(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agent_name: str
    status: AgentStatus
    start_time: datetime
    end_time: datetime
    tokens_used: int | None = None
    retry_count: int = 0
    error_message: str | None = None

    @computed_field
    @property
    def latency_ms(self) -> float:
        return (self.end_time - self.start_time).total_seconds() * 1000


# ── WorkflowState ─────────────────────────────────────────────────────────────


class WorkflowState(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workflow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_leads: list[RawLead]
    validated_leads: list[ValidatedLead] = []
    classified_leads: list[ClassifiedLead] = []
    action_plans: list[ActionPlan] = []
    report: WorkflowReport | None = None
    traces: list[AgentTrace] = []

    def add_trace(self, trace: AgentTrace) -> None:
        self.traces.append(trace)
