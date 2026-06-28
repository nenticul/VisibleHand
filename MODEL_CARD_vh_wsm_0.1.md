# Model Card — VH-WSM v0.1 (VisibleHand World-State Model)

> Transparency framework following the Model Cards convention (intended use,
> data, evaluation, limitations, ethics).

## Overview

VH-WSM is a second-generation modelling layer on top of the VisibleHand
country-risk API. It turns a single risk score into a richer **world state**:
a country-state embedding, nearest historical analogues, per-crisis-type hazard
probabilities, cross-country spillover, and calibrated uncertainty.

| | |
|---|---|
| Model version | `vh-wsm-0.1.0` |
| Feature version | `vh-wsm-features-0.1` |
| Embedding version | `vh-wsm-pca-0.1` |
| Base score version | `visiblehand-0.3.0` |
| Universe | 44 countries (see below) |
| Dependencies | numpy + scipy only (no sklearn/torch required) |

## Intended use

- Research and situational awareness over political-economic risk.
- Characterising what *kind* of state a country is in (cluster), what past
  states it resembles (analogues), and which crisis types are becoming more
  likely (hazards), with explicit uncertainty.

**Not** intended for: automated trading, credit decisions, or any
consequential decision without human review. Hazard probabilities are
**experimental** until calibration is independently validated.

## Components

| Layer | Method (v0.1) | Notes |
|-------|---------------|-------|
| Feature store | Materialised from existing scores + indicators + governance + events | Leakage-safe expanding-window robust z-scores |
| Embeddings | Standardised **PCA** (numpy SVD), L2-normalised, 8 dims | Transparent; ~0.92 explained variance |
| Analogues | Cosine NN with leakage guards | Excludes future dates & recent same-country |
| Hazards | Class-weighted **logistic** baseline + heuristic fallback | Per (target, horizon) |
| Spillover | Deterministic region / neighbour / trade graph | GNN deferred (benchmark-gated) |
| Uncertainty | **Split conformal** intervals + abstention | Coverage reported |

## Data

- **Features:** VisibleHand indicators (World Bank/IMF/BIS/ILO), governance
  (V-Dem/WJP/TI/Freedom House), political events (GDELT/ACLED), central-bank
  NLP. Annual panel 2013–2023 + a live snapshot.
- **Crisis labels:** curated derived dataset (~220 country-year events,
  2000–2023) from IMF HPDD, Laeven & Valencia, UCDP, REIGN, World Bank — onset
  year labels only, not redistributed raw data.

## Evaluation

Temporal split (train ≤2018, test 2019–2023), no future leakage. Both the
logistic baseline and a transparent heuristic baseline are logged for honest
comparison. See [BENCHMARK_vh_wsm_0.1.md](BENCHMARK_vh_wsm_0.1.md) and
`GET /model/leaderboard`. Conformal coverage is validated (~0.90 empirical at
0.90 target).

## Limitations

- Hazard probabilities are experimental; positive labels are sparse for several
  targets (banking, civil_conflict, coup) so those fall back to the heuristic.
- Annual-resolution labels make 6/12/18-month horizons approximate.
- The feature panel starts in 2013; deep crises (2000–2012) inform labels only.
- `sanctions_shock` has no direct label coverage → heuristic only.
- Frontier models (TimesFM, TabPFN, neural Hawkes, temporal GNN) are **not**
  shipped in v0.1; they are benchmark-gated experiments (build guide §6–§10).

## Ethical considerations

- Outputs can stigmatise countries; always presented with uncertainty and
  abstention, and labelled experimental.
- Restricted datasets (e.g. ACLED) are bring-your-own-key; nothing licence-
  restricted is redistributed.
- The system is transparent (open methodology, numpy baselines, published
  benchmarks) so claims can be independently audited.

## Universe

```
AR AU BD BR CA CH CL CN CO DE EG ES ET FR GB GH GR HU ID IN IT JP KE KR
LB LK MA MX MY NG NL PE PH PK PL RU SA TH TR UA US VE VN ZA
```

## Reproduce

```bash
python scripts/materialize_worldstate.py --date today --all
python scripts/build_analogue_index.py
python scripts/train_hazard_models.py --all
python scripts/evaluate_worldstate.py
```
