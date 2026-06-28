"""
BIS Statistics ingestion — credit-to-GDP gap.

Uses the BIS public statistics REST API (free for non-commercial use).
Dataset: TOTAL_CREDIT — Total credit to the private non-financial sector.
We compute the gap as (credit/GDP ratio - long-run trend) using a simple
HP-filter approximation (available directly from BIS as the "gap" series).

BIS dataset: https://www.bis.org/statistics/totcredit.htm
REST API: https://stats.bis.org/api/v2/
"""

from __future__ import annotations

import logging

from core.ingestion.http import get_json
from api.models.database import SessionLocal, Indicator

log = logging.getLogger(__name__)

_BIS_BASE = "https://stats.bis.org/api/v2"

# BIS uses ISO-2 country codes for most series
# Credit-to-GDP gap: dataset C_GAPS, series CRED_GAP_TOTAL_A
COUNTRIES = [
    "US", "GB", "DE", "FR", "JP", "CN", "BR", "IN", "ZA", "MX",
    "AU", "CA", "KR", "TR", "ID", "PL",
]


async def fetch_bis_credit_gap(country_code: str) -> list[dict]:
    """
    Fetch the BIS credit-to-GDP gap (% of GDP) for a country.
    Returns list of {metric, year, value}.
    """
    # BIS SDMX-JSON API: data/C_GAPS/{country}:CRED_GAP_TOTAL_A
    url = (
        f"{_BIS_BASE}/data/dataflow/BIS/BIS%2CC_GAPS%2C1.0/all"
        f"?startPeriod=2010&endPeriod=2024"
        f"&dimensionAtObservation=TIME_PERIOD"
        f"&format=jsondata"
    )
    # The BIS SDMX API is complex; use the simpler CSV-compatible endpoint
    # Fallback: BIS also provides a simpler JSON endpoint per series
    csv_url = (
        f"https://stats.bis.org/api/v2/data/dataflow/BIS/BIS%2CC_GAPS%2C1.0"
        f"/{country_code}.Q.C.770.A.M?startPeriod=2010"
        f"&format=jsondata&detail=dataonly"
    )
    try:
        data = await get_json(csv_url)
        if not data:
            return []

        # Parse SDMX-JSON structure
        datasets = data.get("data", {}).get("dataSets", [])
        if not datasets:
            return []

        structure = data.get("data", {}).get("structure", {})
        dimensions = structure.get("dimensions", {}).get("observation", [])
        time_dim = next((d for d in dimensions if d.get("id") == "TIME_PERIOD"), None)
        if not time_dim:
            return []

        time_values = [v["id"] for v in time_dim.get("values", [])]
        observations = datasets[0].get("observations", {})

        results: list[dict] = []
        for idx_str, obs_val in observations.items():
            try:
                idx = int(idx_str)
                period = time_values[idx]
                year = int(period[:4])
                value = float(obs_val[0])
                results.append({"metric": "credit_gdp_gap", "year": year, "value": value})
            except (ValueError, IndexError, TypeError):
                continue

        # Deduplicate by year (take latest observation per year)
        by_year: dict[int, float] = {}
        for r in results:
            by_year[r["year"]] = r["value"]
        return [{"metric": "credit_gdp_gap", "year": y, "value": v}
                for y, v in sorted(by_year.items())]

    except Exception as exc:
        log.debug("BIS fetch failed for %s: %s", country_code, exc)
        return []


async def ingest_bis() -> None:
    """Ingest BIS credit-to-GDP gap data."""
    db = SessionLocal()
    inserted = 0
    try:
        for code in COUNTRIES:
            rows = await fetch_bis_credit_gap(code)
            for row in rows:
                exists = (
                    db.query(Indicator)
                    .filter(
                        Indicator.country_code == code,
                        Indicator.metric == "credit_gdp_gap",
                        Indicator.year == row["year"],
                        Indicator.source == "bis",
                    )
                    .first()
                )
                if not exists:
                    db.add(Indicator(
                        country_code=code,
                        metric="credit_gdp_gap",
                        year=row["year"],
                        value=row["value"],
                        source="bis",
                    ))
                    inserted += 1
        db.commit()
        log.info("BIS ingestion complete: %d rows inserted", inserted)
    finally:
        db.close()
