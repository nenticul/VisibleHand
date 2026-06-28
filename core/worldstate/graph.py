"""
Deterministic cross-country spillover / temporal-graph features.

v0.1 ships transparent graph aggregates (region, neighbour, trade-weighted)
computed from the same-date country scores. A learned temporal GNN is a later,
benchmark-gated experiment (build guide §9.4) and is intentionally not shipped
here.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from core.worldstate import registry as R
from core.worldstate.schemas import CountryStateFeatureRow


def _mean(xs: list[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def _max(xs: list[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(max(xs), 4) if xs else None


def spillover_features(score_map: dict[str, float], code: str) -> dict:
    """Full spillover feature dict for one country given a {code: score} map."""
    code = code.upper()
    region = R.REGION.get(code)
    regional = [s for c, s in score_map.items()
                if c != code and R.REGION.get(c) == region]
    neighbours = [score_map[n] for n in R.NEIGHBOURS.get(code, []) if n in score_map]

    partners = R.TRADE_PARTNERS.get(code, {})
    tw_num = sum(w * score_map[p] for p, w in partners.items() if p in score_map)
    tw_den = sum(w for p, w in partners.items() if p in score_map)
    trade_weighted = round(tw_num / tw_den, 4) if tw_den > 0 else None

    high = [p for p in partners if p in score_map and score_map[p] >= 60.0]
    share_high = round(len(high) / len(partners), 4) if partners else None

    sanctions_pressure = 0.0
    for p, w in partners.items():
        if p in R.SANCTIONED:
            sanctions_pressure += w * R.SANCTIONED[p]
    sanctions_pressure = round(min(1.0, sanctions_pressure + R.SANCTIONED.get(code, 0.0)), 4)

    conflict_flag = any(n in R.CONFLICT_COUNTRIES for n in R.NEIGHBOURS.get(code, []))

    return {
        "regional_mean_score": _mean(regional),
        "regional_max_score": _max(regional),
        "neighbour_mean_score": _mean(neighbours),
        "neighbour_max_score": _max(neighbours),
        "trade_weighted_partner_score": trade_weighted,
        "share_of_partners_high_risk": share_high,
        "sanctions_network_pressure": sanctions_pressure,
        "conflict_neighbour_flag": conflict_flag,
    }


def add_spillover(rows: list[CountryStateFeatureRow]) -> None:
    """Fill the spillover columns on a batch of same-date feature rows in place."""
    score_map = {r.country_code: r.visiblehand_score for r in rows}
    for r in rows:
        sp = spillover_features(score_map, r.country_code)
        r.regional_mean_score = sp["regional_mean_score"]
        r.regional_max_score = sp["regional_max_score"]
        r.neighbour_mean_score = sp["neighbour_mean_score"]
        r.trade_weighted_partner_score = sp["trade_weighted_partner_score"]


def spillover_from_db(db: Session, code: str, as_of_date: str) -> dict:
    """Compute spillover for a country from the persisted feature store.

    Uses the latest available feature row per country on or before ``as_of_date``
    so the map is internally consistent."""
    from api.models.database import CountryStateFeature

    rows = (
        db.query(CountryStateFeature)
        .filter(CountryStateFeature.as_of_date <= as_of_date)
        .order_by(CountryStateFeature.as_of_date.desc())
        .all()
    )
    score_map: dict[str, float] = {}
    for r in rows:  # rows are newest-first; keep first seen per country
        score_map.setdefault(r.country_code, float(r.visiblehand_score))
    return spillover_features(score_map, code)
