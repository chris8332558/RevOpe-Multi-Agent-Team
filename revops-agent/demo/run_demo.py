"""
Demo runner — end-to-end RevOps pipeline walkthrough.

Will:
- Load sample leads from data/sample_leads.json
- Run the full Intake → Classification → Action → Review pipeline
- Render a prioritized operator dashboard to the terminal using Rich
- Print per-agent timing and token usage summaries
"""
