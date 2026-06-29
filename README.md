# VisibleHand

<img width="1917" height="507" alt="image" src="https://github.com/user-attachments/assets/491ed206-f7b7-43d5-b4c6-5e84946073a7" />

**Political-economic risk scoring for every country. Free. Programmable. Open.**

```bash
pip install visiblehand
```

```python
from visiblehand import Client

client = Client()
score = client.risk("BR")

print(score.composite)      # 61.4
print(score.top_drivers)    # ['high_inflation_vs_history', 'elevated_protest_activity']
print(score.methodology)    # Plain-language explanation of what drove the number
```

Or via HTTP:

```bash
curl https://api.visiblehand.xyz/risk/BR
```

```json
{
  "country": "AR",
  "name": "Argentina",
  "composite": 73.0,
  "confidence": 0.78,
  "risk_level": "High",
  "breakdown": { "economic": 72.9, "political": 65.2, "nlp_sentiment": 85.0 },
  "top_drivers": ["hawkish_central_bank_language", "high_inflation_vs_history", "rapid_escalation"],
  "methodology": "Economic risk 73/100 (weight 50%, confidence 80%). Political risk 65/100 from 3 events (weight 30%). Central-bank language hawkish â†’ 85/100 (weight 20%).",
  "components": { "economic": { "score": 72.9, "confidence": 0.8, "detail": {"inflation": 88.6, "fx_reserves": 79.1} } },
  "updated_at": "2026-06-26T06:00:00Z"
}
```

Every score carries a **confidence** (driven by data coverage + freshness), a
**risk band**, ranked **drivers**, and a plain-language **methodology** â€” so the
number is never a black box.

---

## What it does

VisibleHand scores country-level political-economic risk on a continuous **0â€“100 scale**
(0 = extremely stable, 100 = extremely high risk), updated daily from live sources.

**Three sub-scores, one composite:**

| Component | Default weight | Method |
|-----------|---------------|--------|
| Economic | 50% | Robust median/MAD z-scores + momentum on World Bank / FRED / IMF data |
| Political | 30% | Baseline-relative, decay-weighted GDELT/ACLED events + escalation |
| NLP sentiment | 20% | **FinBERT + central-bank hawkish/dovish lexicon** on policy statements |

**Configurable weights** â€” override per request:

```bash
# A political risk analyst who wants to emphasise events
curl "https://api.visiblehand.xyz/risk/UA?political_weight=0.6&economic_weight=0.3&nlp_weight=0.1"
```

---

## Why it exists

Commercial equivalents cost **$15,000â€“$50,000/year**:

| Product | Price |
|---------|-------|
| PRS Group ICRG | $15kâ€“$30k/year |
| Bloomberg COUN | $24k/user/year (Terminal) |
| Oxford Economics | $10kâ€“$50k/year |
| Control Risks RiskMap | $20k+/year |

**VisibleHand:** free to self-host. Public API tier available via API key.

---

## Live dashboard

A shareable, no-auth risk heatmap is served at **`/dashboard`** â€” sortable
columns, sub-score bars, confidence, and top drivers per country, auto-refreshing.
The landing page at **`/`** is a polished product page. Both are server-rendered,
zero-JS-framework, and work the moment the app boots.

## API reference

Full interactive docs at `/docs` (auto-generated Swagger).

| Endpoint | Description |
|----------|-------------|
| `GET /` | Landing page |
| `GET /dashboard` | Live country-risk heatmap (HTML) |
| `GET /risk/{code}` | Composite score for one country |
| `GET /risk/compare?countries=US,DE,BR` | Compare multiple countries |
| `GET /risk/{code}/history` | Historical score time-series |
| `GET /indicators/{code}` | Raw indicator data |
| `GET /events/{code}` | Political event feed |
| `GET /health` | Liveness + DB connectivity probe |

## Try it in 60 seconds

```bash
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./visiblehand.db   # or your Postgres URL
python -m scripts.seed_demo_data                  # realistic demo data, 8 countries
uvicorn api.main:app --reload
# open http://localhost:8000/dashboard
```

---

## Self-hosting

### Docker (recommended)

```bash
git clone https://github.com/YOUR_USERNAME/visiblehand
cd visiblehand
docker compose up
```

API available at `http://localhost:8080`. Docs at `http://localhost:8080/docs`.

### Manual

