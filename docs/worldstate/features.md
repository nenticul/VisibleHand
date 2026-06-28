# Feature store

`core/worldstate/features.py` materialises one row per `(country, as_of_date)`
into `country_state_features` from data already persisted by the base system —
**no network calls, deterministic, leakage-safe**.

## Sources

- Base composite + component scores + confidence/CI (live snapshot)
- Economic indicator z-scores (robust median/MAD, **expanding window ≤ as_of**)
- Governance structural risk (V-Dem / WJP / TI / Freedom House, latest ≤ as_of)
- Political event windows (30/90/180-day counts + severity, ≤ as_of)
- NLP aspect scores (latest central-bank statement ≤ as_of)
- Spillover aggregates (filled by `graph.add_spillover`)

## Leakage safety

Every historical row uses only observations dated on or before `as_of_date`. The
robust z-score for year *Y* is computed against the country's own history up to
*Y* (expanding window), never the full series. Unit-tested in
`tests/test_worldstate.py`.

## Quality

Each row carries `missing_feature_count` and `data_quality_score`
(= fraction of expected modelling features present). Rows with low quality drive
the abstention logic in the uncertainty layer.

## Panel

The materialiser builds the annual panel (2013–2023 year-ends, proxy scores)
plus one **live** snapshot per country (real `CountryScore`). The annual panel
gives the embeddings/analogues/hazards their temporal depth; the live row is what
`/state/{code}` serves.
