"""
IMF WEO ingestion (via the IMF DataMapper API — no API key required).

Two roles:
  1. Actuals: general govt gross debt (% GDP) and FDI inflows, kept as
     debt_to_gdp_imf / fdi_inflows for cross-checking World Bank.
  2. Projections: WEO forward estimates for real GDP growth (NGDP_RPCH) and
     average CPI inflation (PCPIPCH), stored as gdp_growth_proj /
     inflation_proj. These feed the economic scorer's nowcast layer
     (core/scoring/economic.py::_nowcast_score), which was already coded to
     read *_proj metrics but had no data source until now.

NOTE: the DataMapper API keys countries by ISO3 (USA, BRA, ...). The rest of
VisibleHand keys by ISO2, so we translate on the way in. (The previous version
filtered ISO3 keys against an ISO2 list and therefore stored nothing.)
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from api.models.database import SessionLocal, Indicator

log = logging.getLogger(__name__)

IMF_BASE = "https://www.imf.org/external/datamapper/api/v1"

# ISO3 (DataMapper) -> ISO2 (VisibleHand) for the 44-country universe.
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

# Actuals: WEO code -> stored metric name.
IMF_ACTUALS: dict[str, str] = {
    "GGXWDG_NGDP": "debt_to_gdp_imf",  # General govt gross debt, % GDP
    "BCA_NGDPD": "current_account_imf",  # Current account, % GDP
}

# Projections: WEO code -> stored metric name (forward years only).
IMF_PROJECTIONS: dict[str, str] = {
    "NGDP_RPCH": "gdp_growth_proj",  # Real GDP growth, % (annual)
    "PCPIPCH": "inflation_proj",     # Inflation, average consumer prices, %
}


async def fetch_imf_indicator(indicator: str) -> dict[str, dict[str, float]]:
    """Return {ISO3: {year: value}} for one WEO indicator."""
    url = f"{IMF_BASE}/{indicator}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.json().get("values", {}).get(indicator, {})
            out: dict[str, dict[str, float]] = {}
            for iso3, yearly in raw.items():
                rows = {y: float(v) for y, v in yearly.items() if v is not None}
                if rows:
                    out[iso3] = rows
            return out
        except Exception as exc:
            log.warning("IMF WEO fetch failed for %s: %s", indicator, exc)
            return {}


def _upsert(db, country_code: str, metric: str, year: int, value: float) -> int:
    exists = (
        db.query(Indicator)
        .filter(
            Indicator.country_code == country_code,
            Indicator.metric == metric,
            Indicator.year == year,
            Indicator.source == "imf",
        )
        .first()
    )
    if exists:
        # Projections are revised each WEO round — keep them current.
        if exists.value != value:
            exists.value = value
            return 1
        return 0
    db.add(Indicator(
        country_code=country_code,
        metric=metric,
        year=year,
        value=value,
        source="imf",
    ))
    return 1


async def ingest_imf() -> None:
    db = SessionLocal()
    inserted = 0
    current_year = datetime.utcnow().year
    try:
        # ── Actuals (history up to and including the current year) ───────────
        for code, metric in IMF_ACTUALS.items():
            data = await fetch_imf_indicator(code)
            for iso3, yearly in data.items():
                iso2 = _ISO3_TO_ISO2.get(iso3)
                if not iso2:
                    continue
                for y, v in yearly.items():
                    yi = int(y)
                    if yi <= current_year:
                        inserted += _upsert(db, iso2, metric, yi, v)

        # ── Projections (current year + next year) ───────────────────────────
        # The nowcast layer reads the latest *_proj value to bridge the WB data
        # lag, so we keep the horizon near-term (current + next year) rather than
        # the full 5-year WEO outlook.
        for code, metric in IMF_PROJECTIONS.items():
            data = await fetch_imf_indicator(code)
            for iso3, yearly in data.items():
                iso2 = _ISO3_TO_ISO2.get(iso3)
                if not iso2:
                    continue
                for y, v in yearly.items():
                    yi = int(y)
                    if current_year <= yi <= current_year + 1:
                        inserted += _upsert(db, iso2, metric, yi, v)

        db.commit()
        log.info("IMF WEO ingestion complete: %d rows upserted", inserted)
    finally:
        db.close()
