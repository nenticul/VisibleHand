"""
Risk scoring endpoints.

Route ordering matters: fixed routes (/compare, /movers, /bulk) must come
before /{country_code} so FastAPI does not consume them as country codes.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from api.cache import score_cache
from api.dependencies import get_db, optional_api_key
from api.models.database import (
    CountryScore, Indicator, PoliticalEvent, CentralBankStatement,
    GovernanceIndicator,
)
from api.models.schemas import (
    RiskResponse, ScoreBreakdown, HistoryPoint, MoverPoint,
    DriverAttribution, ForecastPoint,
)
from core.scoring.composite import compute_composite, DEFAULT_WEIGHTS
from core.scoring.labels import risk_level

log = logging.getLogger(__name__)

COUNTRY_NAMES: dict[str, str] = {
    "US": "United States", "GB": "United Kingdom", "DE": "Germany",
    "FR": "France", "JP": "Japan", "CN": "China", "BR": "Brazil",
    "IN": "India", "RU": "Russia", "ZA": "South Africa", "MX": "Mexico",
    "AR": "Argentina", "NG": "Nigeria", "KE": "Kenya", "TR": "Turkey",
    "EG": "Egypt", "ID": "Indonesia", "KR": "South Korea", "AU": "Australia",
    "CA": "Canada", "IT": "Italy", "ES": "Spain", "PL": "Poland",
    "UA": "Ukraine", "VN": "Vietnam", "TH": "Thailand", "PK": "Pakistan",
    "BD": "Bangladesh", "CO": "Colombia", "PH": "Philippines",
    "VE": "Venezuela", "CL": "Chile", "PE": "Peru", "GH": "Ghana",
    "ET": "Ethiopia", "TZ": "Tanzania", "UG": "Uganda",
    "SA": "Saudi Arabia", "GR": "Greece", "NL": "Netherlands",
    "HU": "Hungary", "CH": "Switzerland", "MA": "Morocco",
    "MY": "Malaysia", "LK": "Sri Lanka", "LB": "Lebanon",
}

router = APIRouter(prefix="/risk", tags=["risk"])


def _cache_key(code: str, ew: float, pw: float, nw: float, gw: float) -> str:
    return f"{code}:{ew:.2f}:{pw:.2f}:{nw:.2f}:{gw:.2f}"


def _build_response(
    country_code: str,
    db: Session,
    economic_weight: float,
    political_weight: float,
    nlp_weight: float,
    governance_weight: float,
) -> RiskResponse:
    code = country_code.upper()
    name = COUNTRY_NAMES.get(code, code)
    cache_key = _cache_key(code, economic_weight, political_weight, nlp_weight, governance_weight)

    cached = score_cache.get(cache_key)
    if cached is not None:
        log.debug("cache hit for %s", code)
        return cached

    # Load indicators (chronological order)
    rows = db.query(Indicator).filter(Indicator.country_code == code).all()
    rows = sorted(rows, key=lambda r: (r.year or 0, r.date or ""))
    indicators: dict[str, list[float]] = {}
    for row in rows:
        indicators.setdefault(row.metric, []).append(row.value)

    # Load political events
    events = db.query(PoliticalEvent).filter(PoliticalEvent.country_code == code).all()
    event_dicts = [
        {"event_type": e.event_type, "event_date": e.event_date,
         "severity": e.severity, "description": e.description}
        for e in events
    ]

    # Latest NLP statement score
    stmt = (
        db.query(CentralBankStatement)
        .filter(CentralBankStatement.country_code == code)
        .order_by(CentralBankStatement.fetched_at.desc())
        .first()
    )
    nlp_raw: Optional[float] = stmt.sentiment_score if stmt else None

    # Governance indicators
    gov_rows = db.query(GovernanceIndicator).filter(GovernanceIndicator.country_code == code).all()
    gov_rows = sorted(gov_rows, key=lambda r: r.year or 0)
    governance_indicators: dict[str, list[float]] = {}
    for row in gov_rows:
        governance_indicators.setdefault(row.metric, []).append(row.value)

    # Recent score history for forecast
    history_rows = (
        db.query(CountryScore)
        .filter(CountryScore.country_code == code)
        .order_by(CountryScore.computed_at.asc())
        .limit(24)
        .all()
    )
    score_history = [r.composite for r in history_rows] if len(history_rows) >= 3 else None

    result = compute_composite(
        indicators=indicators,
        events=event_dicts,
        nlp_score=nlp_raw,
        governance_indicators=governance_indicators or None,
        nlp_confidence=0.7 if stmt else 0.5,
        score_history=score_history,
        country=code,
        economic_weight=economic_weight,
        political_weight=political_weight,
        nlp_weight=nlp_weight,
        governance_weight=governance_weight,
    )

    now = datetime.now(timezone.utc).isoformat()

    # Build typed sub-objects
    breakdown = ScoreBreakdown(
        economic=result.get("economic"),
        political=result.get("political"),
        nlp_sentiment=result.get("nlp_sentiment"),
        governance=result.get("governance"),
    )

    attributions = [
        DriverAttribution(**a) for a in result.get("driver_attributions", [])
    ]

    forecast: Optional[dict] = None
    f6 = result.get("forecast_6m")
    f12 = result.get("forecast_12m")
    if f6 or f12:
        forecast = {}
        if f6:
            forecast["6m"] = ForecastPoint(**f6)
        if f12:
            forecast["12m"] = ForecastPoint(**f12)

    response = RiskResponse(
        country=code,
        name=name,
        composite=result["composite"],
        ci_low=result.get("ci_low"),
        ci_high=result.get("ci_high"),
        confidence=result.get("confidence", 0.0),
        risk_level=risk_level(result["composite"]),
        breakdown=breakdown,
        top_drivers=result.get("top_drivers", []),
        driver_attributions=attributions,
        methodology=result.get("methodology"),
        components=result.get("components"),
        forecast=forecast,
        regime_flags=result.get("regime_flags"),
        updated_at=now,
    )

    # Persist score snapshot
    db.add(CountryScore(
        country_code=code,
        composite=result["composite"],
        ci_low=result.get("ci_low"),
        ci_high=result.get("ci_high"),
        economic=result.get("economic"),
        political=result.get("political"),
        nlp_sentiment=result.get("nlp_sentiment"),
        governance=result.get("governance"),
        confidence=result.get("confidence"),
        top_drivers=json.dumps(result.get("top_drivers", [])),
        driver_attributions=json.dumps(result.get("driver_attributions", [])),
        methodology=result.get("methodology"),
        forecast_6m=json.dumps(f6) if f6 else None,
        forecast_12m=json.dumps(f12) if f12 else None,
        computed_at=datetime.now(timezone.utc),
    ))
    db.commit()

    score_cache.set(cache_key, response)
    log.info("scored %s composite=%.1f ci=[%.1f,%.1f]",
             code, result["composite"],
             result.get("ci_low", 0), result.get("ci_high", 0))
    return response


# ── Fixed routes before /{country_code} ─────────────────────────────────────

@router.get("/compare", response_model=list[RiskResponse])
async def compare_countries(
    countries: str = Query(..., description="Comma-separated ISO codes, e.g. US,DE,BR"),
    economic_weight: float = Query(DEFAULT_WEIGHTS["economic"], ge=0, le=1),
    political_weight: float = Query(DEFAULT_WEIGHTS["political"], ge=0, le=1),
    nlp_weight: float = Query(DEFAULT_WEIGHTS["nlp"], ge=0, le=1),
    governance_weight: float = Query(DEFAULT_WEIGHTS["governance"], ge=0, le=1),
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> list[RiskResponse]:
    """Compare risk scores for multiple countries simultaneously."""
    codes = [c.strip().upper() for c in countries.split(",") if c.strip()]
    if not codes:
        raise HTTPException(status_code=422, detail="Provide at least one country code")
    return [
        _build_response(code, db, economic_weight, political_weight, nlp_weight, governance_weight)
        for code in codes[:20]  # cap at 20
    ]


@router.get("/movers", response_model=list[MoverPoint])
async def get_movers(
    days: int = Query(7, ge=1, le=90, description="Look-back window in days"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> list[MoverPoint]:
    """Countries with the largest composite score changes in the past N days."""
    from sqlalchemy import text
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Latest score per country
    latest_rows = {}
    rows = (db.query(CountryScore)
            .order_by(CountryScore.computed_at.desc())
            .limit(2000).all())
    for r in rows:
        if r.country_code not in latest_rows:
            latest_rows[r.country_code] = r

    # Earliest score in the window per country
    earliest_rows = {}
    old_rows = (db.query(CountryScore)
                .filter(CountryScore.computed_at >= cutoff)
                .order_by(CountryScore.computed_at.asc())
                .limit(2000).all())
    for r in old_rows:
        if r.country_code not in earliest_rows:
            earliest_rows[r.country_code] = r

    movers: list[MoverPoint] = []
    for code, latest in latest_rows.items():
        earliest = earliest_rows.get(code)
        if earliest is None:
            continue
        delta = round(latest.composite - earliest.composite, 1)
        if abs(delta) < 0.1:
            continue
        movers.append(MoverPoint(
            country=code,
            name=COUNTRY_NAMES.get(code, code),
            composite=latest.composite,
            delta=delta,
            direction="up" if delta > 0 else "down",
            risk_level=risk_level(latest.composite),
        ))

    movers.sort(key=lambda m: -abs(m.delta))
    return movers[:limit]


@router.get("/bulk", response_model=list[RiskResponse])
async def get_bulk(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> list[RiskResponse]:
    """All latest country scores, paginated."""
    # Get the latest score per country
    latest_per_country: dict[str, CountryScore] = {}
    rows = (db.query(CountryScore)
            .order_by(CountryScore.computed_at.desc())
            .limit(5000).all())
    for r in rows:
        if r.country_code not in latest_per_country:
            latest_per_country[r.country_code] = r

    codes = sorted(latest_per_country.keys())
    start = (page - 1) * page_size
    page_codes = codes[start:start + page_size]

    results = []
    for code in page_codes:
        try:
            results.append(_build_response(
                code, db,
                DEFAULT_WEIGHTS["economic"],
                DEFAULT_WEIGHTS["political"],
                DEFAULT_WEIGHTS["nlp"],
                DEFAULT_WEIGHTS["governance"],
            ))
        except Exception as e:
            log.warning("bulk: skipping %s: %s", code, e)
    return results


# ── Parameterised routes ─────────────────────────────────────────────────────

@router.get("/{country_code}", response_model=RiskResponse)
async def get_risk(
    country_code: str,
    economic_weight: float = Query(DEFAULT_WEIGHTS["economic"], ge=0, le=1),
    political_weight: float = Query(DEFAULT_WEIGHTS["political"], ge=0, le=1),
    nlp_weight: float = Query(DEFAULT_WEIGHTS["nlp"], ge=0, le=1),
    governance_weight: float = Query(DEFAULT_WEIGHTS["governance"], ge=0, le=1),
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> RiskResponse:
    """Return composite political-economic risk score for a country."""
    if len(country_code) != 2 or not country_code.isalpha():
        raise HTTPException(status_code=422, detail="Provide a 2-letter ISO country code, e.g. BR")
    return _build_response(country_code, db, economic_weight, political_weight, nlp_weight, governance_weight)


@router.get("/{country_code}/history", response_model=list[HistoryPoint])
async def get_history(
    country_code: str,
    limit: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> list[HistoryPoint]:
    """Historical composite scores for a country (oldest → newest)."""
    rows = (
        db.query(CountryScore)
        .filter(CountryScore.country_code == country_code.upper())
        .order_by(CountryScore.computed_at.desc())
        .limit(limit)
        .all()
    )
    return [
        HistoryPoint(
            date=r.computed_at.date().isoformat(),
            composite=r.composite,
            ci_low=r.ci_low,
            ci_high=r.ci_high,
            economic=r.economic,
            political=r.political,
            nlp_sentiment=r.nlp_sentiment,
            governance=r.governance,
            confidence=r.confidence,
        )
        for r in reversed(rows)
    ]


@router.get("/{country_code}/forecast")
async def get_forecast(
    country_code: str,
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> dict:
    """6 and 12-month score extrapolation for a country."""
    code = country_code.upper()
    response = _build_response(
        code, db,
        DEFAULT_WEIGHTS["economic"],
        DEFAULT_WEIGHTS["political"],
        DEFAULT_WEIGHTS["nlp"],
        DEFAULT_WEIGHTS["governance"],
    )
    return {
        "country": code,
        "composite_current": response.composite,
        "forecast": response.forecast,
        "note": "Extrapolation via Theil-Sen slope on historical scores. Not a prediction.",
    }


@router.get("/{country_code}/drivers")
async def get_drivers(
    country_code: str,
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> dict:
    """Signed per-indicator driver attributions for a country (linear decomposition)."""
    code = country_code.upper()
    response = _build_response(
        code, db,
        DEFAULT_WEIGHTS["economic"],
        DEFAULT_WEIGHTS["political"],
        DEFAULT_WEIGHTS["nlp"],
        DEFAULT_WEIGHTS["governance"],
    )
    return {
        "country": code,
        "composite": response.composite,
        "driver_attributions": [a.model_dump() for a in response.driver_attributions],
        "top_drivers": response.top_drivers,
        "methodology": "Linear decomposition: contribution = (weight_i/Σw) × score_i per indicator.",
    }
