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
    DriverAttribution, ForecastPoint, BaselineResponse, PeerGroupInfo,
)
from core.scoring.composite import compute_composite, DEFAULT_WEIGHTS
from core.scoring.labels import risk_level
from core.scoring.baseline import (
    build_baseline_reference, resolve_peer_group, BaselineReference,
    INCOME_GROUP, REGION, ANCHOR_ECONOMIES,
)
from core.scoring.stats import robust_z  # noqa: F401  (kept for anchor stats)

log = logging.getLogger(__name__)


def _norm_mode(mode: Optional[str]) -> str:
    """Normalise the measurement-mode query param to a canonical value."""
    m = (mode or "temporal").strip().lower()
    if m in ("cross_sectional", "cross-sectional", "crosssectional",
             "baseline", "peer", "peers", "global", "absolute"):
        return "cross_sectional"
    return "temporal"

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


def _cache_key(code: str, ew: float, pw: float, nw: float, gw: float, mode: str = "temporal") -> str:
    return f"{code}:{ew:.2f}:{pw:.2f}:{nw:.2f}:{gw:.2f}:{mode}"


# ── Cross-sectional baseline reference (built once, cached) ───────────────────
_baseline_cache: dict[str, object] = {"ref": None, "ts": 0.0}
_BASELINE_TTL = 300.0  # seconds


def _get_baseline_reference(db: Session) -> BaselineReference:
    """
    Build (and cache) the cross-country reference distribution: the latest value
    of every macro indicator for every country in the database. Reused across a
    whole /compare call and refreshed every few minutes.
    """
    import time
    now = time.time()
    ref = _baseline_cache.get("ref")
    if ref is not None and (now - float(_baseline_cache.get("ts", 0.0))) < _BASELINE_TTL:
        return ref  # type: ignore[return-value]

    rows = db.query(Indicator).all()
    # Keep the most recent (year, date) value per (country, metric).
    best: dict[tuple, tuple] = {}
    for r in rows:
        key = (r.country_code, r.metric)
        ordkey = (r.year or 0, r.date or "")
        cur = best.get(key)
        if cur is None or ordkey > cur[0]:
            best[key] = (ordkey, r.value)

    latest_by_country: dict[str, dict[str, float]] = {}
    for (cc, metric), (_, val) in best.items():
        if val is None:
            continue
        latest_by_country.setdefault(cc, {})[metric] = val

    ref = build_baseline_reference(latest_by_country)
    _baseline_cache["ref"] = ref
    _baseline_cache["ts"] = now
    return ref


# ── Governance cross-sectional population (built once, cached) ────────────────
_gov_pop_cache: dict[str, object] = {"pop": None, "ts": 0.0}
_GOV_POP_TTL = 300.0  # seconds


def _get_governance_population(db: Session) -> dict[str, list[float]]:
    """
    {metric: [latest value per country]} across all countries, for cross-sectional
    percentile ranking in the governance scorer. Governance is inherently
    comparative (Sweden vs Somalia), so own-history z-scores wash out slow-moving
    indicators like WGI — this population is what gives them signal.
    """
    import time
    now = time.time()
    pop = _gov_pop_cache.get("pop")
    if pop is not None and (now - float(_gov_pop_cache.get("ts", 0.0))) < _GOV_POP_TTL:
        return pop  # type: ignore[return-value]

    rows = db.query(GovernanceIndicator).all()
    best: dict[tuple, tuple] = {}  # (country, metric) -> (year, value)
    for r in rows:
        key = (r.country_code, r.metric)
        ordkey = r.year or 0
        cur = best.get(key)
        if cur is None or ordkey > cur[0]:
            best[key] = (ordkey, r.value)

    population: dict[str, list[float]] = {}
    for (_cc, metric), (_y, val) in best.items():
        if val is not None:
            population.setdefault(metric, []).append(val)

    _gov_pop_cache["pop"] = population
    _gov_pop_cache["ts"] = now
    return population


