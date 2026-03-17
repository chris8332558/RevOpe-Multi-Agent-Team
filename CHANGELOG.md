## [2026-03-16] — Pydantic v2 schemas (pipeline contracts)

### Added
- `app/models/schemas.py` — full implementation of all 10 typed models defining the agent-to-agent contracts: `RawLead`, `ValidatedLead`, `ClassifiedLead`, `NextAction`, `ActionPlan`, `PipelineHealthSummary`, `WorkflowReport`, `AgentTrace`, `WorkflowState`, plus all four enums (`DealStage`, `LeadCategory`, `ActionPriority`, `AgentStatus`)

### Decisions
- **No model inheritance** — each model copies fields from its predecessor explicitly. This avoids implicit coupling between agent stages; each model is independently readable and serializable without tracing a class hierarchy.
- **`latency_ms` as `@computed_field`** — derived from `end_time - start_time` at read time rather than stored, keeping `AgentTrace` construction simple (caller just sets start/end times).
- **`ActionPlan` carries a subset of `ClassifiedLead` fields** — only fields the Review Agent actually needs are forwarded, reducing noise and keeping the downstream contract minimal.
- **`ConfigDict` over `model_config` import** — Pydantic v2 exports `ConfigDict` (not `model_config` as a callable); the attribute on each model class is named `model_config` per v2 convention.
