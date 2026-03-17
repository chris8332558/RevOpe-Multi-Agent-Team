"""
Classification Agent — Stage 2 of the RevOps pipeline.

Responsibilities:
- Score each validated lead using deal value, stage, and recency signals
- Assign a priority tier: HOT | WARM | COLD | AT_RISK
- Attach confidence score and reasoning to each classification
- Pass enriched LeadRecord to the Action agent
"""
