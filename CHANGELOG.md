## [2026-03-16] — Intake Agent (stage 1 of pipeline)

### Added
- `app/agents/intake.py` — full implementation of the Intake Agent: `_normalize_raw` (whitespace strip, email lowercase, empty-string date coercion), `_build_validated_lead` (incomplete flag + warning notes), `run_intake_agent` (main entry point with per-lead ValidationError catching and AgentTrace output), `load_leads_from_file` helper, and a `__main__` Rich table smoke test

### Changed
- `data/sample_leads.json` — corrected lead_005 and lead_006 to properly exercise both intake paths: lead_005 `last_activity_date` set to `null` (becomes the 1 incomplete `ValidatedLead`); lead_006 `last_activity_date` key removed entirely (missing required field triggers a Pydantic `ValidationError`, exercising the skip/error path)

### Decisions
- **`null` vs absent key for the incomplete path** — a JSON `null` for `date | None` passes Pydantic validation silently (becoming `None`), so it cannot trigger the error-handling path. Only a fully absent key raises "field required". The two leads therefore serve distinct roles: lead_005 (null) → incomplete but valid; lead_006 (absent) → skipped with error logged.
- **`run_intake_agent` never raises** — all `ValidationError`s are caught per-lead and accumulated in `errors`; the agent always returns a result so the workflow can continue with partial data.
- **`datetime.now(timezone.utc)` over `datetime.utcnow()`** — `utcnow()` is deprecated in Python 3.12; all timestamps use timezone-aware UTC objects.

## [2026-03-16] — Pydantic v2 schemas (pipeline contracts)

### Added
- `app/models/schemas.py` — full implementation of all 10 typed models defining the agent-to-agent contracts: `RawLead`, `ValidatedLead`, `ClassifiedLead`, `NextAction`, `ActionPlan`, `PipelineHealthSummary`, `WorkflowReport`, `AgentTrace`, `WorkflowState`, plus all four enums (`DealStage`, `LeadCategory`, `ActionPriority`, `AgentStatus`)

### Decisions
- **No model inheritance** — each model copies fields from its predecessor explicitly. This avoids implicit coupling between agent stages; each model is independently readable and serializable without tracing a class hierarchy.
- **`latency_ms` as `@computed_field`** — derived from `end_time - start_time` at read time rather than stored, keeping `AgentTrace` construction simple (caller just sets start/end times).
- **`ActionPlan` carries a subset of `ClassifiedLead` fields** — only fields the Review Agent actually needs are forwarded, reducing noise and keeping the downstream contract minimal.
- **`ConfigDict` over `model_config` import** — Pydantic v2 exports `ConfigDict` (not `model_config` as a callable); the attribute on each model class is named `model_config` per v2 convention.
