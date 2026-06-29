"""Calibration and methodology transparency endpoints."""

from __future__ import annotations

import logging
import time
from functools import lru_cache

from fastapi import APIRouter, Query, Depends
from sqlalchemy.orm import Session

from api.dependencies import get_db
from api.models.schemas import CalibrationSummary
from core.scoring.composite import DEFAULT_WEIGHTS

log = logging.getLogger(__name__)
router = APIRouter(prefix="/calibration", tags=["calibration"])

# The C7 panel materialisation hits the DB ~hundreds of times; cache it (the
# underlying indicator history only changes when ingestion runs, ~daily).
_PANEL_TTL = 1800.0
_panel_cache: dict = {"data": None, "ts": 0.0}


def cached_panel(db) -> dict:
    now = time.time()
    if _panel_cache["data"] is not None and now - _panel_cache["ts"] < _PANEL_TTL:
        return _panel_cache["data"]
    from core.calibration.panel import materialize_crisis_panel
    data = materialize_crisis_panel(db)
    _panel_cache.update(data=data, ts=now)
    return data


@lru_cache(maxsize=1)
def _cached_backtest():
    """Run backtest once and cache result (expensive — scores ~220 events)."""
    from core.calibration.backtest import run_backtest
    return run_backtest()


@lru_cache(maxsize=4)
def _cached_evaluation(n_boot: int):
    """Run the full evaluation harness once per n_boot (bootstrap is expensive)."""
    from core.calibration.evaluation import run_evaluation
    return run_evaluation(n_boot=n_boot)


@router.get("/summary", response_model=CalibrationSummary)
async def calibration_summary() -> CalibrationSummary:
    """
    Published methodology and calibration summary with live AUC estimate.
    """
    try:
        result = _cached_backtest()
        auc_note = (
            f"Heuristic backtest AUC={result.auc:.3f} on {result.n_crises} crisis events "
            f"({result.n_events} total). Full re-scoring with live DB is recommended."
        )
    except Exception as exc:
        log.warning("backtest failed: %s", exc)
        auc_note = "Backtest unavailable."

    return CalibrationSummary(
        description=(
            "VisibleHand scores countries 0-100 by blending four sub-scorers. "
            "Economic (robust MAD/Theil-Sen normalisation, 10 indicators from "
            "World Bank WDI, IMF WEO, BIS, ILO, IMF FSI). Political (Hawkes "
            "process on GDELT/ACLED events, contagion network, ACLED taxonomy). "
            "with 5-aspect breakdowns). Governance (live World Bank WGI six "
            "dimensions plus V-Dem, WJP, TI CPI, Freedom House, cross-sectional "
            "normalisation). Sovereign bond spreads (FRED OECD 10Y vs US) and IMF "
            "WEO projections are also ingested. "
            + auc_note
        ),
        methodology_version="0.3.0",
        component_weights=DEFAULT_WEIGHTS,
        note=(
            "Calibration preprint in preparation. Target: SSRN Q4 2026. "
            "Full ROC curves and calibration plots at /calibration/roc."
        ),
    )


@router.get("/roc")
async def calibration_roc(
    include_curve: bool = Query(False, description="Include full ROC/PR curve arrays"),
) -> dict:
    """
    ROC-AUC calibration data from backtest against ~220 historical crisis events.
    Set include_curve=true to get the full curve point arrays.
    """
    try:
        result = _cached_backtest()
        response: dict = {
            "status": "available",
            "auc": result.auc,
            "brier_score": result.brier_score,
            "pr_auc": result.pr_auc,
            "n_events": result.n_events,
            "n_crises": result.n_crises,
            "by_crisis_type": result.by_crisis_type,
            "note": result.note,
            "dataset_note": (
                "Crisis labels from IMF HPDD, Laeven & Valencia (2012/2018), "
                "UCDP Conflict Catalogue, REIGN, and World Bank (2000-2023). "
                "220 events: sovereign defaults, IMF programmes, currency crises, "
                "banking crises, civil war onsets, coups. "
                "Scores are heuristic estimates; full scoring from live DB "
                "will be published in the calibration preprint."
            ),
        }
        if include_curve:
            response["roc_curve"] = result.roc_curve
            response["pr_curve"] = result.pr_curve
        return response

    except Exception as exc:
        log.exception("calibration/roc failed")
        return {
            "status": "error",
            "message": str(exc),
        }


