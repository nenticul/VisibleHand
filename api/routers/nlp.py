"""NLP aspect-scores and statement endpoints."""

import json
import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db, optional_api_key
from api.models.database import CentralBankStatement
from api.models.schemas import AspectScoresResponse
from core.nlp.aspect_scorer import aspect_sentiment_score, aggregate_aspect_scores

log = logging.getLogger(__name__)
router = APIRouter(tags=["nlp"])


@router.get("/risk/{country_code}/aspects", response_model=AspectScoresResponse)
async def get_aspects(
    country_code: str,
    limit: int = 5,
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> AspectScoresResponse:
    """
    Per-aspect NLP sentiment scores (monetary policy, fiscal, financial stability,
    external sector, political economy) from recent central-bank documents.
    """
    code = country_code.upper()
    if len(code) != 2 or not code.isalpha():
        raise HTTPException(status_code=422, detail="Provide a 2-letter ISO country code")

    stmts = (
        db.query(CentralBankStatement)
        .filter(CentralBankStatement.country_code == code)
        .order_by(CentralBankStatement.fetched_at.desc())
        .limit(limit)
        .all()
    )

    if not stmts:
        return AspectScoresResponse(country=code, document_count=0)

    # Try cached aspect_scores first; otherwise compute on-the-fly
    scored = []
    for s in stmts:
        if s.aspect_scores:
            try:
                d = json.loads(s.aspect_scores)
                from core.nlp.aspect_scorer import AspectScores
                scored.append(AspectScores(**d))
                continue
            except Exception:
                pass
        # Compute and cache
        if s.raw_text:
            asp = aspect_sentiment_score(s.raw_text)
            try:
                s.aspect_scores = json.dumps(asp.to_dict())
                db.commit()
            except Exception:
                pass
            scored.append(asp)

    if not scored:
        return AspectScoresResponse(country=code, document_count=0)

    agg = aggregate_aspect_scores(scored)
    latest_date = stmts[0].statement_date if stmts else None

    return AspectScoresResponse(
        country=code,
        monetary_policy=agg.monetary_policy,
        fiscal_policy=agg.fiscal_policy,
        financial_stability=agg.financial_stability,
        external_sector=agg.external_sector,
        political_economy=agg.political_economy,
        overall=agg.overall,
        document_count=len(scored),
        updated_at=latest_date,
    )


@router.get("/statements/{country_code}")
async def get_statements(
    country_code: str,
    limit: int = 10,
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> list[dict]:
    """Recent NLP-processed central-bank documents for a country."""
    code = country_code.upper()
    stmts = (
        db.query(CentralBankStatement)
        .filter(CentralBankStatement.country_code == code)
        .order_by(CentralBankStatement.fetched_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "country": code,
            "bank": s.bank_name,
            "date": s.statement_date,
            "sentiment_score": s.sentiment_score,
            "sentiment_label": _label(s.sentiment_score),
            "snippet": (s.raw_text or "")[:300] + "…" if s.raw_text and len(s.raw_text) > 300 else s.raw_text,
        }
        for s in stmts
    ]


def _label(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    if score >= 70:
        return "hawkish"
    if score >= 50:
        return "slightly hawkish"
    if score >= 35:
        return "neutral"
    return "dovish"
