"""
Tests for the RevOps multi-agent pipeline.

A. Unit tests — pure Python, no LLM calls, fast
B. Integration smoke test — runs full pipeline with real LLM

Run unit tests only:   pytest tests/test_workflow.py -m "not integration" -v
Run integration test:  pytest tests/test_workflow.py -m integration -v
"""
from __future__ import annotations

import json
import pytest
from datetime import date, datetime
from pathlib import Path

from app.models.schemas import (
    RawLead, ValidatedLead, ClassifiedLead, ActionPlan,
    NextAction, PipelineHealthSummary, WorkflowState,
    AgentTrace, AgentStatus, DealStage, LeadCategory, ActionPriority,
)
from app.agents.intake import run_intake_agent, load_leads_from_file, _normalize_raw
from app.agents.classification import _compute_pre_score, _determine_category
from app.agents.review import _compute_health_summary
from app.workflows.revops_workflow import _is_parseable, create_revops_workflow


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_raw_leads() -> list[dict]:
    """Load the real sample_leads.json file."""
    return load_leads_from_file(Path("data/sample_leads.json"))


@pytest.fixture
def minimal_valid_lead() -> dict:
    return {
        "id": "test_001",
        "company": "Test Corp",
        "contact_name": "Jane Doe",
        "contact_email": "jane@testcorp.com",
        "deal_value_usd": 50000,
        "deal_stage": "proposal",
        "last_activity_date": str(date.today()),
        "days_in_current_stage": 10,
        "notes": "Good prospect",
    }


@pytest.fixture
def incomplete_lead() -> dict:
    return {
        "id": "test_002",
        "company": "Ghost Corp",
        "contact_name": "John Ghost",
        "contact_email": "john@ghost.com",
        "deal_value_usd": 30000,
        "deal_stage": "qualification",
        "last_activity_date": None,
        "days_in_current_stage": 25,
        "notes": "",
    }


@pytest.fixture
def malformed_lead() -> dict:
    """Missing required fields — should be skipped by Intake Agent."""
    return {
        "id": "bad_001",
        "company": "Bad Corp",
    }


# ── A. Schema validation tests ───────────────────────────────────────────────


class TestSchemas:

    def test_raw_lead_valid(self, minimal_valid_lead):
        lead = RawLead.model_validate(minimal_valid_lead)
        assert lead.id == "test_001"
        assert lead.deal_stage == DealStage.PROPOSAL

    def test_raw_lead_rejects_negative_deal_value(self, minimal_valid_lead):
        minimal_valid_lead["deal_value_usd"] = -100
        with pytest.raises(Exception):
            RawLead.model_validate(minimal_valid_lead)

    def test_raw_lead_rejects_invalid_email(self, minimal_valid_lead):
        minimal_valid_lead["contact_email"] = "notanemail"
        with pytest.raises(Exception):
            RawLead.model_validate(minimal_valid_lead)

    def test_classified_lead_rejects_score_over_100(self, minimal_valid_lead):
        """Failure Scenario #2 guard — score must be 0-100."""
        raw = RawLead.model_validate(minimal_valid_lead)
        with pytest.raises(Exception):
            ClassifiedLead(
                **raw.model_dump(),
                priority_score=150,
                category=LeadCategory.HOT,
                score_reasoning="test",
                classified_at=datetime.utcnow(),
                is_incomplete=False,
                validation_notes=[],
                validated_at=datetime.utcnow(),
            )

    def test_action_plan_rejects_empty_next_actions(self, minimal_valid_lead):
        raw = RawLead.model_validate(minimal_valid_lead)
        with pytest.raises(Exception):
            ActionPlan(
                lead_id=raw.id,
                company=raw.company,
                contact_name=raw.contact_name,
                contact_email=raw.contact_email,
                deal_value_usd=raw.deal_value_usd,
                deal_stage=raw.deal_stage,
                priority_score=75,
                category=LeadCategory.HOT,
                score_reasoning="test",
                next_actions=[],
                follow_up_template="Subject: Hi | Opening: Hi there",
            )

    def test_agent_trace_latency_computed(self):
        start = datetime(2026, 1, 1, 12, 0, 0)
        end = datetime(2026, 1, 1, 12, 0, 2)
        trace = AgentTrace(
            agent_name="test_agent",
            status=AgentStatus.SUCCESS,
            start_time=start,
            end_time=end,
            tokens_used=100,
        )
        assert abs(trace.latency_ms - 2000.0) < 1.0


