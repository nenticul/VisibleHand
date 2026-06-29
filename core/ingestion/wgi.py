"""
World Bank Worldwide Governance Indicators (WGI) ingestion.

Free, no API key. Source 3 in the World Bank API. Six governance dimensions,
each an estimate on roughly -2.5 (worst) to +2.5 (best):
  Voice & Accountability, Political Stability, Government Effectiveness,
  Regulatory Quality, Rule of Law, Control of Corruption.

Stored as GovernanceIndicator rows (source="wgi") and consumed by
core/scoring/governance.py, which percentile-ranks them cross-sectionally.
This is the first *live* governance data source — the others were seeded.
"""

from __future__ import annotations

import logging

from core.ingestion.http import get_json
from api.models.database import SessionLocal, GovernanceIndicator

log = logging.getLogger(__name__)

WB_BASE = "https://api.worldbank.org/v2"

# WGI estimate series (source 3) -> stored metric name. Higher = better.
WGI_INDICATORS: dict[str, str] = {
    "GOV_WGI_VA.EST": "wgi_voice_accountability",
    "GOV_WGI_PV.EST": "wgi_political_stability",
    "GOV_WGI_GE.EST": "wgi_govt_effectiveness",
    "GOV_WGI_RQ.EST": "wgi_regulatory_quality",
    "GOV_WGI_RL.EST": "wgi_rule_of_law",
    "GOV_WGI_CC.EST": "wgi_control_of_corruption",
}

# ISO3 (World Bank) -> ISO2 (VisibleHand) for the 44-country universe.
_ISO3_TO_ISO2: dict[str, str] = {
    "ARG": "AR", "AUS": "AU", "BGD": "BD", "BRA": "BR", "CAN": "CA",
    "CHE": "CH", "CHL": "CL", "CHN": "CN", "COL": "CO", "DEU": "DE",
    "EGY": "EG", "ESP": "ES", "ETH": "ET", "FRA": "FR", "GBR": "GB",
    "GHA": "GH", "GRC": "GR", "HUN": "HU", "IDN": "ID", "IND": "IN",
    "ITA": "IT", "JPN": "JP", "KEN": "KE", "KOR": "KR", "LBN": "LB",
    "LKA": "LK", "MAR": "MA", "MEX": "MX", "MYS": "MY", "NGA": "NG",
    "NLD": "NL", "PER": "PE", "PHL": "PH", "PAK": "PK", "POL": "PL",
    "RUS": "RU", "SAU": "SA", "THA": "TH", "TUR": "TR", "UKR": "UA",
    "USA": "US", "VEN": "VE", "VNM": "VN", "ZAF": "ZA",
}

_ISO3_LIST = ";".join(_ISO3_TO_ISO2.keys())


async def fetch_wgi(series_id: str, years: int = 5) -> list[dict]:
    """Return [{iso2, year, value}] for one WGI series across all 44 countries."""
    url = (
        f"{WB_BASE}/country/{_ISO3_LIST}/indicator/{series_id}"
        f"?source=3&format=json&mrv={years}&per_page=600"
    )
    payload = await get_json(url)
    if not payload or len(payload) < 2 or not payload[1]:
        return []
    rows: list[dict] = []
    for item in payload[1]:
        if item.get("value") is None:
            continue
        iso2 = _ISO3_TO_ISO2.get(item.get("countryiso3code", ""))
        if not iso2:
            continue
        try:
            rows.append({
                "iso2": iso2,
                "year": int(item["date"]),
                "value": float(item["value"]),
            })
        except (ValueError, TypeError):
            continue
    return rows


async def ingest_wgi() -> None:
    db = SessionLocal()
    inserted = 0
    try:
        for series_id, metric in WGI_INDICATORS.items():
            for row in await fetch_wgi(series_id):
                exists = (
                    db.query(GovernanceIndicator)
                    .filter(
                        GovernanceIndicator.country_code == row["iso2"],
                        GovernanceIndicator.metric == metric,
                        GovernanceIndicator.year == row["year"],
                        GovernanceIndicator.source == "wgi",
                    )
                    .first()
                )
                if not exists:
                    db.add(GovernanceIndicator(
                        country_code=row["iso2"],
                        metric=metric,
                        year=row["year"],
                        value=row["value"],
                        source="wgi",
                    ))
                    inserted += 1
        db.commit()
        log.info("WGI ingestion complete: %d rows inserted", inserted)
    finally:
        db.close()
