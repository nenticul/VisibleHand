# visiblehand

Python SDK for the [VisibleHand](https://github.com/nenticul/VisibleHand) political-economic country risk API.

VisibleHand scores country-level risk on a **0–100 scale** (0 = stable, 100 = high risk), updated daily from live sources. Free and open-source alternative to commercial equivalents costing $15,000–$50,000/year.

## Install

```bash
pip install visiblehand
```

## Usage

```python
from visiblehand import Client

client = Client()

# Single country
score = client.risk("BR")
print(score.composite)       # 61.4
print(score.ci_low, score.ci_high)   # 55.1, 67.8
print(score.top_drivers)     # ['high_inflation_vs_history', 'rapid_escalation']
print(score.methodology)     # plain-language explanation

# Compare multiple countries
scores = client.compare("US", "DE", "BR", "IN", "ZA")
for s in sorted(scores, key=lambda x: x.composite, reverse=True):
    print(f"{s.country}: {s.composite:.1f} ({s.risk_level})")

# Historical trend
history = client.history("AR", limit=90)
for day in history[-5:]:
    print(day.date, day.composite)

# Governance sub-score
gov = client.governance("NG")
print(gov.score, gov.components)
```

### Custom weights

```python
# Emphasise political risk
score = client.risk("UA", political_weight=0.6, economic_weight=0.3, nlp_weight=0.1)
```

### Async client

```python
import asyncio
from visiblehand import AsyncClient

async def main():
    async with AsyncClient() as client:
        score = await client.risk("IN")
        print(score.composite, score.confidence)

asyncio.run(main())
```

### Self-hosted

```python
client = Client(base_url="http://localhost:8000")
```

## Score breakdown

Every score includes:

- `composite` — overall 0–100 risk score
- `ci_low` / `ci_high` — 95% confidence interval (Monte Carlo)
- `breakdown` — economic, political, nlp_sentiment, governance sub-scores
- `top_drivers` — ranked list of what's driving the score
- `confidence` — data coverage and freshness (0–1)
- `risk_level` — Very Low / Low / Moderate / High / Very High / Critical
- `methodology` — plain-language explanation

## Note

> ⚠️ Research preview. Scores are not validated for investment or financial decisions. See [METHODOLOGY.md](https://github.com/nenticul/VisibleHand/blob/main/METHODOLOGY.md) for full methodology and limitations.

## Links

- [GitHub](https://github.com/nenticul/VisibleHand)
- [API docs](https://github.com/nenticul/VisibleHand#api-reference)
- [Methodology](https://github.com/nenticul/VisibleHand/blob/main/METHODOLOGY.md)

## License

MIT
