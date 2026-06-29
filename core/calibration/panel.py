"""
C7 — point-in-time crisis panel materialisation.

Turns the evaluation harness from "illustrative heuristic" into a real
backtest *for the subset of crisis events the database can actually cover*.

For each (country, year) in the crisis dataset we reconstruct what VisibleHand
would have scored at the **start of the crisis year**, using only indicator,
governance, and event data timestamped strictly *before* that date — no
look-ahead. The crisis label then sits 12 months in the future, exactly as an
early-warning system would face it.

Coverage is honest and explicit: many crisis countries (Zimbabwe, Lebanon,
Ethiopia, …) are outside the 44-country panel or lack deep history, so they fall
back to the heuristic in `run_evaluation`. But the panel countries do overlap a
meaningful slice — US 2008, Türkiye 2001/2018/2021, Argentina 2018, Brazil 2015,
Nigeria, Egypt, South Africa, Greece, Ukraine, plus most negative controls — so
this yields genuine live scores where the data exists, and says so.
"""

from __future__ import annotations

from core.scoring.composite import compute_composite, DEFAULT_WEIGHTS
from core.calibration.crisis_dataset import ALL_EVENTS


def _before(row, year: int, cutoff_iso: str) -> bool:
    """Was this indicator row known strictly before the crisis year began?"""
    if getattr(row, "year", None) is not None:
        return row.year < year
    d = getattr(row, "date", None)
    if d:
        return d < cutoff_iso
    return False


def _gov_pop_asof(db, year: int, cache: dict):
    """Point-in-time cross-sectional governance population (latest value per
    country/metric known before `year`). Cached per year to avoid re-scanning."""
    if year in cache:
        return cache[year]
    from api.models.database import GovernanceIndicator
    rows = db.query(GovernanceIndicator).all()
    latest: dict[tuple, tuple] = {}
    for r in rows:
        yr = getattr(r, "year", None) or 0
        if yr >= year:
            continue
        key = (r.country_code, r.metric)
        if key not in latest or yr > latest[key][0]:
            latest[key] = (yr, r.value)
    pop: dict[str, list[float]] = {}
    for (_cc, metric), (_yr, val) in latest.items():
        pop.setdefault(metric, []).append(val)
    cache[year] = pop or None
    return cache[year]


def materialize_crisis_panel(db, weights: dict | None = None) -> dict:
    """
    Returns {"scores": {(country, year): composite}, "coverage": {...}}.

    `scores` is exactly the mapping `run_evaluation(db_scores=...)` consumes.
    """
    from api.models.database import Indicator, PoliticalEvent, GovernanceIndicator

    w = weights or DEFAULT_WEIGHTS
    scores: dict[tuple[str, int], float] = {}
    gov_pop_cache: dict[int, object] = {}
    live_events: list[dict] = []
    n_insufficient = 0

    for ev in ALL_EVENTS:
        code = ev.country
        cutoff_iso = f"{ev.year}-01-01"

        ind_rows = db.query(Indicator).filter(Indicator.country_code == code).all()
        indicators: dict[str, list[float]] = {}
        for r in sorted(ind_rows or [], key=lambda r: (getattr(r, "year", 0) or 0, getattr(r, "date", "") or "")):
            if _before(r, ev.year, cutoff_iso):
                indicators.setdefault(r.metric, []).append(r.value)

        ev_rows = db.query(PoliticalEvent).filter(PoliticalEvent.country_code == code).all()
        event_dicts = [
            {"event_type": e.event_type, "event_date": e.event_date,
             "severity": e.severity, "description": e.description}
            for e in (ev_rows or [])
            if (getattr(e, "event_date", None) or "") < cutoff_iso
        ]

        gov_rows = db.query(GovernanceIndicator).filter(GovernanceIndicator.country_code == code).all()
        governance: dict[str, list[float]] = {}
        for r in sorted(gov_rows or [], key=lambda r: getattr(r, "year", 0) or 0):
            if (getattr(r, "year", 0) or 0) < ev.year:
                governance.setdefault(r.metric, []).append(r.value)

        if not indicators and not governance and not event_dicts:
            n_insufficient += 1
            continue

        gov_pop = _gov_pop_asof(db, ev.year, gov_pop_cache) if governance else None
        result = compute_composite(
            indicators=indicators,
            events=event_dicts,
            nlp_score=None,
            governance_indicators=governance or None,
            governance_population=gov_pop,
            country=code,
            mode="temporal",
            economic_weight=w["economic"],
            political_weight=w["political"],
            nlp_weight=w["nlp"],
            governance_weight=w["governance"],
        )
        comp = result.get("composite")
        if comp is None:
            n_insufficient += 1
            continue
        scores[(code, ev.year)] = round(float(comp), 1)
        live_events.append({"country": code, "year": ev.year,
                            "crisis_type": ev.crisis_type, "label": ev.label,
                            "score": round(float(comp), 1),
                            "economic": result.get("economic"),
                            "political": result.get("political"),
                            "nlp": result.get("nlp_sentiment"),
                            "governance": result.get("governance")})

    n_events = len(ALL_EVENTS)
    coverage = {
        "n_events": n_events,
        "live": len(scores),
        "insufficient": n_insufficient,
        "coverage_rate": round(len(scores) / max(n_events, 1), 3),
        "live_events": sorted(live_events, key=lambda x: -x["score"]),
    }
    return {"scores": scores, "coverage": coverage}
