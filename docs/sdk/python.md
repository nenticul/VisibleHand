# Python SDK

## Installation

```bash
pip install visiblehand
```

Or from source:
```bash
cd sdk && pip install -e .
```

## Sync client

```python
from visiblehand import Client

client = Client(
    base_url="https://api.visiblehand.dev",  # or your self-hosted URL
    api_key="optional-key",
)

# Score a country
score = client.risk("BR")
print(score.composite)          # 52.0
print(f"[{score.ci_low:.1f}, {score.ci_high:.1f}]")  # [46.5, 57.6]
print(score.confidence)         # 0.70
print(score.risk_level)         # "Moderate"
print(score.top_drivers)        # ['rapid_escalation', ...]
print(score.governance)         # 45.5

# Compare countries
scores = client.compare("US", "DE", "BR", "UA")
for s in sorted(scores, key=lambda x: x.composite, reverse=True):
    print(f"{s.country}: {s.composite:.1f} [{s.ci_low:.1f}-{s.ci_high:.1f}]")

# Historical scores
history = client.history("BR", limit=30)
for h in history:
    print(f"{h.date}: {h.composite:.1f} (conf={h.confidence:.2f})")

# Governance sub-score
gov = client.governance("DE")
print(gov.score, gov.components)

# NLP aspect scores
aspects = client.aspects("BR")
print(aspects.monetary_policy, aspects.fiscal_policy)

# Forecast
forecast = client.forecast("UA")
print(forecast)

# Driver attribution
drivers = client.drivers("BR")
for d in drivers["driver_attributions"]:
    print(f"{d['name']}: {d['contribution']:.2f} ({d['direction']})")

# Movers (biggest 7-day changes)
movers = client.movers(days=7, limit=5)

# Calibration
cal = client.calibration()
print(cal["component_weights"])
```

## Async client

```python
import asyncio
from visiblehand import AsyncClient

async def main():
    async with AsyncClient(base_url="http://localhost:8000") as client:
        # Score multiple countries concurrently
        ua, br, de = await asyncio.gather(
            client.risk("UA"),
            client.risk("BR"),
            client.risk("DE"),
        )
        print(ua.composite, br.composite, de.composite)

asyncio.run(main())
```

## Data models

| Class | Fields |
|-------|--------|
| `RiskScore` | `composite`, `ci_low`, `ci_high`, `confidence`, `risk_level`, `breakdown`, `top_drivers`, `driver_attributions`, `forecast`, `regime_flags`, `governance`, `methodology` |
| `ScoreBreakdown` | `economic`, `political`, `nlp_sentiment`, `governance` |
| `DriverAttribution` | `name`, `contribution`, `direction`, `sub_scorer` |
| `ForecastPoint` | `composite`, `ci_low`, `ci_high` |
| `GovernanceScore` | `country`, `score`, `confidence`, `components`, `drivers` |
| `AspectScores` | `overall`, `monetary_policy`, `fiscal_policy`, `financial_stability`, `external_sector`, `political_economy`, `sentence_count` |
| `HistoryPoint` | `date`, `composite`, `ci_low`, `ci_high`, `economic`, `political`, `governance`, `confidence` |
