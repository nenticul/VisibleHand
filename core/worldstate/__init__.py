"""
VH-WSM — VisibleHand World-State Model.

A second-generation modelling layer built on top of the base VisibleHand
scoring system. It turns the question "what is this country's risk score?" into
"what state is this country entering, what historical states resemble it, which
crisis type is becoming more likely, how could risk spill over, and how certain
are we?".

Layers (see the module of the same name):
    features     — materialise modelling features from existing persisted data
    embeddings   — dense country-state vectors (transparent numpy PCA in v0.1)
    analogues    — nearest historical-state search (leakage-safe)
    graph        — deterministic cross-country spillover features
    hazards      — per-crisis-type probability models (numpy logistic baseline)
    uncertainty  — conformal prediction intervals + abstention
    service      — orchestration for the /state/{code} endpoint

Design rules (non-negotiable, see the build guide §18):
    1. No future leakage — historical computations use only data <= as_of_date.
    2. Baselines first — transparent numpy models; frontier models are optional.
    3. Everything versioned — every output carries model/feature/embedding version.
"""

from core.worldstate import registry  # noqa: F401

__all__ = ["registry"]
