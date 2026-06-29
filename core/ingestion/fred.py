"""
FRED (St. Louis Fed) ingestion.

Fetches daily/monthly series. Requires FRED_API_KEY env var.

Two families:
  1. US market series (yields, FX, policy rate, credit spread).
  2. Sovereign 10-year government bond yields (OECD via FRED) for 18 countries,
     from which a `sovereign_spread` (country yield minus US 10Y, by month) is
     derived and stored. The spread is a queryable risk indicator; it is NOT
     added to the economic WEIGHTS, so the calibrated composite is unchanged
     until a deliberate recalibration.
"""

from core.ingestion.http import get_json
from api.config import get_settings
from api.models.database import SessionLocal, Indicator

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# US market series mapped to (country_code, metric)
FRED_SERIES: dict[str, tuple[str, str]] = {
    "DGS10": ("US", "yield_10y"),
    "DEXUSEU": ("US", "usd_eur"),
    "DEXJPUS": ("US", "usd_jpy"),  # DEXUSJP was discontinued by FRED
    "FEDFUNDS": ("US", "fed_funds_rate"),
    "BAA10Y": ("US", "credit_spread"),
}

# OECD 10-year government bond yields (monthly, %), ISO2 -> FRED series id.
# Verified live against the FRED API; only series with current data are kept
# (RU excluded — OECD coverage stops in 2018). US is the spread anchor.
SOVEREIGN_YIELD_SERIES: dict[str, str] = {
    "US": "IRLTLT01USM156N",
    "AU": "IRLTLT01AUM156N",
    "CA": "IRLTLT01CAM156N",
    "CH": "IRLTLT01CHM156N",
    "CL": "IRLTLT01CLM156N",
    "DE": "IRLTLT01DEM156N",
    "ES": "IRLTLT01ESM156N",
    "FR": "IRLTLT01FRM156N",
    "GB": "IRLTLT01GBM156N",
    "GR": "IRLTLT01GRM156N",
    "HU": "IRLTLT01HUM156N",
    "IT": "IRLTLT01ITM156N",
    "JP": "IRLTLT01JPM156N",
    "KR": "IRLTLT01KRM156N",
    "MX": "IRLTLT01MXM156N",
    "NL": "IRLTLT01NLM156N",
    "PL": "IRLTLT01PLM156N",
    "ZA": "IRLTLT01ZAM156N",
}


async def fetch_fred_series(series_id: str, limit: int = 30) -> list[dict]:
    api_key = get_settings().fred_api_key
    if not api_key:
        return []

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "limit": limit,
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


def _upsert(db, country_code: str, metric: str, date: str, value: float) -> None:
    exists = (
        db.query(Indicator)
        .filter(
            Indicator.country_code == country_code,
            Indicator.metric == metric,
            Indicator.date == date,
            Indicator.source == "fred",
        )
        .first()
    )
    if not exists:
        db.add(Indicator(
            country_code=country_code,
            metric=metric,
            date=date,
            value=value,
            source="fred",
        ))


async def ingest_fred() -> None:
    db = SessionLocal()
    try:
        # ── 1. US market series ──────────────────────────────────────────────
        for series_id, (country_code, metric) in FRED_SERIES.items():
            for obs in await fetch_fred_series(series_id):
                _upsert(db, country_code, metric, obs["date"], obs["value"])

        # ── 2. Sovereign 10Y yields + derived spread vs US ──────────────────
        # Pull 10 years of monthly data so the scorer has real history.
        yields: dict[str, dict[str, float]] = {}
        for iso2, series_id in SOVEREIGN_YIELD_SERIES.items():
            obs_list = await fetch_fred_series(series_id, limit=120)
            by_date = {o["date"]: o["value"] for o in obs_list}
            yields[iso2] = by_date
            for date, value in by_date.items():
                _upsert(db, iso2, "bond_yield_10y", date, value)

        us_by_date = yields.get("US", {})
        for iso2, by_date in yields.items():
            if iso2 == "US":
                continue
            for date, value in by_date.items():
                us = us_by_date.get(date)
                if us is not None:
                    spread = round(value - us, 3)
                    _upsert(db, iso2, "sovereign_spread", date, spread)

        db.commit()
    finally:
        db.close()
