# Example Pipeline Output

**Run ID:** revops-a1b2c3d4
**Generated:** 2026-03-17 05:30 UTC
**Leads processed:** 5 valid (1 skipped — malformed input)

Lead `lead_006` (Vantage Point Solutions) was skipped because `last_activity_date` was absent from the record entirely (missing key, not null), triggering a Pydantic validation error. The remaining 5 leads were processed through all 4 pipeline stages.

## Observability Log

| Agent                | Status  | Latency (ms) | Tokens | Retries |
|----------------------|---------|-------------|--------|---------|
| intake_agent         | success | 12          | —      | 0       |
| classification_agent | success | 3847        | 1823   | 0       |
| action_agent         | success | 6234        | 2891   | 0       |
| review_agent         | success | 7156        | 3102   | 0       |
| **Total**            |         | **17,249**  | **7,816** |      |

## Pipeline Dashboard

### Pipeline Health Score: 46/100

| Metric                 | Value     |
|------------------------|-----------|
| Total Leads            | 5         |
| Hot Leads              | 1         |
| Warm Leads             | 2         |
| Cold Leads             | 0         |
| At-Risk Leads          | 2         |
| Incomplete Leads       | 1         |
| Total Pipeline Value   | $317,200  |
| At-Risk Pipeline Value | $105,700  |

### Top Priority Leads

| Rank | Company                    | Score | Category | Next Action                              |
|------|----------------------------|-------|----------|------------------------------------------|
| 1    | Meridian Analytics         | 88    | hot      | Follow up with procurement for MSA sign-off (due 1d, AE) |
| 2    | Stackwell Inc              | 52    | at_risk  | Re-engage champion with case study email (due 2d, AE) |
| 3    | Crestview Capital Partners | 58    | warm     | Send revised proposal with volume discount (due 3d, AE) |
| 4    | Luminary Health Systems    | 50    | warm     | Schedule competitive positioning call (due 5d, SDR) |
| 5    | Halcyon Retail Group       | 14    | at_risk  | Send re-engagement email with ROI calculator (due 7d, SDR) |

### QA Review Notes

The pipeline health score of 46/100 reflects a pipeline with significant at-risk exposure. Meridian Analytics is the only hot lead and should be the top priority — the deal is in negotiation with legal review complete, making closure within the week realistic. Stackwell Inc and Halcyon Retail Group are both flagged at-risk: Stackwell has gone dark after 35 days in proposal stage with a $97.5K deal, warranting immediate escalation to a Manager if the AE re-engagement attempt fails within 48 hours. Halcyon's incomplete data (missing last activity date) and 65 days in prospecting suggest this lead may need to be archived if the re-engagement attempt shows no traction.

### All Action Plans

---

**Meridian Analytics** | Score: 88 | Category: hot
- [URGENT] Follow up with procurement to confirm MSA sign-off timeline (due: 1d, owner: AE)
- [URGENT] Prepare final pricing sheet and implementation timeline for signature (due: 2d, owner: AE)
- [HIGH] Schedule post-signature onboarding kickoff with CS team (due: 3d, owner: CSM)

Follow-up: Subject: MSA Sign-Off — Next Steps for Meridian Analytics | Opening: Hi Sarah, following up on the procurement review — wanted to confirm we're still on track for sign-off by end of week.

---

**Stackwell Inc** | Score: 52 | Category: at_risk
- [URGENT] Send personalized re-engagement email with relevant case study (due: 1d, owner: AE)
- [HIGH] If no response in 48h, escalate to Manager for executive outreach (due: 3d, owner: Manager)
- [MEDIUM] Set 14-day archive trigger if no engagement after escalation (due: 14d, owner: SDR)

Follow-up: Subject: Checking In — Stackwell Proposal Update | Opening: Hi Derek, I wanted to follow up on the proposal we sent last month. I've attached a case study from a similar deployment that might address some of your team's questions.

---

**Crestview Capital Partners** | Score: 58 | Category: warm
- [HIGH] Send revised proposal with requested volume discount pricing (due: 2d, owner: AE)
- [MEDIUM] Schedule call to walk through revised terms and address questions (due: 5d, owner: AE)
- [MEDIUM] Prepare competitive comparison document if competitor mentioned (due: 7d, owner: SDR)

Follow-up: Subject: Revised Proposal — Crestview Volume Pricing | Opening: Hi Marcus, as discussed, here's the updated proposal with the volume discount structure your team requested.

---

**Luminary Health Systems** | Score: 50 | Category: warm
- [MEDIUM] Send competitive positioning one-pager addressing vendor comparison (due: 3d, owner: SDR)
- [MEDIUM] Schedule technical deep-dive with their evaluation team (due: 5d, owner: SDR)
- [HIGH] Request intro to economic buyer / decision maker (due: 7d, owner: AE)

Follow-up: Subject: Luminary Health — Technical Deep Dive & Next Steps | Opening: Hi Priya, great speaking with you during the discovery call. I'd love to schedule a deeper technical session to address the evaluation criteria you mentioned.

---

**Halcyon Retail Group** | Score: 14 | Category: at_risk
- [MEDIUM] Send re-engagement email with ROI calculator tailored to retail (due: 3d, owner: SDR)
- [LOW] If no response in 14 days, move to archive/nurture track (due: 14d, owner: SDR)

Follow-up: Subject: Quick Question — Halcyon Retail Group | Opening: Hi Tina, I wanted to check in and share a quick ROI calculator that might be useful as you evaluate solutions for your team.
