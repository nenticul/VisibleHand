# VisibleHand

**Free, open-source political-economic country risk scoring.**  
Commercial equivalents (ICRG, Bloomberg COUN) cost $15–50k/year. This is free.

---

## What is it?

VisibleHand scores any country **0–100** by blending four sub-scorers:

| Component | Weight | Sources |
|-----------|--------|---------|
| **Economic** | 45% | World Bank WDI, IMF WEO, BIS, ILO, IMF FSI |
| **Political** | 25% | GDELT, ACLED (Hawkes process + contagion) |
| **NLP** | 20% | FinBERT on central-bank statements |
| **Governance** | 10% | V-Dem, WJP, TI CPI, Freedom House |

Every score ships:
- **Bayesian 95% confidence interval** (Monte Carlo, 500 samples)
- **Signed driver attributions** (which indicator drives risk most)
- **6m/12m Theil-Sen forecast** (extrapolation, not prediction)
- **Plain-language methodology string**

---

## Quick start

```python
from visiblehand import Client

client = Client(base_url="http://localhost:8000")
score = client.risk("BR")

print(score.composite)          # 52.0
print(score.ci_low, score.ci_high)  # 46.5, 57.6
print(score.top_drivers)        # ['rapid_escalation', ...]
print(score.governance)         # 45.5
```

Or via HTTP:

```bash
curl http://localhost:8000/risk/BR | jq .composite
```

---

## Why VisibleHand?

| Feature | VisibleHand | ICRG | Bloomberg COUN |
|---------|-------------|------|----------------|
| Price | **Free** | $15k+/yr | $50k+/yr |
| Open source | **Yes** | No | No |
| Methodology published | **Yes** | Partial | No |
| Confidence intervals | **Yes** | No | No |
| Driver attribution | **Yes** | No | No |
| NLP on central-bank language | **Yes** | No | No |
| API | **REST** | Download | Bloomberg Terminal |

---

## Installation

See [Getting Started → Quickstart](getting-started/quickstart.md).

---

## Scores are not investment advice

VisibleHand scores are analytical tools for research and situational awareness.
They are not investment advice, legal advice, or professional risk assessments.
See [Terms of Use](terms-of-use.md).
