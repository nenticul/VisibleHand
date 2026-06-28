"""
Fit the PCA embedder over the feature store, persist embeddings + cluster
labels, and precompute historical analogues for the latest state of each country.

Usage:
    python scripts/build_analogue_index.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np

from api.models.database import SessionLocal, Base, engine, CountryStateFeature
from core.worldstate import registry as R
from core.worldstate.embeddings import (
    StandardizedPCAEmbedder, rows_to_matrix, persist_embeddings,
)
from core.worldstate.analogues import AnalogueSearchService, persist_analogues


def _kmeans(X: np.ndarray, k: int, iters: int = 50, seed: int = 0):
    rng = np.random.default_rng(seed)
    if X.shape[0] <= k:
        return np.arange(X.shape[0]), X
    centers = X[rng.choice(X.shape[0], k, replace=False)]
    labels = np.zeros(X.shape[0], dtype=int)
    for _ in range(iters):
        d = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        new = d.argmin(axis=1)
        if np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            if (labels == j).any():
                centers[j] = X[labels == j].mean(axis=0)
    return labels, centers


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        rows = (
            db.query(CountryStateFeature)
            .filter(CountryStateFeature.model_version == R.FEATURE_VERSION)
            .order_by(CountryStateFeature.as_of_date.asc())
            .all()
        )
        if not rows:
            print("No feature rows. Run materialize_worldstate.py first.")
            return

        X = rows_to_matrix(rows)
        emb = StandardizedPCAEmbedder(n_components=8)
        V = emb.fit_transform(X)
        emb.save()
        evr = emb.explained_variance_ratio_
        print(f"PCA fitted: {V.shape[1]} dims, "
              f"explained variance = {float(np.sum(evr)):.3f} "
              f"({', '.join(f'{x:.2f}' for x in evr)})")

        # cluster (numpy KMeans) for /world/clusters and world_state.cluster
        k = min(6, V.shape[0])
        labels, centers = _kmeans(V, k)
        dist = np.linalg.norm(V - centers[labels], axis=1)
        conf = 1.0 / (1.0 + dist)

        items = []
        cluster_meta = {}
        for i, r in enumerate(rows):
            items.append((r.country_code, r.as_of_date, V[i]))
            cluster_meta[(r.country_code, r.as_of_date)] = (
                f"cluster-{int(labels[i])}", round(float(conf[i]), 4)
            )
        persist_embeddings(db, items)

        # write cluster labels onto the persisted embedding rows
        from api.models.database import CountryStateEmbedding
        for r in db.query(CountryStateEmbedding).filter(
            CountryStateEmbedding.embedding_version == R.EMBEDDING_VERSION
        ).all():
            meta = cluster_meta.get((r.country_code, r.as_of_date))
            if meta:
                r.cluster_label, r.cluster_confidence = meta
        db.commit()
        print(f"Persisted {len(items)} embeddings, {k} clusters.")

        # precompute analogues for the latest state per country
        svc = AnalogueSearchService(db)
        latest_date = {}
        for r in rows:
            if r.country_code not in latest_date or r.as_of_date > latest_date[r.country_code]:
                latest_date[r.country_code] = r.as_of_date
        n_an = 0
        for c, d in latest_date.items():
            analogues = svc.find_analogues(c, d, k=10)
            n_an += persist_analogues(db, c, d, analogues)
        print(f"Precomputed analogues for {len(latest_date)} countries ({n_an} rows).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
