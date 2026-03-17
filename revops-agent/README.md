# RevOps Multi-Agent Pipeline

A four-agent Revenue Operations pipeline that validates, classifies, and generates action plans for sales leads, producing a prioritized operator dashboard.

## Track

State: Option D — Revenue Operations (Operators Team)

## Agent Architecture

The system uses a planner-less linear pipeline: each step is a pure Python function wrapped as an Agno `Step`. `WorkflowState` (Pydantic v2) flows through `session_data` between steps, serialized as JSON via `model_dump(mode="json")` / `model_validate()`.

```
┌─────────────┐    ┌──────────────────┐    ┌───────────────┐    ┌───────────────┐
│ Intake      │───>│ Classification   │───>│ Action        │───>│ Review        │
│ Agent       │    │ Agent            │    │ Agent         │    │ Agent         │
└─────────────┘    └──────────────────┘    └───────────────┘    └───────────────┘
Validate &         Score 0-100 +           Next actions +        QA + dashboard +
normalize          categorize              follow-up template    JSON log
```

The workflow is orchestrated by `app/workflows/revops_workflow.py` using Agno 2.5.9's Step-based Workflow API (`Workflow(steps=[Step(...), ...])`) — not subclassing. State is transported between steps via `step_input.workflow_session.session_data["session_state"]`.

## What Each Agent Does

**Intake Agent** (`app/agents/intake.py`)
- Input: `list[dict]` (raw JSON records) -> Output: `list[ValidatedLead]` + `AgentTrace`
- No LLM. Pure Python validation and normalization.
- Strips whitespace, lowercases emails, coerces empty date strings to `None`. Flags leads missing `last_activity_date` as incomplete. Skips malformed records with per-lead `ValidationError` catching.

**Classification Agent** (`app/agents/classification.py`)
- Input: `list[ValidatedLead]` -> Output: `list[ClassifiedLead]` + `AgentTrace`
- Uses LLM (via LiteLLM). Also computes a deterministic `_compute_pre_score` (0-100) as an anchor.
- LLM assigns `priority_score`, `category` (hot/warm/cold/at_risk), and `score_reasoning`. Retries up to 3 times on parse failure, falls back to deterministic score if all retries fail.

**Action Agent** (`app/agents/action.py`)
- Input: `list[ClassifiedLead]` -> Output: `list[ActionPlan]` + `AgentTrace`
- Uses LLM. Generates 2-3 `NextAction` items with due dates, owner roles, and a `follow_up_template` per lead.
- Category-specific strategy context injected into prompts (HOT: urgent closure actions, AT_RISK: escalation, WARM: nurture, COLD: re-engage or archive). Raises `RuntimeError` on total failure — no fallback.

**Review Agent** (`app/agents/review.py`)
- Input: `list[ActionPlan]` -> Output: `WorkflowReport` + `AgentTrace`
- Two LLM calls: one for QA `review_notes` (JSON, retry loop), one for `markdown_report` (free text, single attempt with template fallback).
- `_compute_health_summary` is fully deterministic: health score formula is `50 + (hot_ratio * 30) - (at_risk_ratio * 25) - (cold_ratio * 15)`.

## Tools Used

- **agno 2.5.9** — Step-based Workflow orchestration, AgentOS for UI
- **litellm** — LLM provider abstraction (Gemini / vLLM-compatible)
- **pydantic v2** — typed state contracts between agents, schema-first design
- **rich** — CLI output (tables, panels, markdown rendering)
- **uv** — dependency management and virtual environment

## Setup & Run

### Prerequisites