def _build_response(
    country_code: str,
    db: Session,
    economic_weight: float,
    political_weight: float,
    nlp_weight: float,
    governance_weight: float,
    mode: str = "temporal",
) -> RiskResponse:
    code = country_code.upper()
    name = COUNTRY_NAMES.get(code, code)
    mode = _norm_mode(mode)
    cache_key = _cache_key(code, economic_weight, political_weight, nlp_weight, governance_weight, mode)

    cached = score_cache.get(cache_key)
    if cached is not None:
        log.debug("cache hit for %s (%s)", code, mode)
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

    baseline_ref = _get_baseline_reference(db) if mode == "cross_sectional" else None
    governance_population = _get_governance_population(db) if governance_indicators else None

    result = compute_composite(
        indicators=indicators,
        events=event_dicts,
        nlp_score=nlp_raw,
        governance_indicators=governance_indicators or None,
        governance_population=governance_population,
        nlp_confidence=0.7 if stmt else 0.5,
        score_history=score_history,
        country=code,
        economic_weight=economic_weight,
        political_weight=political_weight,
        nlp_weight=nlp_weight,
        governance_weight=governance_weight,
        mode=mode,
        baseline_ref=baseline_ref,
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
        mode=mode,
        peer_group=result.get("peer_group"),
        peer_percentiles=result.get("peer_percentiles"),
        updated_at=now,
    )

    # Only the temporal score is the canonical time series; persist that one so
    # history / movers stay clean. Cross-sectional is computed on demand + cached.
    if mode != "temporal":
        score_cache.set(cache_key, response)
        log.info("scored %s (cross_sectional) composite=%.1f peer=%s",
                 code, result["composite"], result.get("peer_group"))
        return response

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
    mode: str = Query("temporal", description="'temporal' (vs own history) or 'cross_sectional' (vs peer + anchor baseline)"),
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
        _build_response(code, db, economic_weight, political_weight, nlp_weight, governance_weight, mode)
        for code in codes[:20]  # cap at 20
    ]


