"""
VH-WSM World-State Model API.

All endpoints are read-only over the materialised feature store / embeddings /
hazard predictions. Run the offline scripts (materialize_worldstate,
build_analogue_index, train_hazard_models) to populate the tables first.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from api.dependencies import get_db
from core.worldstate import registry as R
from core.worldstate import service

router = APIRouter(prefix="", tags=["worldstate"])

_CODE = Path(..., min_length=2, max_length=3, pattern="^[A-Za-z]{2,3}$")


def _norm(code: str) -> str:
    return code.upper()


# ── per-country ──────────────────────────────────────────────────────────────
@router.get("/state/{country_code}")
async def state(country_code: str = _CODE, db: Session = Depends(get_db)) -> dict:
    code = _norm(country_code)
    result = service.build_state(db, code)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No world-state data for {code}. "
                   f"Run: python scripts/materialize_worldstate.py --date today --all",
        )
    return result


@router.get("/state/{country_code}/embedding")
async def embedding(country_code: str = _CODE, db: Session = Depends(get_db)) -> dict:
    code = _norm(country_code)
    result = service.get_embedding(db, code)
    if not result:
        raise HTTPException(404, f"No embedding for {code}. Run build_analogue_index.py")
    return result


@router.get("/state/{country_code}/analogues")
async def analogues(
    country_code: str = _CODE,
    k: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    code = _norm(country_code)
    return service.get_analogues(db, code, k=k)


@router.get("/state/{country_code}/hazards")
async def hazards(
    country_code: str = _CODE,
    horizon: int = Query(12, description="Horizon in months (6/12/18)"),
    db: Session = Depends(get_db),
) -> dict:
    code = _norm(country_code)
    if horizon not in R.HORIZONS_MONTHS:
        raise HTTPException(422, f"horizon must be one of {R.HORIZONS_MONTHS}")
    result = service.get_hazards(db, code, horizon=horizon)
    if not result:
        raise HTTPException(404, f"No world-state data for {code}.")
    return result


@router.get("/state/{country_code}/spillover")
async def spillover(country_code: str = _CODE, db: Session = Depends(get_db)) -> dict:
    return service.get_spillover(db, _norm(country_code))


@router.get("/state/{country_code}/uncertainty")
async def uncertainty(country_code: str = _CODE, db: Session = Depends(get_db)) -> dict:
    code = _norm(country_code)
    result = service.get_uncertainty(db, code)
    if not result:
        raise HTTPException(404, f"No world-state data for {code}.")
    return result


# ── world-level ──────────────────────────────────────────────────────────────
@router.get("/world/graph")
async def world_graph(db: Session = Depends(get_db)) -> dict:
    from api.models.database import CountryStateFeature

    rows = (
        db.query(CountryStateFeature)
        .filter(CountryStateFeature.model_version == R.FEATURE_VERSION)
        .order_by(CountryStateFeature.as_of_date.desc())
        .all()
    )
    latest: dict[str, CountryStateFeature] = {}
    for r in rows:
        latest.setdefault(r.country_code, r)

    nodes = [{
        "country": c, "region": R.REGION.get(c),
        "score": round(float(r.visiblehand_score), 2), "risk_band": r.risk_band,
    } for c, r in sorted(latest.items())]

    edges = []
    seen = set()
    for c in latest:
        for n in R.NEIGHBOURS.get(c, []):
            if n in latest:
                key = tuple(sorted((c, n)))
                if key not in seen:
                    seen.add(key)
                    edges.append({"source": key[0], "target": key[1], "type": "border"})
        for p, w in R.TRADE_PARTNERS.get(c, {}).items():
            if p in latest:
                edges.append({"source": c, "target": p, "type": "trade", "weight": w})

    return {"nodes": nodes, "edges": edges, "n_countries": len(nodes)}


@router.get("/world/clusters")
async def world_clusters(db: Session = Depends(get_db)) -> dict:
    from api.models.database import CountryStateEmbedding

    rows = (
        db.query(CountryStateEmbedding)
        .filter(CountryStateEmbedding.embedding_version == R.EMBEDDING_VERSION)
        .order_by(CountryStateEmbedding.as_of_date.desc())
        .all()
    )
    latest: dict[str, CountryStateEmbedding] = {}
    for r in rows:
        latest.setdefault(r.country_code, r)

    clusters: dict[str, list[str]] = {}
    for c, r in latest.items():
        label = r.cluster_label or f"region:{R.REGION.get(c, 'unknown')}"
        clusters.setdefault(label, []).append(c)

    return {
        "embedding_version": R.EMBEDDING_VERSION,
        "n_clusters": len(clusters),
        "clusters": [{"label": k, "members": sorted(v), "size": len(v)}
                     for k, v in sorted(clusters.items())],
    }


# ── model metadata ───────────────────────────────────────────────────────────
@router.get("/model/leaderboard")
async def leaderboard(db: Session = Depends(get_db)) -> dict:
    from api.models.database import ModelLeaderboard

    rows = (
        db.query(ModelLeaderboard)
        .order_by(ModelLeaderboard.target, ModelLeaderboard.horizon_months,
                  ModelLeaderboard.auc.desc())
        .all()
    )
    return {
        "n_entries": len(rows),
        "entries": [{
            "model_name": r.model_name, "model_version": r.model_version,
            "target": r.target, "horizon_months": r.horizon_months,
            "auc": r.auc, "pr_auc": r.pr_auc, "brier_score": r.brier_score,
            "calibration_error": r.calibration_error, "log_loss": r.log_loss,
            "train_period": r.train_period, "test_period": r.test_period,
            "n_samples": r.n_samples, "n_events": r.n_events,
        } for r in rows],
    }


@router.get("/model/card")
async def model_card() -> dict:
    return {
        "model": "VH-WSM — VisibleHand World-State Model",
        "version": R.MODEL_VERSION,
        "feature_version": R.FEATURE_VERSION,
        "embedding_version": R.EMBEDDING_VERSION,
        "base_score_version": R.BASE_SCORE_VERSION,
        "intended_use": (
            "Research and situational awareness: country-state characterisation, "
            "historical analogues, crisis-type hazard signals, spillover, and "
            "calibrated uncertainty over a 44-country universe."
        ),
        "components": {
            "embeddings": "Standardised PCA (numpy), L2-normalised",
            "analogues": "cosine NN with leakage guards + crisis-outcome attribution",
            "hazards": "class-weighted logistic baseline + transparent heuristic fallback",
            "spillover": "deterministic region/neighbour/trade graph aggregates",
            "uncertainty": "split conformal intervals + abstention",
        },
        "limitations": [
            "Hazard probabilities are EXPERIMENTAL until calibration is validated.",
            "Annual-resolution labels limit horizon precision (6/12/18m approximated).",
            "Historical feature panel begins 2013; deep crises (2000-2012) are label-only.",
            "Frontier models (TimesFM, TabPFN, neural Hawkes, GNN) are not shipped in v0.1.",
        ],
        "universe": R.UNIVERSE,
        "docs": "/docs and docs/worldstate/overview.md",
        "card_file": "MODEL_CARD_vh_wsm_0.1.md",
    }
