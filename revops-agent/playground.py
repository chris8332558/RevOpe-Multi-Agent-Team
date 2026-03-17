"""
Agno Agent OS — serves the RevOps pipeline for the Agent OS UI.

Setup:
    uv add "agno[os]"

Run:
    fastapi dev playground.py

Then:
    1. Open https://os.agno.com
    2. Click "Add new OS" → "Local"
    3. Enter http://localhost:8000
    4. Click "Connect"
"""
from agno.os import AgentOS
from agno.db.sqlite import SqliteDb

from app.workflows.revops_workflow import create_revops_workflow

# Create the workflow
workflow = create_revops_workflow()

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

# FastAPI app — this is what `fastapi dev playground.py` picks up
app = agent_os.get_app()
