"""Calibration and methodology transparency endpoints."""

from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import APIRouter, Query
from api.models.schemas import CalibrationSummary
from core.scoring.composite import DEFAULT_WEIGHTS

log = logging.getLogger(__name__)
router = APIRouter(prefix="/calibration", tags=["calibration"])


@lru_cache(maxsize=1)
def _cached_backtest():
    """Run backtest once and cache result (expensive — scores ~220 events)."""
    from core.calibration.backtest import run_backtest
    return run_backtest()


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
