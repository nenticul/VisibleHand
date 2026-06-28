"""
ILO ILOSTAT ingestion — unemployment rate (annual, %).

Uses the ILOSTAT REST API v2 (no key required, CC BY 4.0).
Indicator: UNE_DEAP_SEX_AGE_RT — unemployment rate by sex and age.
We pull the aggregate (sex=SEX_T, classif1=AGE_AGGREGATE_TOTAL).
"""

from __future__ import annotations

import logging

from core.ingestion.http import get_json
from api.models.database import SessionLocal, Indicator

log = logging.getLogger(__name__)

# ILOSTAT REST API v2 base
_BASE = "https://rplumber.ilo.org/data/indicator/"

# ILO country codes match ISO-2 for most countries; exceptions listed here
_ILO_CODE_MAP: dict[str, str] = {
    "GB": "GBR",  # ILO uses ISO-3 for some endpoints — but v2 accepts ISO-2
}

COUNTRIES = [
    "US", "GB", "DE", "FR", "JP", "CN", "BR", "IN", "ZA", "MX",
    "AR", "NG", "TR", "EG", "ID", "KR", "AU", "CA", "UA", "PL",
]


async def fetch_ilo_unemployment(country_code: str, years: int = 10) -> list[dict]:
    """
    Fetch annual unemployment rate (%) for a country.
    Returns list of {metric, year, value}.
    """
    url = (
        f"{_BASE}?id=UNE_DEAP_SEX_AGE_RT"
        f"&ref_area={country_code}"
        f"&sex=SEX_T&classif1=AGE_AGGREGATE_TOTAL"
        f"&timefrom={2024 - years}&type=label&lang=en&format=json"
    )
    try:
        data = await get_json(url)
        if not data or "data" not in data:
            return []
        observations = data["data"].get("Observation", {})
        results: list[dict] = []
        for key, val in observations.items():
            # key format: "2023:1:1:1:1"
            year_str = key.split(":")[0]
            try:
                year = int(year_str)
                value = float(val[0]) if isinstance(val, list) else float(val)
                results.append({"metric": "unemployment", "year": year, "value": value})
            except (ValueError, IndexError, TypeError):
                continue
        return sorted(results, key=lambda r: r["year"])
    except Exception as exc:
        log.debug("ILO fetch failed for %s: %s", country_code, exc)
        return []


async def ingest_ilo() -> None:
    """Ingest ILO unemployment data for all tracked countries."""
    db = SessionLocal()
    inserted = 0
    try:
        for code in COUNTRIES:
            rows = await fetch_ilo_unemployment(code)
            for row in rows:
                exists = (
                    db.query(Indicator)
                    .filter(
                        Indicator.country_code == code,
                        Indicator.metric == "unemployment",
                        Indicator.year == row["year"],
                        Indicator.source == "ilostat",
                    )
                    .first()
                )
                if not exists:
                    db.add(Indicator(
                        country_code=code,
                        metric="unemployment",
                        year=row["year"],
                        value=row["value"],
                        source="ilostat",
                    ))
                    inserted += 1
        db.commit()
        log.info("ILO ingestion complete: %d rows inserted", inserted)
    finally:
        db.close()