@router.get("/evaluation")
async def calibration_evaluation(
    n_boot: int = Query(2000, ge=200, le=5000,
                        description="Bootstrap replicates for the AUC/AP confidence intervals."),
    source: str = Query("heuristic", pattern="^(heuristic|live)$",
                        description="'heuristic' = synthetic bridge; 'live' = point-in-time "
                                    "DB composite scores (C7 panel) where coverage exists."),
    db: Session = Depends(get_db),
) -> dict:
    """
    Rigorous evaluation harness (Tier-0): the headline AUC/AP **with bootstrap
    confidence intervals**, no-skill **baselines**, a look-ahead-free **temporal
    (walk-forward) calibration CV**, and the **Murphy/Brier decomposition** into
    reliability / resolution / uncertainty.

    `source=live` materialises the C7 point-in-time crisis panel — reconstructing
    what VisibleHand would have scored at the start of each crisis year from data
    known beforehand — and uses those composite scores where the DB has coverage,
    falling back to the heuristic elsewhere. `score_source` reports the split
    honestly. `source=heuristic` (default, cached) is the fully-synthetic bridge.
    """
    try:
        if source == "live":
            from core.calibration.evaluation import run_evaluation, live_only_evaluation
            panel = cached_panel(db)
            rep = run_evaluation(db_scores=panel["scores"], n_boot=n_boot)
            out = rep.__dict__
            out["panel_coverage"] = panel["coverage"]
            out["live_only"] = live_only_evaluation(panel["coverage"]["live_events"], n_boot=n_boot)
            return out
        rep = _cached_evaluation(n_boot)
        return rep.__dict__
    except Exception as exc:
        log.exception("calibration/evaluation failed")
        return {"status": "error", "message": str(exc)}


@router.get("/hazard-model")
async def calibration_hazard_model(
    l2: float = Query(1.0, ge=0.0, le=100.0, description="L2 shrinkage strength."),
    monotone: bool = Query(True, description="Constrain every coefficient ≥ 0 (risk-increasing)."),
    db: Session = Depends(get_db),
) -> dict:
    """
    Discrete-time logistic hazard model (Shumway 2001) trained on the C7
    point-in-time panel: P(crisis within 12 months) from the four sub-scores,
    with monotonic (coefficient ≥ 0) constraints + L2. Returns the glass-box
    coefficients, in-sample AUC/Brier, and honest training coverage. Does not
    change the published composite — it's an opt-in early-warning probability.
    """
    try:
        from core.calibration.hazard_model import train_from_panel
        return train_from_panel(panel=cached_panel(db), l2=l2, monotone=monotone)
    except Exception as exc:
        log.exception("calibration/hazard-model failed")
        return {"status": "error", "message": str(exc)}


@router.get("/panel")
async def calibration_panel(db: Session = Depends(get_db)) -> dict:
    """
    C7 point-in-time panel coverage: which crisis events the DB can score for
    real (no look-ahead) vs which fall back to the heuristic, plus the live
    reconstructed scores. The honest denominator behind a `source=live` AUC.
    """
    try:
        panel = cached_panel(db)
        return {"status": "available", "coverage": panel["coverage"]}
    except Exception as exc:
        log.exception("calibration/panel failed")
        return {"status": "error", "message": str(exc)}


@router.get("/baselines")
async def calibration_baselines() -> dict:
    """No-skill floors (random, base-rate, crisis-type prior) the headline AUC must beat."""
    try:
        from core.calibration.evaluation import baseline_results
        from core.calibration.crisis_dataset import ALL_EVENTS
        return {"status": "available", "baselines": baseline_results(ALL_EVENTS)}
    except Exception as exc:
        log.exception("calibration/baselines failed")
        return {"status": "error", "message": str(exc)}


@router.get("/dataset")
async def calibration_dataset() -> dict:
    """
    List of crisis events used in calibration (country, year, type, label).
    Useful for researchers who want to verify the dataset or extend it.
    """
    from core.calibration.crisis_dataset import ALL_EVENTS, get_positive_rate
    return {
        "n_total": len(ALL_EVENTS),
        "n_crises": sum(e.label for e in ALL_EVENTS),
        "positive_rate": round(get_positive_rate(), 3),
        "crisis_types": list({e.crisis_type for e in ALL_EVENTS}),
        "year_range": [min(e.year for e in ALL_EVENTS), max(e.year for e in ALL_EVENTS)],
        "events": [
            {
                "country": e.country,
                "year": e.year,
                "crisis_type": e.crisis_type,
                "label": e.label,
                "notes": e.notes,
            }
            for e in ALL_EVENTS
        ],
    }
