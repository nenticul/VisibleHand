"""Governance sub-score endpoint."""

import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db, optional_api_key
from api.models.database import GovernanceIndicator, CountryScore
from api.models.schemas import GovernanceResponse
from core.scoring.governance import governance_score

log = logging.getLogger(__name__)
router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/{country_code}", response_model=GovernanceResponse)
async def get_governance(
    country_code: str,
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> GovernanceResponse:
    """
    Governance quality sub-score for a country (0–100, higher = more risk).
    Sources: V-Dem, WJP Rule of Law, TI CPI, Freedom House.
    """
    code = country_code.upper()
    if len(code) != 2 or not code.isalpha():
        raise HTTPException(status_code=422, detail="Provide a 2-letter ISO country code")

    rows = db.query(GovernanceIndicator).filter(GovernanceIndicator.country_code == code).all()
    rows = sorted(rows, key=lambda r: r.year or 0)

    gov_indicators: dict[str, list[float]] = {}
    for row in rows:
        gov_indicators.setdefault(row.metric, []).append(row.value)

    if not gov_indicators:
        return GovernanceResponse(
            country=code,
            score=50.0,
            confidence=0.0,
            components={},
            drivers=["no_governance_data_available"],
        )

    result = governance_score(gov_indicators)

    # Latest computation timestamp
    latest_score = (
        db.query(CountryScore)
        .filter(CountryScore.country_code == code)
        .order_by(CountryScore.computed_at.desc())
        .first()
    )
    updated = latest_score.computed_at.isoformat() if latest_score else None

    return GovernanceResponse(
        country=code,
        score=result.score,
        confidence=result.confidence,
        components=result.components,
        drivers=result.drivers,
        press_freedom_modifier=result.press_freedom_confidence_modifier,
        updated_at=updated,
    )