```bash
# Prerequisites: Python 3.12+, PostgreSQL 16

pip install -r requirements.txt
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/visiblehand
export FRED_API_KEY=your_fred_api_key  # free at fred.stlouisfed.org

alembic upgrade head
uvicorn api.main:app --reload
```

Run ingestion manually:

```bash
python -m core.ingestion.scheduler
```

---

## Python SDK

```bash
pip install visiblehand
```

```python
from visiblehand import Client

client = Client(api_key="your-key")  # key optional for public endpoints

# Single country
score = client.risk("IN", economic_weight=0.6, political_weight=0.3, nlp_weight=0.1)
print(f"{score.name}: {score.composite}/100")

# Multi-country comparison
scores = client.compare("US", "DE", "BR", "IN", "ZA")
for s in sorted(scores, key=lambda x: x.composite, reverse=True):
    print(f"{s.country}: {s.composite:.1f}")

# Historical trend
history = client.history("AR", limit=90)
for day in history[-5:]:
    print(day["date"], day["composite"])
```

---

## Architecture

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  Data ingestion (daily, APScheduler)                â”‚
â”‚  World Bank â”€â”                                       â”‚
â”‚  FRED â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â–º PostgreSQL â—„â”€â”€ Scoring engine     â”‚
â”‚  IMF â”€â”€â”€â”€â”€â”€â”€â”€â”˜    (indicators,    (economic scorer   â”‚
â”‚  GDELT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–º events,        political scorer   â”‚
â”‚  Central bank â”€â”€â”€â–º statements)    NLP scorer)        â”‚
â”‚  PDFs/HTML                             â”‚             â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                         â–¼
                              FastAPI REST API
                              (Railway deployment)
                                    â–²
                              Python SDK (PyPI)
```

---

## World-State Model (VH-WSM)

A second-generation modelling layer on top of the score. Instead of just *"what
is the risk score?"* it answers: **what state is this country entering, what
historical states resemble it, which crisis type is becoming more likely, how
could risk spill over, and how certain are we?**

```bash
make worldstate         # feature store + PCA embeddings + analogues
make worldstate-train   # logistic hazard baselines + conformal calibrator
```

| Endpoint | Description |
|----------|-------------|
| `GET /state/{code}` | Full world state (score, cluster, hazards, analogues, spillover, uncertainty) |
| `GET /state/{code}/analogues?k=10` | Nearest historical states + outcomes |
| `GET /state/{code}/hazards?horizon=12` | 8 crisis-type probabilities |
| `GET /state/{code}/spillover` | Region / neighbour / trade pressure |
| `GET /state/{code}/uncertainty` | Conformal interval + abstention |
| `GET /world/graph`, `/world/clusters` | Country graph & state clusters |
| `GET /model/leaderboard`, `/model/card` | Honest benchmarks & model card |
| `GET /world` | **Global state-space map** (PCA scatter + contagion network, HTML) |
| `GET /worldstate/{code}` | World-State page â€” hazard radar, score gauge, analogues (HTML) |

Built with numpy-only baselines (PCA, logistic, split conformal) â€” transparent
and dependency-light. Frontier models (TimesFM, TabPFN, neural Hawkes, GNN) are
benchmark-gated experiments. See [docs/worldstate/overview.md](docs/worldstate/overview.md),
[MODEL_CARD_vh_wsm_0.1.md](MODEL_CARD_vh_wsm_0.1.md), and
[BENCHMARK_vh_wsm_0.1.md](BENCHMARK_vh_wsm_0.1.md).

## Methodology

Full scoring methodology documented in [METHODOLOGY.md](METHODOLOGY.md).

**Short version:**
- Economic score: z-score each indicator against its own 10-year rolling window.
  A country is scored against its own history, not a global mean.
- Political score: exponential decay of event counts (half-life 90 days) so
  recent events weigh more than old ones.
- NLP score: DistilBERT sentiment analysis on central bank press releases â€”
  hawkish language during inflationary regimes signals elevated risk.

---

## Contributing

Pull requests welcome. Key areas for contribution:

- Additional country coverage (currently ~20 countries)
- ACLED integration for more precise political event data
- Multi-language central-bank statement support (ECB, Banque de France, Banxico)
- Calibration study against historical sovereign stress events (see METHODOLOGY Â§6)
- A purpose-built hawkish/dovish model fine-tuned on FOMC/ECB minutes

---

## License

MIT
