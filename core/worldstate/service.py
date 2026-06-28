"""
World-state service layer — orchestrates the per-country VH-WSM view by reading
the materialised feature store, embeddings, hazard predictions, analogues,
spillover, and conformal uncertainty.

Everything here is read-only against persisted data so the API stays fast and
the heavy lifting lives in the offline scripts.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from sqlalchemy.orm import Session

from core.worldstate import registry as R
from core.worldstate import graph, hazards
from core.worldstate.analogues import AnalogueSearchService
from core.worldstate.uncertainty import ConformalCalibrator, abstain_decision

_CONFORMAL_PATH = os.path.join(R.DATA_ROOT, "conformal", "v0.1", "calibrator.json")


def _country_name(code: str) -> str:
    try:
        from api.routers.risk import COUNTRY_NAMES
        return COUNTRY_NAMES.get(code, code)
    except Exception:
        return code


def latest_feature_row(db: Session, code: str,
                       model_version: str = R.FEATURE_VERSION):
    from api.models.database import CountryStateFeature
    return (
        db.query(CountryStateFeature)
        .filter(CountryStateFeature.country_code == code)
        .filter(CountryStateFeature.model_version == model_version)
        .order_by(CountryStateFeature.as_of_date.desc())
        .first()
    )


def _row_to_dict(row) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


# ── hazards ──────────────────────────────────────────────────────────────────
def get_hazards(db: Session, code: str, horizon: int = 12) -> dict:
    from api.models.database import CrisisHazardPrediction

    row = latest_feature_row(db, code)
    pred = None
    if row is not None:
        pred = (
            db.query(CrisisHazardPrediction)
            .filter(CrisisHazardPrediction.country_code == code)
            .filter(CrisisHazardPrediction.horizon_months == horizon)
            .order_by(CrisisHazardPrediction.as_of_date.desc())
            .first()
        )
    if pred is not None:
        hz = {t: getattr(pred, f"{t}_prob") for t in R.HAZARD_TARGETS}
        hz = {k: (round(v, 4) if v is not None else None) for k, v in hz.items()}
        return {
            "country": code, "date": pred.as_of_date, "horizon_months": horizon,
            "model": pred.model_name, "model_version": pred.model_version,
            "calibration_status": pred.calibration_status or "experimental",
            "hazards": hz,
        }
    # fallback: transparent heuristic from latest feature row
    if row is None:
        return {}
    hz = hazards.heuristic_hazards(_row_to_dict(row), code=code)
    return {
        "country": code, "date": row.as_of_date, "horizon_months": horizon,
        "model": "vh-wsm-hazard-heuristic", "model_version": R.HAZARD_MODEL_VERSION,
        "calibration_status": "heuristic", "hazards": hz,
    }


# ── analogues ────────────────────────────────────────────────────────────────
def get_analogues(db: Session, code: str, k: int = 10) -> dict:
    from api.models.database import CountryStateEmbedding

    latest = (
        db.query(CountryStateEmbedding)
        .filter(CountryStateEmbedding.country_code == code)
        .filter(CountryStateEmbedding.embedding_version == R.EMBEDDING_VERSION)
        .order_by(CountryStateEmbedding.as_of_date.desc())
        .first()
    )
    if latest is None:
        return {"country": code, "date": None,
                "embedding_version": R.EMBEDDING_VERSION, "analogues": []}
    svc = AnalogueSearchService(db)
    items = svc.find_analogues(code, latest.as_of_date, k=k)
    return {"country": code, "date": latest.as_of_date,
            "embedding_version": R.EMBEDDING_VERSION, "analogues": items}


# ── spillover ────────────────────────────────────────────────────────────────
def get_spillover(db: Session, code: str) -> dict:
    row = latest_feature_row(db, code)
    as_of = row.as_of_date if row else _today()
    return {"country": code, "date": as_of,
            "spillover": graph.spillover_from_db(db, code, as_of)}


# ── uncertainty ──────────────────────────────────────────────────────────────
def _load_calibrator() -> Optional[ConformalCalibrator]:
    if os.path.exists(_CONFORMAL_PATH):
        try:
            return ConformalCalibrator.load(_CONFORMAL_PATH)
        except Exception:
            return None
    return None


def get_uncertainty(db: Session, code: str, alpha: float = 0.1) -> dict:
    row = latest_feature_row(db, code)
    if row is None:
        return {}
    score = float(row.visiblehand_score)
    cal = _load_calibrator()
    if cal is not None:
        interval = cal.interval(score, alpha=alpha)
        cov = cal.coverage_report(alpha=alpha)
        empirical = cov.get("empirical_coverage")
    elif row.ci_low is not None and row.ci_high is not None:
        interval = (round(float(row.ci_low), 2), round(float(row.ci_high), 2))
        empirical = None
    else:
        interval = (round(max(0.0, score - 9.0), 2), round(min(100.0, score + 9.0), 2))
        empirical = None

    abstain, reasons = abstain_decision(_row_to_dict(row), interval)
    return {
        "country": code, "date": row.as_of_date, "score": round(score, 2),
        "conformal_90": list(interval), "coverage_target": round(1 - alpha, 2),
        "empirical_coverage": empirical, "abstain": abstain,
        "abstain_reasons": reasons,
    }


# ── embedding ────────────────────────────────────────────────────────────────
def get_embedding(db: Session, code: str) -> dict:
    from api.models.database import CountryStateEmbedding
    row = (
        db.query(CountryStateEmbedding)
        .filter(CountryStateEmbedding.country_code == code)
        .filter(CountryStateEmbedding.embedding_version == R.EMBEDDING_VERSION)
        .order_by(CountryStateEmbedding.as_of_date.desc())
        .first()
    )
    if row is None:
        return {}
    try:
        vec = json.loads(row.embedding)
    except Exception:
        vec = []
    return {
        "country": code, "date": row.as_of_date,
        "embedding_version": row.embedding_version, "embedding_dim": row.embedding_dim,
        "embedding": vec, "cluster": row.cluster_label,
        "cluster_confidence": row.cluster_confidence,
    }


# ── full state ───────────────────────────────────────────────────────────────
def build_state(db: Session, code: str) -> Optional[dict]:
    row = latest_feature_row(db, code)
    if row is None:
        return None
    as_of = row.as_of_date

    haz = get_hazards(db, code, horizon=12)
    analogues = get_analogues(db, code, k=5)
    spill = get_spillover(db, code)
    unc = get_uncertainty(db, code)
    emb = get_embedding(db, code)

    return {
        "country": code,
        "name": _country_name(code),
        "date": as_of,
        "base_score": {
            "score": round(float(row.visiblehand_score), 2),
            "risk_band": row.risk_band,
            "confidence": row.confidence,
            "ci_95": [row.ci_low, row.ci_high] if row.ci_low is not None else None,
            "components": {
                "economic": row.economic_score, "political": row.political_score,
                "nlp": row.nlp_score, "governance": row.governance_score,
            },
        },
        "world_state": {
            "cluster": emb.get("cluster"),
            "cluster_confidence": emb.get("cluster_confidence"),
            "embedding_version": R.EMBEDDING_VERSION,
        },
        "hazards_12m": haz.get("hazards", {}),
        "hazards_model": {
            "model": haz.get("model"), "calibration_status": haz.get("calibration_status"),
        },
        "nearest_analogues": analogues.get("analogues", []),
        "spillover": spill.get("spillover", {}),
        "uncertainty": {
            "conformal_90": unc.get("conformal_90"),
            "abstain": unc.get("abstain"),
            "abstain_reasons": unc.get("abstain_reasons", []),
        },
        "model_metadata": {
            "model_version": R.MODEL_VERSION,
            "feature_version": R.FEATURE_VERSION,
            "embedding_version": R.EMBEDDING_VERSION,
            "base_score_version": R.BASE_SCORE_VERSION,
            "data_cutoff": as_of,
            "data_quality_score": row.data_quality_score,
        },
    }


def _today() -> str:
    from datetime import date
    return date.today().isoformat()
