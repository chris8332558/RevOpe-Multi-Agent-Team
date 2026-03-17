"""
Scoring tools for the Classification agent.

Will implement deterministic scoring helpers used alongside LLM reasoning:
- score_deal_value(usd: float) -> int       # 0–40 points
- score_stage(stage: str) -> int            # 0–30 points
- score_recency(days_since_activity: int) -> int  # 0–30 points
- compute_priority_tier(total_score: int) -> PriorityTier
"""