# ── B. Intake Agent tests ────────────────────────────────────────────────────


class TestIntakeAgent:

    def test_normalize_strips_whitespace(self):
        raw = {"company": "  Acme Corp  ", "contact_email": "USER@ACME.COM"}
        result = _normalize_raw(raw)
        assert result["company"] == "Acme Corp"
        assert result["contact_email"] == "user@acme.com"

    def test_normalize_empty_date_becomes_none(self):
        raw = {"last_activity_date": ""}
        result = _normalize_raw(raw)
        assert result["last_activity_date"] is None

    def test_normalize_does_not_mutate_input(self):
        raw = {"contact_email": "USER@TEST.COM"}
        original = raw.copy()
        _normalize_raw(raw)
        assert raw == original

    def test_intake_processes_valid_leads(self, sample_raw_leads):
        leads, trace = run_intake_agent(sample_raw_leads)
        assert len(leads) >= 1
        assert trace.status == AgentStatus.SUCCESS
        assert trace.tokens_used is None

    def test_intake_flags_incomplete_lead(self, minimal_valid_lead, incomplete_lead):
        leads, _ = run_intake_agent([minimal_valid_lead, incomplete_lead])
        incomplete = [l for l in leads if l.is_incomplete]
        assert len(incomplete) == 1
        assert incomplete[0].id == "test_002"

    def test_intake_skips_malformed_lead(self, minimal_valid_lead, malformed_lead):
        """Failure Scenario #1 — malformed input is skipped, not crashed."""
        leads, trace = run_intake_agent([minimal_valid_lead, malformed_lead])
        ids = [l.id for l in leads]
        assert "test_001" in ids
        assert "bad_001" not in ids
        assert trace.error_message is not None

    def test_intake_empty_input_returns_empty(self):
        leads, trace = run_intake_agent([])
        assert leads == []
        assert trace.status == AgentStatus.FAILURE


# ── C. Classification scoring tests (deterministic, no LLM) ──────────────────


class TestClassificationScoring:

    def _make_validated_lead(self, **kwargs) -> ValidatedLead:
        """Helper to build a ValidatedLead with overrideable defaults."""
        defaults = dict(
            id="t1", company="X", contact_name="Y",
            contact_email="y@x.com", deal_value_usd=50000,
            deal_stage=DealStage.PROPOSAL,
            last_activity_date=date.today(),
            days_in_current_stage=10,
            notes="", is_incomplete=False,
            validation_notes=[], validated_at=datetime.utcnow(),
        )
        defaults.update(kwargs)
        return ValidatedLead(**defaults)

    def test_pre_score_is_deterministic(self, sample_raw_leads):
        leads, _ = run_intake_agent(sample_raw_leads)
        scores1 = [_compute_pre_score(l) for l in leads]
        scores2 = [_compute_pre_score(l) for l in leads]
        assert scores1 == scores2

    def test_pre_score_in_valid_range(self, sample_raw_leads):
        leads, _ = run_intake_agent(sample_raw_leads)
        for lead in leads:
            score = _compute_pre_score(lead)
            assert 0 <= score <= 100, f"{lead.id} score {score} out of range"

    def test_hot_lead_scores_high(self):
        lead = self._make_validated_lead(
            deal_value_usd=120000,
            deal_stage=DealStage.NEGOTIATION,
            days_in_current_stage=5,
        )
        assert _compute_pre_score(lead) >= 70

    def test_cold_lead_scores_low(self):
        lead = self._make_validated_lead(
            deal_value_usd=3000,
            deal_stage=DealStage.PROSPECTING,
            last_activity_date=date(2025, 1, 1),
            days_in_current_stage=90,
        )
        assert _compute_pre_score(lead) < 30

    def test_incomplete_lead_gets_zero_recency(self):
        lead = self._make_validated_lead(
            last_activity_date=None,
            is_incomplete=True,
        )
        score = _compute_pre_score(lead)
        assert score <= 65

    def test_determine_category_hot(self):
        lead = self._make_validated_lead()
        assert _determine_category(75, lead) == LeadCategory.HOT

    def test_determine_category_cold(self):
        lead = self._make_validated_lead()
        assert _determine_category(25, lead) == LeadCategory.COLD

    def test_determine_category_at_risk(self):
        lead = self._make_validated_lead(
            deal_value_usd=50000,
            last_activity_date=date(2026, 2, 1),
        )
        assert _determine_category(45, lead) == LeadCategory.AT_RISK


