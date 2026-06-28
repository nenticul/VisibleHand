"""
FRED (St. Louis Fed) ingestion.

Fetches daily/monthly series. Requires FRED_API_KEY env var.
"""

from core.ingestion.http import get_json
from api.config import get_settings
from api.models.database import SessionLocal, Indicator

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Series mapped to (country_code, metric)
FRED_SERIES: dict[str, tuple[str, str]] = {
    "DGS10": ("US", "yield_10y"),
    "DEXUSEU": ("US", "usd_eur"),
    "DEXUSJP": ("US", "usd_jpy"),
    "FEDFUNDS": ("US", "fed_funds_rate"),
    "BAA10Y": ("US", "credit_spread"),
}


async def fetch_fred_series(series_id: str) -> list[dict]:
    api_key = get_settings().fred_api_key
    if not api_key:
        return []

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "limit": 30,
        "sort_order": "desc",
    }
    data = await get_json(FRED_BASE, params=params)
    if not data:
        return []
    return [
        {"date": obs["date"], "value": float(obs["value"])}
        for obs in data.get("observations", [])
        if obs.get("value") not in (".", None)
    ]


async def ingest_fred() -> None:
    db = SessionLocal()
    try:
        for series_id, (country_code, metric) in FRED_SERIES.items():
            observations = await fetch_fred_series(series_id)
            for obs in observations:
                exists = (
                    db.query(Indicator)
                    .filter(
                        Indicator.country_code == country_code,
                        Indicator.metric == metric,
                        Indicator.date == obs["date"],
                        Indicator.source == "fred",
                    )
                    .first()
                )
                if not exists:
                    db.add(
                        Indicator(
                            country_code=country_code,
                            metric=metric,
                            date=obs["date"],
                            value=obs["value"],
                            source="fred",
                        )
                    )
        db.commit()
    finally:
        db.close()