@router.get("/baseline", response_model=BaselineResponse)
async def get_baseline(
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> BaselineResponse:
    """
    Introspect the cross-sectional reference distribution: the anchor basket,
    the income/region peer taxonomy, per-metric anchor statistics, and each
    country's resolved peer group. Lets anyone audit exactly what a
    cross-sectional score is measured against.
    """
    from statistics import median
    ref = _get_baseline_reference(db)

    anchor_stats: dict[str, dict[str, float]] = {}
    for metric, vals in ref.anchor.items():
        if not vals:
            continue
        med = median(vals)
        devs = [abs(v - med) for v in vals]
        mad = round(median(devs) * 1.4826, 4) if devs else 0.0
        anchor_stats[metric] = {"median": round(med, 4), "mad": mad, "n": float(len(vals))}

    metric_coverage = {m: len(pop) for m, pop in ref.populations.items()}

    peer_groups: list[PeerGroupInfo] = []
    for cc in ref.countries:
        label, peers = resolve_peer_group(cc, ref)
        peer_groups.append(PeerGroupInfo(
            country=cc,
            income_group=INCOME_GROUP.get(cc),
            region=REGION.get(cc),
            peer_group=label,
            peers=peers,
        ))

    return BaselineResponse(
        n_countries=len(ref.countries),
        anchor_economies=ANCHOR_ECONOMIES,
        income_groups={c: INCOME_GROUP[c] for c in ref.countries if c in INCOME_GROUP},
        regions={c: REGION[c] for c in ref.countries if c in REGION},
        anchor_stats=anchor_stats,
        metric_coverage=metric_coverage,
        peer_groups=peer_groups,
    )


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

_STORY = {
    "economic": "Macro-financial stress",
    "political": "Political instability",
    "nlp": "Central-bank / monetary stress",
    "governance": "Governance & rule-of-law weakness",
}


def _humanize(s: str) -> str:
    return s.replace("_", " ").strip()


def _nlp_band(s: float) -> str:
    if s < 35: return "dovish"
    if s < 65: return "neutral"
    if s < 85: return "hawkish"
    return "very hawkish / stressed"


def _top_detail(detail: dict | None, n: int = 3) -> list[tuple[str, float]]:
    if not detail:
        return []
    items = [(k, v) for k, v in detail.items() if isinstance(v, (int, float))]
    items.sort(key=lambda kv: -kv[1])
    return items[:n]


def _build_explanation(resp: RiskResponse) -> dict:
    """
    Assemble a structured 'why this score' tree from a finished response — no
    re-computation, so it works off the cached score too. The dominant story is
    the sub-scorer contributing the most risk; each component reports its single
    biggest driver, and the NLP section carries the monetary-regime tag.
    """
    from core.scoring.regime import classify_nlp_regime

    comps = resp.components or {}
    bd = resp.breakdown
    by = {"economic": bd.economic, "political": bd.political,
          "nlp": bd.nlp_sentiment, "governance": bd.governance}

    risk_attrs = [a for a in (resp.driver_attributions or []) if a.direction == "risk"]
    dominant = None
    if risk_attrs:
        dominant = max(risk_attrs, key=lambda a: a.contribution).sub_scorer
    if dominant not in _STORY:
        present = {k: v for k, v in by.items() if v is not None}
        dominant = max(present, key=present.get) if present else "economic"
    story = _STORY.get(dominant, "Composite risk")

    eco = comps.get("economic") or {}
    eco_detail = eco.get("detail") or {}
    pol = comps.get("political") or {}
    pol_detail = pol.get("detail") or {}
    nlp = comps.get("nlp") or {}
    gov = comps.get("governance") or {}
    gov_detail = gov.get("detail") or {}

    out: dict = {
        "dominant_story": story,
        "risk_level": resp.risk_level,
        "headline": (f"{resp.name} scores {resp.composite:.1f}/100 "
                     f"({resp.risk_level}); dominant factor: {story.lower()}."),
    }

    if by["economic"] is not None:
        top = _top_detail(eco_detail)
        out["economic"] = {
            "score": by["economic"],
            "confidence": eco.get("confidence"),
            "key_driver": _humanize(top[0][0]) if top else None,
            "top_indicators": [{"indicator": _humanize(k), "risk": round(v, 1)} for k, v in top],
        }
    if by["political"] is not None:
        esc = pol_detail.get("escalation")
        out["political"] = {
            "score": by["political"],
            "confidence": pol.get("confidence"),
            "escalating": bool(esc is not None and esc >= 60),
            "detail": {k: round(v, 1) for k, v in pol_detail.items() if isinstance(v, (int, float))},
        }
    if by["nlp"] is not None:
        out["nlp"] = {
            "score": by["nlp"],
            "confidence": nlp.get("confidence"),
            "stance": _nlp_band(by["nlp"]),
            "regime": classify_nlp_regime(by["nlp"], eco_detail),
        }
    if by["governance"] is not None:
        top = _top_detail(gov_detail)
        out["governance"] = {
            "score": by["governance"],
            "confidence": gov.get("confidence"),
            "key_driver": _humanize(top[0][0]) if top else None,
        }
    return out


@router.get("/{country_code}", response_model=RiskResponse)
async def get_risk(
    country_code: str,
    mode: str = Query("temporal", description="'temporal' (vs own history) or 'cross_sectional' (vs peer + anchor baseline)"),
    explain: bool = Query(False, description="Attach a structured why-this-score explanation tree"),
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
    resp = _build_response(country_code, db, economic_weight, political_weight, nlp_weight, governance_weight, mode)
    if explain:
        # model_copy so the cached instance is never mutated.
        resp = resp.model_copy(update={"explanation": _build_explanation(resp)})
    return resp


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
