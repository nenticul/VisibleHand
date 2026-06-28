# Historical analogues

The flagship feature: given a country-state embedding, find the most similar
**past** states and show what happened next.

```
GET /state/AR/analogues?k=5
```

```json
{
  "country": "AR",
  "date": "2026-06-27",
  "embedding_version": "vh-wsm-pca-0.1",
  "analogues": [
    {"rank": 1, "country": "AR", "date": "2018-12-31", "similarity": 0.89,
     "outcome_12m": "imf_programme"},
    {"rank": 2, "country": "EG", "date": "2023-12-31", "similarity": 0.76,
     "outcome_12m": null}
  ]
}
```

## Method

- Cosine similarity over L2-normalised embeddings (dot product).
- Top-`k` after applying the leakage rules below.

## Leakage rules (enforced + unit-tested)

1. **No future** — an analogue's date must be ≤ the query date.
2. **No recent same-country** — exclude the same country within
   `min_date_gap_days` (default 180) of the query.
3. **Outcomes are strictly forward-looking** — 6/12/18-month outcomes are read
   from the crisis dataset *after* the analogue date (annual resolution:
   6/12m → next year, 18m → next two years).

## Storage

Precomputed neighbours land in `historical_analogues` via
`scripts/build_analogue_index.py`; the API can also compute them on demand.
