# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Package management

Use `uv` exclusively — never `pip install` directly.

```bash
uv add <package>            # add runtime dependency
uv add --dev <package>      # add dev dependency
uv run <command>            # run any command inside the venv
```

## Common commands

```bash
# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_placeholder.py -v

# Run a single test by name
uv run pytest tests/test_placeholder.py::test_imports -v

# Run the demo (once implemented)
uv run python demo/run_demo.py
```

## CHANGELOG.md Rules

When the user asks to log changes into `CHANGELOG.md`:

1. **Prepend** a new section at the top (below the file header, above all existing entries)
2. **Section header format**: `## [YYYY-MM-DD] — <short description of the session's theme>`
3. **Group entries** under these subsections as applicable:
   - `### Added` — new files, dependencies, features
   - `### Changed` — modifications to existing files or behaviour
   - `### Removed` — deleted files or dropped functionality
   - `### Fixed` — bug fixes
   - `### Decisions` — reasoning behind non-obvious choices (architecture, naming, trade-offs, workarounds)
4. Each bullet should name the **file or artifact** first, then a concise description of what changed and why
5. The `### Decisions` block is mandatory when a non-trivial design choice was made — explain *why*, not just *what*
6. Never overwrite or delete existing entries


## Architecture

The system is a **4-stage linear pipeline** where each stage is an independent Agno agent:

```
Intake → Classification → Action → Review
```

- **Intake** (`app/agents/intake.py`) — validates and normalizes raw lead records; emits a clean `LeadRecord` or a `FailedIngestion` (e.g. missing `last_activity_date`)
- **Classification** (`app/agents/classification.py`) — scores leads and assigns a `PriorityTier`: `HOT | WARM | COLD | AT_RISK`
- **Action** (`app/agents/action.py`) — generates a recommended next action with rationale for each classified lead
- **Review** (`app/agents/review.py`) — audits full pipeline output and produces the operator dashboard payload

The workflow that chains all four agents lives in `app/workflows/revops_workflow.py`.

### Key design decisions

**LLM routing via LiteLLM** — all agents must call `get_model_id()` and optionally `get_api_base()` from `app/utils/llm.py` rather than hardcoding model strings. This is the single config point for switching between Gemini and local vLLM.

**Two supported providers:**
- Gemini: set `LLM_MODEL=gemini/gemini-2.0-flash` and `GEMINI_API_KEY`
- Local vLLM: set `LLM_MODEL=openai/<model-name>` and `VLLM_API_BASE=http://localhost:8000`

**Pydantic v2 schemas** (`app/models/schemas.py`) define the typed state objects passed between agents: `LeadRecord → ClassifiedLead → ActionPlan → ReviewSummary`.

**Sample data** (`data/sample_leads.json`) contains 6 leads that deliberately cover all pipeline paths: HOT, AT_RISK, WARM (×2), COLD, and one INCOMPLETE lead (null `last_activity_date`) to exercise the Intake agent's error path.

## Environment setup

```bash
cp .env.example .env
# then fill in GEMINI_API_KEY or VLLM_API_BASE + LLM_MODEL
```
