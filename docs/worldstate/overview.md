# VH-WSM — World-State Model

VH-WSM is a modelling layer on top of the VisibleHand country-risk API. It
reframes the product from *"what is this country's risk score?"* to:

> What state is this country entering, what historical states resemble it, which
> crisis type is becoming more likely, how could risk spill over, and how
> certain are we?

## Pipeline

```
VisibleHand scores / features
        ↓  features.py        →  country_state_features
        ↓  embeddings.py      →  country_state_embeddings (PCA, L2)
        ↓  analogues.py       →  historical_analogues
        ↓  hazards.py         →  crisis_hazard_predictions + model_leaderboard
        ↓  graph.py           →  spillover features
        ↓  uncertainty.py     →  conformal intervals + abstention
        ↓  service.py / API   →  /state/{code} …
```

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /state/{code}` | Full world state (score, cluster, hazards, analogues, spillover, uncertainty) |
| `GET /state/{code}/embedding` | Country-state vector + cluster |
| `GET /state/{code}/analogues?k=10` | Nearest historical states + outcomes |
| `GET /state/{code}/hazards?horizon=12` | Per-crisis-type probabilities |
| `GET /state/{code}/spillover` | Region/neighbour/trade pressure |
| `GET /state/{code}/uncertainty` | Conformal interval + abstain flag |
| `GET /world/graph` | Country graph (nodes + border/trade edges) |
| `GET /world/clusters` | State clusters |
| `GET /model/leaderboard` | Benchmark results |
| `GET /model/card` | Model metadata, limitations, universe |

## Visual pages (HTML)

| Page | Description |
|------|-------------|
| `GET /world` | Global state-space map — PCA(2) scatter of all countries, state clusters, regional risk bars, contagion network |
| `GET /worldstate/{code}` | Per-country World-State — composite gauge with CI + conformal band, 8-axis crisis-hazard radar, sub-score bars, analogue table with similarity meters, spillover, provenance |

## Build it

```bash
python scripts/materialize_worldstate.py --date today --all
python scripts/build_analogue_index.py
python scripts/train_hazard_models.py --all
python scripts/evaluate_worldstate.py
python scripts/export_static_worldstate.py --out public/api   # optional static mode
```

See: [features](features.md) · [embeddings](embeddings.md) ·
[analogues](analogues.md) · [hazards](hazards.md) ·
[uncertainty](uncertainty.md) · [limitations](limitations.md).