Python 3.12+, [uv](https://docs.astral.sh/uv/) installed.

### Install

```bash
git clone <repo>
cd revops-agent
uv sync
```

### Configure

```bash
cp .env.example .env
# Edit .env — set GEMINI_API_KEY and LLM_MODEL
# Example: LLM_MODEL=gemini/gemini-2.0-flash
```

### Run CLI demo

```bash
uv run python -m demo.run_demo
```

### Run Agent OS UI

```bash
uv run uvicorn playground:app --host 0.0.0.0 --port 8000 --reload
# Open https://os.agno.com -> Add new OS -> Local -> http://localhost:8000
```

### Run tests

```bash
uv run pytest tests/ -m "not integration" -v     # fast, no LLM
uv run pytest tests/ -m integration -v            # requires API key
```

## Where AI-Assisted Coding Helped

- **Claude Code** was the primary AI tool used throughout the entire build, from scaffold to final deliverables. Claude on claude.ai was used for initial planning and spec drafting.
- **Pydantic v2 schema generation** — Claude Code generated all 10 typed models with validators, computed fields, and `ConfigDict` in one pass. Required a correction: `model_config` is the class attribute name, not an importable callable — the import must be `ConfigDict`.
- **Agent boilerplate** — each agent's retry loop, LLM call wrapper, markdown-fence stripping, and `AgentTrace` assembly followed a consistent pattern that Claude Code templated efficiently across all four agents.
- **Prompt engineering** — system prompts and user message templates for Classification, Action, and Review agents were drafted by Claude Code, with human review of the output contracts (JSON schema instructions, "return ONLY the JSON" directives).
- **`except Exception` vs narrow catches** — Claude Code initially used narrow exception types (`ValidationError`, `KeyError`, etc.) in the Classification Agent retry loop. This missed LiteLLM's own error types (`AuthenticationError`, `APIConnectionError`), causing leads to be silently lost. Debugging this required reading LiteLLM source to understand which exceptions it raises.
- **Agno 2.5.9 API discovery** — the original workflow spec used `RunResponse`/`RunEvent` which don't exist in agno 2.5.9. Claude Code explored the installed package internals (`StepInput`, `WorkflowSession`, `Step.__init__` signatures) to find the actual Step-based API, but this required multiple rounds of inspection and correction.
- **The `_get_sd()`/`_set_sd()` session_data pattern** — the critical discovery that `workflow.session_state` is nested at `session.session_data["session_state"]` (not `session_data` directly) required reading agno's `workflow.py` source code (~6000 lines). The initial implementation returned the wrong dict level, producing 0 valid leads. This was debugged by running the demo and tracing the empty result back to the nesting mismatch.
- **`StepInput` has no `session_state` attribute** — another agno 2.5.9 internal that differed from the spec. Shared state lives at `step_input.workflow_session.session_data`, not a top-level attribute. Required `getattr` fallback to `additional_data` for testability.
- **Intake step pre-parse crash** — Claude Code's initial `intake_step_fn` used `[RawLead.model_validate(r) for r in parseable]` which crashed the entire step on one bad lead (lead_006). The fix was recognizing that `run_intake_agent` already handles per-lead `ValidationError` internally, so the redundant pre-parse was removed.
- **`AgentOS` vs `Playground`** — `agno.playground.Playground` was removed in agno v2. Claude Code initially generated code using it. The fix required discovering `agno.os.AgentOS` and its `get_app()` method by exploring the installed package.
- **`datetime.utcnow()` deprecation** — Claude Code initially used `datetime.utcnow()` across schemas; the linter flagged this as deprecated in Python 3.12. All timestamps were updated to `datetime.now(timezone.utc)`.
- **Sample data design** — the distinction between lead_005 (`null` date = incomplete but valid) and lead_006 (absent key = Pydantic error) was a deliberate human design decision to exercise both intake paths, implemented after Claude Code's initial version had both as `null`.
- **Rich CLI demo** — Claude Code generated the observability table formatting and panel layout. The key design decision that the table reads from the saved JSON log (not in-memory objects) was specified by the human to prove the log is correct and independently readable.
- **CHANGELOG discipline** — prepend-only, Decisions section mandatory for non-obvious choices — was enforced as a human convention that Claude Code followed consistently after initial guidance.

## Tradeoffs & Known Limitations

- **LLM + deterministic pre-score for classification** — the rule-based `_compute_pre_score` serves two purposes: it anchors the LLM output (included in prompt as "starting reference") and provides a guaranteed fallback if all LLM retries fail. This ensures the pipeline never drops a lead due to LLM failure.
- **Action Agent raises `RuntimeError` vs Classification Agent fallback** — the Classification Agent has a meaningful deterministic fallback (pre-score + rule-based category). The Action Agent does not: a generated action plan without LLM output would be useless boilerplate. So it raises on total failure, and `run_action_agent` catches per-lead, logs the loss, and continues.
- **Two LLM calls in Review Agent** — `review_notes` (JSON, QA-focused) and `markdown_report` (free text, formatting-focused) have fundamentally different output contracts. Splitting them gives cleaner retry logic: notes use JSON parsing + retry loop; markdown uses a single attempt with a pre-built fallback template.
- **No parallel agent execution** — agents run sequentially because each depends on the previous step's output (`ValidatedLead` -> `ClassifiedLead` -> `ActionPlan`). There's no opportunity for parallelism in the pipeline itself, though leads within each agent could theoretically be processed concurrently.
- **vLLM local model support** — set `LLM_MODEL=openai/<model-name>` and `VLLM_API_BASE=http://localhost:8000` in `.env`. The LiteLLM abstraction routes to the local endpoint via `api_base`. This path is implemented but less tested than the Gemini path.
- **Sample data size** — 6 leads (5 valid + 1 malformed) is a demo dataset. The pipeline processes leads sequentially with individual LLM calls, so scaling to hundreds of leads would require batching or concurrency — neither is implemented.
- **AgentOS session persistence via SqliteDb** — `playground.py` uses `SqliteDb(db_file="tmp/agent_os.db")` for session storage. This is sufficient for local development but would need PostgreSQL or similar for production use.
- **Broad `except Exception` in Classification Agent** — necessary because LiteLLM raises its own exception types that don't overlap with `ValidationError`/`KeyError`/`JSONDecodeError`. The tradeoff is that truly unexpected errors (e.g., `MemoryError`) are silently caught and retried, but this is acceptable given the fallback guarantee.

## Output Format

- **Logs:** `outputs/workflow_<id>_<timestamp>.json` — structured JSON with per-agent traces, health summary, total latency and token counts
- **Report:** Markdown dashboard embedded in the final `StepOutput`, including pipeline health score, priority leads table, QA review notes, and all action plans
