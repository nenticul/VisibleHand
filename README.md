# VisibleHand

**Open, programmable, point-in-time political-economic risk scoring for every country.**

VisibleHand scores any of 44 countries on a continuous **0–100 risk scale** (0 = very stable, 100 = very high risk), updated daily from live public data. Every score ships with a **confidence** figure, a **Bayesian 95% confidence interval**, signed **driver attributions**, a plain-language **methodology** string, and a **risk band** — so the number is never a black box. Commercial equivalents (PRS ICRG, Bloomberg COUN, Oxford Economics, Control Risks) cost **\$15k–\$50k/year**; this is free and MIT-licensed.

- **Live API:** `https://api.visiblehand.xyz`
- **Website:** `https://visiblehand.xyz`
- **Source:** `https://github.com/nenticul/VisibleHand`

```bash
curl https://api.visiblehand.xyz/risk/BR
```

```json
{
  "country": "BR", "name": "Brazil",
  "composite": 56.2, "confidence": 0.81, "risk_level": "Elevated",
  "ci_95": [47.0, 65.0],
  "breakdown": { "economic": 65.1, "political": 13.4, "nlp_sentiment": 74.2, "governance": 13.0 },
  "top_drivers": ["high_inflation_vs_history", "hawkish_central_bank_language"],
  "driver_attributions": [{ "name": "inflation", "contribution": 6.4, "direction": "risk", "sub_scorer": "economic" }],
  "methodology": "Economic risk 65/100 (weight 45%, confidence 82%). Political risk 13/100 from 2 events (weight 25%). Central-bank language hawkish -> 74/100 (weight 20%). Governance risk 13/100 (weight 10%).",
  "forecast_6m": { "composite": 57.9, "ci_low": 52.1, "ci_high": 63.7 }
}
```

---

## Table of contents

