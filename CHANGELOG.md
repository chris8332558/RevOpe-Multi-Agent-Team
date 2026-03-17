## [2026-03-16] — Review Agent (stage 4 of pipeline — final output)

### Added
- `app/agents/review.py` — full implementation of the Review Agent: `_compute_health_summary` (deterministic `PipelineHealthSummary` from counts and deal values, health score formula: base 50 ± hot/at-risk/cold ratios), `_call_llm` (shared LiteLLM helper for both calls, returns raw string), `_build_review_notes_prompt` / `_build_markdown_prompt` (separate prompts for QA notes vs. dashboard), `_get_review_notes` (retry loop + string fallback), `_get_markdown_report` (single attempt + minimal template fallback), `run_review_agent` (main entry point assembling `WorkflowReport`), and a `__main__` Rich Markdown smoke test

### Decisions
- **Two separate LLM calls** — review_notes and markdown_report have fundamentally different output contracts (JSON vs. free-text markdown) so splitting them gives cleaner retry logic: notes use JSON parsing + retry loop; markdown uses a single attempt with a pre-built fallback template, since markdown failures are less structured and not worth retrying.
- **`top_priority_leads` sorted in Python, not LLM** — deterministic sort by `priority_score` descending guarantees the ordering contract regardless of LLM behaviour; LLM is only responsible for narrative content.
- **`_compute_health_summary` proxies `incomplete_count`** via `"incomplete" in score_reasoning.lower()` because `ActionPlan` does not carry `is_incomplete` — the Classification Agent embeds "incomplete" in the fallback `score_reasoning` when the lead has no `last_activity_date`.

## [2026-03-16] — Action Agent (stage 3 of pipeline)

### Added
- `app/agents/action.py` — full implementation of the Action Agent: `_get_strategy_context` (category-specific strategy strings injected into LLM prompt), `_build_action_prompt` (messages builder with per-category guidance and retry context), `_call_llm_for_action` (LiteLLM call at temperature=0.3, max_tokens=512), `_parse_next_actions` (raw dict → `NextAction` model list with enum validation), `_build_action_plan_single` (retry loop, raises `RuntimeError` on total failure — no fallback), `run_action_agent` (main entry point catching `RuntimeError` per lead), and a `__main__` Rich panel smoke test

### Decisions
- **`RuntimeError` on total failure, no fallback** — unlike the Classification Agent, the Action Agent has no meaningful deterministic fallback (a generated action plan without LLM output would be useless). Total failure is surfaced as a `RuntimeError` that `run_action_agent` catches per-lead, logs, and skips — keeping the workflow alive while flagging the loss in `trace.error_message`.
- **`except (ValidationError, KeyError, ValueError, JSONDecodeError)` kept narrow in retry loop** — the Action Agent's LLM failures (auth errors, network) are not retryable in a meaningful way, so they propagate out of the loop and become the `RuntimeError`. This differs from the Classification Agent where all failures should retry to reach the safe fallback.
- **`temperature=0.3` vs `0.1` for Classification** — action descriptions benefit from slight variation to avoid identical boilerplate across similar leads; classification scoring needs tighter determinism.

## [2026-03-16] — Classification Agent (stage 2 of pipeline)

### Added
- `app/agents/classification.py` — full implementation of the Classification Agent: `_compute_pre_score` (deterministic 0–100 rule-based score from deal stage, deal value, recency, and stage-velocity penalty), `_determine_category` (rule-based `LeadCategory` fallback), `_build_classification_prompt` (LiteLLM messages builder with retry context injection), `_call_llm_for_classification` (LiteLLM call with markdown-fence stripping), `_classify_single_lead` (retry loop + deterministic fallback), `run_classification_agent` (main entry point with AgentTrace), and a `__main__` Rich table smoke test

### Decisions
- **Broad `except Exception` in the retry loop** — the spec listed specific exception types (`ValidationError`, `KeyError`, `ValueError`, `JSONDecodeError`), but LiteLLM raises its own types (`AuthenticationError`, `APIConnectionError`, etc.) that are none of those. A narrow catch let LLM failures escape the retry loop and bypass the fallback entirely, losing the lead. Catching `Exception` keeps all failure modes inside the retry/fallback cycle, which is the required contract.
- **Deterministic fallback is always safe** — `_classify_single_lead` never raises; after `MAX_RETRIES` exhausted it falls back to `_compute_pre_score` + `_determine_category`, ensuring the downstream Action Agent always receives a `ClassifiedLead` regardless of LLM availability.
- **Pre-score as LLM anchor** — the rule-based score is included in the prompt as a "starting reference" so the LLM output stays grounded; on retry the previous error is appended to the prompt to steer correction without a full context reset.

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
