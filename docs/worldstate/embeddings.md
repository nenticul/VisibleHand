# Embeddings

`core/worldstate/embeddings.py` converts feature rows into dense vectors for
analogue search and clustering.

## v0.1 — `StandardizedPCAEmbedder`

Pure numpy, transparent, debuggable:

```
impute missing → standardise → PCA (SVD) → L2-normalise
```

- 8 components by default (~0.92 explained variance on the seed panel).
- Deterministic: SVD sign is fixed (largest-magnitude loading positive), so the
  same input always yields the same vectors (unit-tested).
- L2-normalised so cosine similarity is a dot product.

## Leakage rule

For historical backtests, **fit on the training period only** and `transform`
the test period with the frozen scaler/PCA. Artefacts are saved to
`data/models/worldstate/pca/v0.1/` (`pca.npz` + `meta.json` with the explained
variance and column order).

## Later modes (optional, not in v0.1)

- `UMAPClusterEmbedder` — UMAP + HDBSCAN/KMeans for dashboard visualisation.
- `AutoencoderEmbedder` — only after the PCA version is stable.

## Storage

Vectors are stored as JSON arrays in `country_state_embeddings` for SQLite/
Postgres portability; swap to `pgvector` for large-scale deployments.
