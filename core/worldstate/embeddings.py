"""
Country-state embeddings.

v0.1 ships ``StandardizedPCAEmbedder`` — a transparent, dependency-free
(numpy-only) pipeline: impute → standardise → PCA (SVD) → L2-normalise. PCA is
chosen first because it is easy to debug and its explained variance is
inspectable. UMAP/autoencoder modes are later, optional experiments.

Leakage rule: in any historical backtest, ``fit`` on the training period only,
then ``transform`` the test period with the frozen scaler/PCA (artefacts saved
to disk and reloaded).
"""

from __future__ import annotations

import json
import os
from typing import Optional, Protocol

import numpy as np

from core.worldstate import registry as R
from core.worldstate.schemas import CountryStateFeatureRow


def rows_to_matrix(
    rows: list[CountryStateFeatureRow],
    columns: Optional[list[str]] = None,
) -> np.ndarray:
    """Build an (n, d) float matrix; missing values become np.nan."""
    cols = columns or R.EMBEDDING_FEATURE_COLUMNS
    out = np.full((len(rows), len(cols)), np.nan, dtype=float)
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            v = getattr(r, c, None)
            if v is not None:
                out[i, j] = float(v)
    return out


class BaseStateEmbedder(Protocol):
    name: str
    version: str

    def fit(self, X: np.ndarray) -> None: ...
    def transform(self, X: np.ndarray) -> np.ndarray: ...
    def fit_transform(self, X: np.ndarray) -> np.ndarray: ...


class StandardizedPCAEmbedder:
    """Impute → standardise → PCA → L2-normalise."""

    name = "standardized_pca"
    version = R.EMBEDDING_VERSION

    def __init__(self, n_components: int = 8):
        self.n_components = n_components
        self.impute_: Optional[np.ndarray] = None
        self.mean_: Optional[np.ndarray] = None
        self.std_: Optional[np.ndarray] = None
        self.components_: Optional[np.ndarray] = None
        self.explained_variance_ratio_: Optional[np.ndarray] = None
        self.columns_: list[str] = list(R.EMBEDDING_FEATURE_COLUMNS)

    # ── fit / transform ─────────────────────────────────────────────────────
    def fit(self, X: np.ndarray) -> None:
        X = np.asarray(X, dtype=float)
        self.impute_ = np.nanmean(_nan_safe(X), axis=0)
        Xi = self._impute(X)
        self.mean_ = Xi.mean(axis=0)
        self.std_ = Xi.std(axis=0)
        self.std_[self.std_ < 1e-9] = 1.0
        Xs = (Xi - self.mean_) / self.std_

        k = int(min(self.n_components, Xs.shape[1], max(1, Xs.shape[0] - 1)))
        U, S, Vt = np.linalg.svd(Xs, full_matrices=False)
        comps = Vt[:k]
        # deterministic sign: largest-magnitude loading positive
        for i in range(comps.shape[0]):
            j = int(np.argmax(np.abs(comps[i])))
            if comps[i, j] < 0:
                comps[i] *= -1.0
        self.components_ = comps
        var = (S ** 2)
        self.explained_variance_ratio_ = (var[:k] / var.sum()) if var.sum() > 0 else np.zeros(k)

    def transform(self, X: np.ndarray) -> np.ndarray:
        if self.components_ is None:
            raise RuntimeError("embedder not fitted")
        Xi = self._impute(np.asarray(X, dtype=float))
        Xs = (Xi - self.mean_) / self.std_
        proj = Xs @ self.components_.T
        return _l2_normalize(proj)

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        self.fit(X)
        return self.transform(X)

    def _impute(self, X: np.ndarray) -> np.ndarray:
        Xi = X.copy()
        idx = np.where(np.isnan(Xi))
        if idx[0].size:
            Xi[idx] = np.take(np.nan_to_num(self.impute_), idx[1])
        return Xi

    # ── persistence ─────────────────────────────────────────────────────────
    def save(self, path: str = R.PCA_ARTEFACT_DIR) -> None:
        os.makedirs(path, exist_ok=True)
        np.savez(
            os.path.join(path, "pca.npz"),
            impute=self.impute_, mean=self.mean_, std=self.std_,
            components=self.components_, evr=self.explained_variance_ratio_,
        )
        with open(os.path.join(path, "meta.json"), "w") as f:
            json.dump({
                "name": self.name, "version": self.version,
                "n_components": int(self.components_.shape[0]),
                "columns": self.columns_,
                "explained_variance_ratio": [float(x) for x in self.explained_variance_ratio_],
            }, f, indent=2)

    @classmethod
    def load(cls, path: str = R.PCA_ARTEFACT_DIR) -> "StandardizedPCAEmbedder":
        d = np.load(os.path.join(path, "pca.npz"))
        obj = cls(n_components=int(d["components"].shape[0]))
        obj.impute_ = d["impute"]; obj.mean_ = d["mean"]; obj.std_ = d["std"]
        obj.components_ = d["components"]; obj.explained_variance_ratio_ = d["evr"]
        meta_path = os.path.join(path, "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                obj.columns_ = json.load(f).get("columns", obj.columns_)
        return obj


def _nan_safe(X: np.ndarray) -> np.ndarray:
    """Replace all-nan columns so nanmean doesn't warn/NaN."""
    X = X.copy()
    allnan = np.all(np.isnan(X), axis=0)
    X[:, allnan] = 0.0
    return X


def _l2_normalize(X: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1.0
    return X / norms


# ── persistence of embedding vectors ─────────────────────────────────────────
def persist_embeddings(db, items: list[tuple[str, str, np.ndarray]],
                       version: str = R.EMBEDDING_VERSION) -> int:
    """items = list of (country_code, as_of_date, vector)."""
    from api.models.database import CountryStateEmbedding

    n = 0
    for code, as_of, vec in items:
        vec = np.asarray(vec, dtype=float)
        db.query(CountryStateEmbedding).filter(
            CountryStateEmbedding.country_code == code,
            CountryStateEmbedding.as_of_date == as_of,
            CountryStateEmbedding.embedding_version == version,
        ).delete()
        db.add(CountryStateEmbedding(
            country_code=code, as_of_date=as_of, embedding_version=version,
            embedding_dim=int(vec.size),
            embedding=json.dumps([round(float(x), 6) for x in vec]),
        ))
        n += 1
    db.commit()
    return n
