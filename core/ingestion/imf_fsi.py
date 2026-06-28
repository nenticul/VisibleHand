"""
IMF Financial Soundness Indicators (FSI) ingestion — bank NPL ratio.

Uses the IMF Data API v2 (free, no key required for public datasets).
Key indicator: FSANL_PT — Non-performing loans as % of total gross loans.

IMF FSI documentation: https://www.imf.org/en/Data/data/FSI
API: https://datahelp.imf.org/knowledgebase/articles/667681-using-json-restful-web-service
"""

from __future__ import annotations

import logging

from core.ingestion.http import get_json
from api.models.database import SessionLocal, Indicator

log = logging.getLogger(__name__)

_IMF_BASE = "https://www.imf.org/external/datamapper/api/v1"

# IMF uses ISO-2 for country codes in the DataMapper API
COUNTRIES = [
    "US", "GB", "DE", "FR", "JP", "CN", "BR", "IN", "ZA", "MX",
    "AR", "NG", "TR", "KR", "AU", "CA", "UA", "PL", "ID",
]

_INDICATOR = "FSANL_PT"  # NPL ratio (%)


async def fetch_imf_npl(country_code: str) -> list[dict]:
    """
    Fetch bank NPL ratio (%) from IMF FSI for a country.
    Returns list of {metric, year, value}.
    """
    url = f"{_IMF_BASE}/{_INDICATOR}/{country_code}"
    try:
        data = await get_json(url)
        if not data or "values" not in data:
            return []

        country_data = data["values"].get(_INDICATOR, {}).get(country_code, {})
        results: list[dict] = []
        for year_str, value in country_data.items():
            try:
                year = int(year_str)
                val = float(value)
                if 2005 <= year <= 2025:
                    results.append({"metric": "bank_npl", "year": year, "value": val})
            except (ValueError, TypeError):
                continue
        return sorted(results, key=lambda r: r["year"])
    except Exception as exc:
        log.debug("IMF FSI fetch failed for %s: %s", country_code, exc)
        return []


async def ingest_imf_fsi() -> None:
    """Ingest IMF FSI bank NPL data for all tracked countries."""
    db = SessionLocal()
    inserted = 0
    try:
        for code in COUNTRIES:
            rows = await fetch_imf_npl(code)
            for row in rows:
                exists = (
                    db.query(Indicator)
                    .filter(
                        Indicator.country_code == code,
                        Indicator.metric == "bank_npl",
                        Indicator.year == row["year"],
                        Indicator.source == "imf_fsi",
                    )
                    .first()
                )
                if not exists:
                    db.add(Indicator(
                        country_code=code,
                        metric="bank_npl",
                        year=row["year"],
                        value=row["value"],
                        source="imf_fsi",
                    ))
                    inserted += 1
        db.commit()
        log.info("IMF FSI ingestion complete: %d rows inserted", inserted)
    finally:
        db.close()