# ── D. Review Agent deterministic tests ──────────────────────────────────────


class TestReviewAgent:

    def _make_plan(self, category: LeadCategory, score: int,
                   value: float) -> ActionPlan:
        return ActionPlan(
            lead_id=f"lead_{score}",
            company=f"Co {score}",
            contact_name="Test", contact_email="t@t.com",
            deal_value_usd=value, deal_stage=DealStage.PROPOSAL,
            priority_score=score, category=category,
            score_reasoning="test",
            next_actions=[NextAction(
                description="Follow up",
                owner_role="AE", due_in_days=3,
                priority=ActionPriority.HIGH,
            )],
            follow_up_template="Subject: Hi | Opening: Hello",
        )

    def test_health_summary_counts(self):
        plans = [
            self._make_plan(LeadCategory.HOT, 85, 100000),
            self._make_plan(LeadCategory.WARM, 55, 40000),
            self._make_plan(LeadCategory.AT_RISK, 45, 80000),
        ]
        summary = _compute_health_summary(plans)
        assert summary.total_leads == 3
        assert summary.hot_count == 1
        assert summary.warm_count == 1
        assert summary.at_risk_count == 1
        assert summary.cold_count == 0
        assert summary.total_pipeline_value_usd == 220000
        assert summary.at_risk_pipeline_value_usd == 80000

    def test_health_score_in_range(self):
        plans = [self._make_plan(LeadCategory.COLD, 20, 5000)] * 5
        summary = _compute_health_summary(plans)
        assert 0 <= summary.pipeline_health_score <= 100

    def test_health_summary_is_deterministic(self):
        plans = [self._make_plan(LeadCategory.HOT, 80, 90000)]
        s1 = _compute_health_summary(plans)
        s2 = _compute_health_summary(plans)
        assert s1.pipeline_health_score == s2.pipeline_health_score


# ── E. Workflow helpers tests ────────────────────────────────────────────────


class TestWorkflowHelpers:

    def test_is_parseable_valid(self):
        good = {
            "id": "1", "company": "X", "contact_name": "Y",
            "contact_email": "y@x.com", "deal_value_usd": 1000,
            "deal_stage": "prospecting", "days_in_current_stage": 5,
        }
        assert _is_parseable(good) is True

    def test_is_parseable_missing_fields(self):
        assert _is_parseable({"id": "1", "company": "X"}) is False

    def test_is_parseable_empty_dict(self):
        assert _is_parseable({}) is False

    def test_workflow_factory_creates_workflow(self):
        wf = create_revops_workflow()
        assert wf is not None
        assert len(wf.steps) == 4
        step_names = [s.name for s in wf.steps]
        assert step_names == ["Intake", "Classification", "Action", "Review"]


# ── F. Integration test (requires real LLM + API key) ────────────────────────


@pytest.mark.integration
class TestFullPipeline:

    def test_full_pipeline_produces_report(self):
        """
        End-to-end: runs all 4 agents with real LLM calls.
        Skipped in CI with: pytest -m 'not integration'
        """
        raw = load_leads_from_file(Path("data/sample_leads.json"))
        leads, intake_trace = run_intake_agent(raw)

        from app.agents.classification import run_classification_agent
        from app.agents.action import run_action_agent
        from app.agents.review import run_review_agent

        classified, cls_trace = run_classification_agent(leads)
        plans, act_trace = run_action_agent(classified)
        report, rev_trace = run_review_agent(plans)

        assert len(classified) == len(leads)
        assert len(plans) == len(classified)
        assert report.markdown_report.startswith("#")
        assert 0 <= report.health_summary.pipeline_health_score <= 100

        for trace in [intake_trace, cls_trace, act_trace, rev_trace]:
            assert trace.latency_ms > 0
            assert trace.status == AgentStatus.SUCCESS