- [What it is](#what-it-is)
- [The scoring model](#the-scoring-model)
- [Data sources](#data-sources)
- [Validation & calibration](#validation--calibration)
- [World-State Model (VH-WSM)](#world-state-model-vh-wsm)
- [The web application](#the-web-application)
- [Data Studio](#data-studio)
- [API reference](#api-reference)
- [Configurable weights & modes](#configurable-weights--modes)
- [Architecture](#architecture)
- [Project layout](#project-layout)
- [Running it yourself](#running-it-yourself)
- [Configuration](#configuration)
- [Python SDK](#python-sdk)
- [Development](#development)
- [Honest limitations](#honest-limitations)
- [Roadmap](#roadmap)
- [License & disclaimer](#license--disclaimer)

---

## What it is

VisibleHand is a self-contained FastAPI service that:

1. **Ingests** macroeconomic, political-event, governance, and central-bank text data from ~13 free/public sources on a daily schedule.
2. **Scores** each country with four transparent sub-scorers blended into one composite, with uncertainty and attribution attached.
3. **Serves** the result as a JSON API, a Python SDK, and a set of server-rendered web tools (a live dashboard, a country-comparison view, a risk map, an interactive **Data Studio**, and a calibration/validation page).
4. **Validates** itself honestly against a labelled historical crisis dataset, with point-in-time reconstruction, bootstrap confidence intervals, no-skill baselines, and a trained early-warning hazard model — and is candid about where coverage is thin.

It runs on Python 3.12 + PostgreSQL, deploys as a single Docker image, and uses numpy/scipy only (no heavy ML runtime required for the core).

---

## The scoring model

The composite is a transparent, **linear blend of four sub-scores** (default weights below — overridable per request). Each sub-scorer is independently inspectable.

| Sub-score | Weight | Method |
|---|---:|---|
| **Economic** | 45% | Robust normalisation (median/MAD, Theil–Sen trend) of ~10 indicators against each country's own history; cross-sectional peer mode available; a nowcast layer folds in IMF WEO near-term projections. |
| **Political** | 25% | A self-exciting **Hawkes process** on GDELT/ACLED events (λ(t) = μ + Σ α·e^(−β(t−tᵢ)), branching ratio capped < 0.95), ACLED intensity taxonomy with fatality weighting, a geographic/trade **contagion** term, a time-decaying sanctions boost, and leader-vulnerability flags. Falls back to decay-weighted event pressure when history is thin. |
| **NLP sentiment** | 20% | FinBERT + a central-bank hawkish/dovish lexicon over policy statements, with a 5-aspect breakdown (inflation, growth, employment, financial stability, external). Press-freedom modifies confidence. |
| **Governance** | 10% | World Bank **WGI** (six live dimensions) plus V-Dem, WJP Rule of Law, TI CPI, and Freedom House, **cross-sectionally percentile-ranked** against the full country population. |

**On top of the linear blend, every score also carries:**

- **Bayesian 95% CI** — a 500-sample Monte-Carlo over each sub-score's uncertainty band.
- **Signed driver attribution** — for a linear composite, contribution = (weight ÷ Σweights) × sub-score, drilled to indicator level for the economic component. No SHAP overhead.
- **6- and 12-month forecast** — Theil–Sen extrapolation of the score trajectory + IMF WEO projections, labelled as extrapolation, not prediction.
- **Regime flags** — e.g. a monetary-regime classifier that reports a `suggested_multiplier` it never silently applies.
- **Risk bands** — Low (<20), Watch (20–40), Elevated (40–60), High (60–75), Severe (75+).

Two normalisation **modes**: `temporal` (vs the country's own history — the default) and `cross_sectional` (vs an external peer + anchor baseline).

---

## Data sources

All free or public. New sources are **ingested and exposed first**, and only added to a scorer's weights after deliberate recalibration — so adding data never silently invalidates the published calibration.

| Source | What it provides | Notes |
|---|---|---|
| **World Bank WDI** | Core macro indicators | No key |
| **World Bank WGI** | Six governance dimensions, 1996→present | No key; live governance signal |
| **IMF WEO** (DataMapper) | GDP growth / inflation projections, debt, current account | No key; feeds the economic nowcast |
| **IMF FSI** | Financial soundness indicators | No key |
| **FRED** | OECD 10Y yields → **sovereign bond spreads** (vs US) | Free API key; queryable, not yet in weights |
| **ILO** | Unemployment | No key |
| **BIS** | Credit / banking aggregates | No key |
| **GDELT** | Global political event stream | No key |
| **ACLED** | Conflict-event taxonomy + fatalities | **OAuth2** (account email + password → 24h Bearer tokens) |
| **V-Dem, WJP, TI CPI, Freedom House** | Governance/rule-of-law indices | Seeded |
| **Central-bank statements** | Policy text for NLP | PDF/HTML parsing |

---

## Validation & calibration

This is what separates VisibleHand from a dashboard: the model is held to a **labelled historical crisis dataset** (sovereign defaults, IMF programmes, currency/banking crises, civil-war onsets, coups — 2000–2023, with hard-negative stable controls) and evaluated with real rigor. All of it is exposed at `/calibration/*` and visualised at `/validation`.

- **Rigorous evaluation harness** (`core/calibration/evaluation.py`): rank-based (Mann-Whitney) AUC + average precision with **stratified bootstrap confidence intervals**, **no-skill baselines** (random, base-rate, crisis-type prior), a look-ahead-free **walk-forward (rolling-origin) calibration CV**, the **Murphy/Brier decomposition** (reliability / resolution / uncertainty / skill), and a paired-bootstrap model-comparison test.
- **C7 point-in-time panel** (`core/calibration/panel.py`): for each crisis event, reconstructs what VisibleHand *would have scored at the start of the crisis year* using only data timestamped before that date (no look-ahead), with a per-year as-of governance population. Coverage is reported honestly (live vs heuristic fallback, and per-sub-scorer coverage).
- **Discrete-time hazard model** (`core/calibration/hazard_model.py`): a Shumway-style logistic hazard for *P(crisis within 12 months)* from the four sub-scores, with **monotonic (coefficient ≥ 0) constraints** so a worse sub-score can never lower predicted risk, plus L2 regularisation. Glass-box coefficients, not a black box.
- **In-browser backtest**: run any of the above live from the Data Studio against the crisis dataset.

**Current honest figures (live, point-in-time):** on the ~48 crisis events the production database can reconstruct without look-ahead, the composite scores **AUC ≈ 0.79 [0.62, 0.92]** and is **well-calibrated** (reliability climbs monotonically; currency crises best-predicted, coups worst). The wider "all-events" number is inflated by heuristic fill and is *not* the honest figure. The current bottleneck is **historical depth of political/governance ingestion** — most reconstructed events are economic-dominated until those back-years backfill. The validation page labels exactly which path produced each number.

---

## World-State Model (VH-WSM)

A second modelling layer that asks not just *"what is the risk score?"* but *"what state is this country entering, what historical states resemble it, which crisis type is becoming likelier, how could risk spill over, and how certain are we?"* — built with numpy-only baselines (PCA embeddings, logistic hazards, split-conformal intervals).

| Endpoint | Description |
|---|---|
| `GET /state/{code}` | Full world state: score, cluster, hazards, analogues, spillover, uncertainty |
| `GET /state/{code}/analogues?k=10` | Nearest historical country-states |
| `GET /state/{code}/hazards?horizon=12` | Crisis-type probabilities |
| `GET /state/{code}/spillover` | Region / neighbour / trade pressure |
| `GET /state/{code}/uncertainty` | Conformal interval + abstention decision |
| `GET /state/{code}/embedding` | The country-state embedding vector + cluster |
| `GET /world/graph`, `/world/clusters` | Country graph & state clusters |
| `GET /model/leaderboard`, `/model/card` | Benchmarks & model card |

Offline build scripts: `scripts/materialize_worldstate.py`, `build_analogue_index.py`, `train_hazard_models.py`, `export_static_worldstate.py`, `evaluate_worldstate.py`. See `docs/worldstate/`.

---

## The web application

Every page is server-rendered, framework-free, and works the moment the app boots.

| Page | What it is |
|---|---|
| `GET /` | Landing / product page |
| `GET /dashboard` | Live country-risk heatmap — sortable, sub-score bars, confidence, drivers |
| `GET /dashboard/{code}` | Per-country detail |
| `GET /compare` | Side-by-side country comparison |
| `GET /map` | Risk map / modelling view |
| `GET /studio` | **Data Studio** — the interactive analysis tool (see below) |
| `GET /validation` | Calibration & validation — ROC, reliability diagram, baselines, Brier decomposition, the live result, and the hazard model |
| `GET /worldstate/{code}` | World-State page — hazard radar, gauge, analogues |
| `GET /world` | Global state-space map (PCA scatter + contagion network) |
| `GET /methodology` | Methodology write-up |
| `GET /docs` | Interactive API explorer (custom-skinned Swagger UI) |
| `GET /api` | Human-readable API reference |

---

## Data Studio

`GET /studio` is a self-contained, framework-free interactive tool — styled as a **retro instrument**: a dot-matrix LED status header (live weights readout), a dithered device casing, beveled controls, and CRT-style chart "screens" with scanlines and corner registration marks. Plain language throughout — it's a tool for a job, not a demo reel.

What you can do, all client-side:

- **Re-blend live** — drag the four component-weight sliders and every country re-ranks instantly; the LED header echoes the current weights.
- **Choose data sources** — toggle each scorer family (Economic / Political / NLP / Governance) in or out of the blend, with provenance chips showing the real underlying sources.
- **Analyse** — selectable X/Y scatter with an OLS fit line + R², a Pearson correlation matrix, a distribution histogram, and a sortable/filterable ranked table with 95% CIs.
- **Run scenarios** — shock the sub-scores (or apply stress presets like "2008 GFC"), watch the composite and risk-band crossings ripple across all countries; a per-country **tornado** sensitivity chart and an **inverse solver** ("what's the smallest single-driver cut to leave the current band?").
- **Backtest** — run the evaluation harness (heuristic or live point-in-time) against the crisis dataset and read AUC/CIs, baselines, walk-forward calibration, and panel coverage inline.
- **Query** — a real **SQL console (DuckDB-WASM)** that runs entirely in your browser over the cross-section: joins, aggregates, window functions, `CORR`, with CSV export.
- **Export** — CSV, JSON, and an auto-generated Python `requests` snippet that reproduces the current view against the live API.

---

## API reference

Interactive docs at `/docs`; OpenAPI schema at `/openapi.json`.

**Risk**
| Endpoint | Description |
|---|---|
| `GET /risk/{code}` | Composite score for one country (`?explain=true` for a structured driver tree) |
| `GET /risk/compare?countries=US,DE,BR` | Compare several countries |
| `GET /risk/bulk` | All countries at once |
| `GET /risk/movers` | Biggest recent score moves |
| `GET /risk/baseline` | Cross-sectional baseline reference |
| `GET /risk/{code}/history` | Score time-series |
| `GET /risk/{code}/forecast` | 6/12-month extrapolation |
| `GET /risk/{code}/drivers` | Ranked driver attributions |

**Indicators / events / governance / NLP**
| Endpoint | Description |
|---|---|
| `GET /indicators/{code}` | Raw indicator data (`?metric=sovereign_spread`, etc.) |
| `GET /events/{code}` | Political event feed |
| `GET /governance/{code}` | Governance sub-score breakdown |
| `GET /risk/{code}/aspects` | 5-aspect NLP breakdown |
| `GET /statements/{code}` | Central-bank statement feed |

**Calibration**
| Endpoint | Description |
|---|---|
| `GET /calibration/summary` | Methodology + headline calibration |
| `GET /calibration/roc` | ROC curve / AUC / Brier / PR-AUC |
| `GET /calibration/evaluation?source=heuristic\|live` | Full harness (bootstrap CIs, baselines, walk-forward, decomposition) |
| `GET /calibration/baselines` | No-skill floors |
| `GET /calibration/panel` | C7 point-in-time coverage report |
| `GET /calibration/hazard-model` | Trained discrete-time hazard model |
| `GET /calibration/dataset` | The labelled crisis dataset |

**World-State** — see [the VH-WSM table above](#world-state-model-vh-wsm).

**Meta** — `GET /health`, `/health/live`, `/health/ready`, `/health/scores`, `/metrics` (Prometheus).

---

## Configurable weights & modes

Override the blend per request:

```bash
# A political analyst who wants to emphasise events
curl "https://api.visiblehand.xyz/risk/UA?political_weight=0.6&economic_weight=0.3&nlp_weight=0.1"

# Score against peers instead of own history
curl "https://api.visiblehand.xyz/risk/TR?mode=cross_sectional"

# Structured explanation tree
curl "https://api.visiblehand.xyz/risk/AR?explain=true"
```

Weights are renormalised automatically; omitted components are dropped and the rest re-weighted.

---

## Architecture

```
Ingestion (daily, APScheduler @ 02:00 UTC)
  World Bank WDI/WGI ─┐
  IMF WEO / FSI ──────┤
  FRED ───────────────┤
  ILO / BIS ──────────┼──►  PostgreSQL  ◄── Scoring engine
  GDELT / ACLED ──────┤     (indicators,     economic · political
  Central-bank text ──┘      events,          nlp · governance
                             governance,      → composite + CI
                             statements,         + attribution
                             scores,             + forecast)
                             worldstate)
                                  │
                                  ▼
                        FastAPI  (Railway / Docker)
                        ├─ JSON API  (/risk, /calibration, /state, …)
                        ├─ Web tools (/dashboard, /studio, /validation, …)
                        ├─ /docs (Swagger)  ·  /metrics (Prometheus)
                        └─ Python SDK (sdk/)  ·  React site (website/)
```

---

## Project layout

```
api/
  main.py              FastAPI app, lifespan, health, custom /docs
  config.py            Pydantic settings (env-driven)
  dependencies.py      get_db, optional_api_key
  models/              SQLAlchemy tables + Pydantic schemas
  routers/             risk, indicators, events, governance, nlp,
                       calibration, worldstate, dashboard (all HTML pages)
  observability.py     Prometheus middleware, structured logging
core/
  scoring/             economic, political, nlp_scorer, governance,
                       baseline, composite, regime, stats
  ingestion/           worldbank, wgi, imf, imf_fsi, fred, ilo, bis,
                       gdelt, acled, centralbank, scheduler, http
  nlp/                 finbert, lexicon, sentiment, aspect_scorer, parsers
  calibration/         crisis_dataset, backtest, evaluation, panel,
                       hazard_model, optimizer
  worldstate/          features, embeddings, analogues, hazards, graph,
                       uncertainty, service, registry, schemas
scripts/               seed_demo_data, materialize/train/export worldstate,
                       export_finbert_onnx, smoke_test
sdk/                   Python client package (pip install visiblehand)
website/               React + Vite + Tailwind marketing/app site
docs/                  methodology, worldstate, sdk, getting-started
tests/                 173 tests (pytest; SQLite-stubbed, no Postgres needed)
Dockerfile  railway.json  docker-compose.yml  alembic/  .env.example
```

---

## Running it yourself

### Quick start (SQLite + demo data, ~60s)

```bash
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./visiblehand.db
python -m scripts.seed_demo_data        # realistic demo data
uvicorn api.main:app --reload
# open http://localhost:8000/studio
```

### Docker

```bash
git clone https://github.com/nenticul/VisibleHand
cd VisibleHand
docker compose up
# API at http://localhost:8080  ·  docs at /docs
```

### Production (PostgreSQL)

```bash
# Python 3.12+, PostgreSQL 16
pip install -r requirements-prod.txt
export DATABASE_URL=postgresql://user:pass@localhost:5432/visiblehand
export FRED_API_KEY=...           # free at fred.stlouisfed.org
alembic upgrade head
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Railway

`railway.json` is included: Dockerfile build, `alembic upgrade head` predeploy, `/health/live` healthcheck. Set the environment variables below in the Railway dashboard and it deploys on push. Ingestion runs automatically at 02:00 UTC.

Trigger ingestion manually any time:

```bash
python -m core.ingestion.scheduler
```

---

## Configuration

Copy `.env.example` to `.env`. Key variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `sqlite:///...` (dev) or `postgresql://...` (prod) |
| `FRED_API_KEY` | Sovereign bond spreads (free) |
| `ACLED_EMAIL` / `ACLED_PASSWORD` | ACLED OAuth2 (account password → 24h tokens) |
| `API_KEY` | If set, callers must send `X-API-Key`; blank = open |
| `RATE_LIMIT` | e.g. `120/minute` per IP |
| `INGESTION_ENABLED` / `INGESTION_HOUR_UTC` | Daily scheduler on/off + hour |
| `NLP_MODEL_DIR` / `NLP_MODEL` | ONNX FinBERT dir / HF fallback |
| `LOG_LEVEL`, `ENVIRONMENT`, `STRUCTURED_LOGGING`, `PROMETHEUS_ENABLED`, `SENTRY_DSN` | Observability |
| `SCORE_CACHE_TTL`, `SCORING_ROLLING_WINDOW` | Scoring cache + window |

WGI, IMF WEO/FSI, World Bank, GDELT, ILO, and BIS need **no key**.

---

## Python SDK

```python
from visiblehand import Client

client = Client()                              # api_key optional for public endpoints
score = client.risk("IN", economic_weight=0.6, political_weight=0.3, nlp_weight=0.1)
print(f"{score.name}: {score.composite}/100")

for s in sorted(client.compare("US", "DE", "BR", "ZA"), key=lambda x: -x.composite):
    print(f"{s.country}: {s.composite:.1f}")

for day in client.history("AR", limit=90)[-5:]:
    print(day["date"], day["composite"])
```

The SDK lives in `sdk/`. See `docs/sdk/python.md`.

---

## Development

```bash
pip install -r requirements.txt
pytest -q                      # 173 tests; SQLite-stubbed, no Postgres/network needed
python -m scripts.smoke_test   # end-to-end smoke check
```

Tests run against an in-memory SQLite stub (`tests/conftest.py`) so CI needs no database. On Windows, exclude `.venv` from Defender if `.pyd` imports hang.

---

## Honest limitations

- The four-component blend is **linear and transparent** by design; it is not a black-box model and does not claim to be one.
- The **live, point-in-time** AUC (≈0.79 on ~48 reconstructable events) is a genuine but small-sample result; read the confidence interval, not the point. Out-of-panel crisis countries fall back to a documented heuristic, and the validation page says so.
- Most point-in-time reconstructions are currently **economic-dominated** because political/governance history is shallow before ~2018; deeper ingestion back-years are the main unlock (WGI is already backfilled to 1996).
- ACLED is non-commercial without a paid licence; respect each source's terms (`DATA_SOURCES.md`, `TERMS_OF_USE.md`).
- Forecasts are **extrapolations**, not predictions, and are labelled as such.

---

## Roadmap

- Backfill historical political/governance depth to make the live backtest multi-signal (and unblock richer models).
- An EBM/GA²M monotonic additive blend as an opt-in alternative to the linear composite (default stays linear to preserve calibration).
- A full historical calibration study toward a citable, fully-powered AUC.
- Extending the instrument design language to the remaining web pages.

---

## License & disclaimer

**MIT.** VisibleHand is a research and analysis tool. Scores are model outputs, not financial, investment, or political advice, and carry uncertainty by construction. Verify before relying on any number for a real decision, and comply with the terms of each upstream data source.

*Built with Python, FastAPI, PostgreSQL, numpy/scipy, and DuckDB-WASM.*
