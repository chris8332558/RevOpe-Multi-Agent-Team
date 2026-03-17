"""
RevOps Agno Workflow — orchestrates the full 4-agent pipeline.

Defines the Agno Workflow that chains:
  Intake → Classification → Action → Review

Handles per-lead session state, error routing for failed ingestions,
and produces the final prioritized operator dashboard output.
"""
