"""
Intake Agent — Stage 1 of the RevOps pipeline.

Responsibilities:
- Ingest raw lead records from data sources (JSON, CRM webhooks, etc.)
- Validate required fields and flag incomplete records
- Normalize field formats (dates, currency, email)
- Emit a validated LeadRecord for downstream agents or a FailedIngestion on error
"""
