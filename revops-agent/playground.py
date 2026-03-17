"""
Agno Agent OS — serves the RevOps pipeline for the Agent OS UI.

Setup:
    uv add "agno[os]"

Run:
    uv run uvicorn playground:app --host 0.0.0.0 --port 8000 --reload

Then:
    1. Open https://os.agno.com
    2. Click "Add new OS" → "Local"
    3. Enter http://localhost:8000
    4. Click "Connect"
"""
from pathlib import Path

from agno.os import AgentOS
from agno.db.sqlite import SqliteDb

from app.agents.intake import load_leads_from_file
from app.workflows.revops_workflow import create_revops_workflow

# Create the workflow and pre-load sample leads into session_state
workflow = create_revops_workflow()
workflow.session_state = {
    "raw_leads": load_leads_from_file(Path("data/sample_leads.json"))
}

# Create AgentOS with the workflow registered
agent_os = AgentOS(
    name="RevOps Pipeline",
    description=(
        "Revenue Operations pipeline: validates, classifies, and generates "
        "action plans for sales leads."
    ),
    workflows=[workflow],
    db=SqliteDb(db_file="tmp/agent_os.db"),
    tracing=True,
)

# Fastapi app 
app = agent_os.get_app()
