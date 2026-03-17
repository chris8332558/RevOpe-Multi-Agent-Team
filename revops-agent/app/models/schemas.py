"""
Pydantic v2 schemas for the RevOps pipeline.

Will define:
- LeadRecord: validated, normalized inbound lead
- ClassifiedLead: LeadRecord + priority tier + confidence score
- ActionPlan: recommended next action with rationale
- ReviewSummary: final operator dashboard payload
- FailedIngestion: error envelope for incomplete/invalid leads
- PriorityTier enum: HOT | WARM | COLD | AT_RISK
"""
