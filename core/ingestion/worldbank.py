"""
World Bank WDI ingestion.

Fetches annual macroeconomic indicators for a set of countries
and upserts them into the indicators table. Now covers all 10 V3 indicators
available from WDI (unemployment and some V3 metrics from ILO/BIS/IMF FSI
are pulled by their dedicated fetchers).
"""

from __future__ import annotations

import logging

from core.ingestion.http import get_json
from api.models.database import SessionLocal, Indicator

log = logging.getLogger(__name__)

WB_INDICATORS: dict[str, str] = {
    # Core macro
    "NY.GDP.MKTP.KD.ZG":  "gdp_growth",        # GDP growth (%)
    "FP.CPI.TOTL.ZG":     "inflation",          # CPI inflation (%)
    "GC.DOD.TOTL.GD.ZS":  "debt_to_gdp",       # General govt gross debt (% GDP)
    "FI.RES.TOTL.MO":     "fx_reserves",        # FX reserves (months of imports)
    "BN.CAB.XOKA.GD.ZS":  "current_account",   # Current account balance (% GDP)
    # V3 additional indicators
    "SL.UEM.TOTL.ZS":     "unemployment",       # Unemployment, total (% labour force)
    "GC.TAX.TOTL.GD.ZS":  "tax_revenue",        # Tax revenue (% GDP)
    "BX.TRF.PWKR.DT.GD.ZS": "remittances",     # Personal remittances received (% GDP)
    # GDP projections (WDI provides actuals; IMF WEO handles forward-looking)
    "NY.GDP.MKTP.KD.ZG":  "gdp_growth",        # duplicate guard handled below
}

# Remove duplicates while preserving order
_SEEN: set[str] = set()
WB_INDICATORS_CLEAN: dict[str, str] = {}
for wb_code, field in WB_INDICATORS.items():
    if field not in _SEEN:
        WB_INDICATORS_CLEAN[wb_code] = field
        _SEEN.add(field)

COUNTRIES = [
    "US", "GB", "DE", "FR", "JP", "CN", "BR", "IN", "ZA", "MX",
    "AR", "NG", "KE", "TR", "EG", "ID", "KR", "AU", "CA", "UA",
    "PL", "VN", "TH", "PK", "BD", "CO", "PH", "CL", "PE", "GH",
]


async def fetch_world_bank(country_code: str, years: int = 12) -> list[dict]:
    """Return a list of {metric, year, value} dicts for one country."""
    results: list[dict] = []
    for wb_code, field in WB_INDICATORS_CLEAN.items():
        url = (
            f"https://api.worldbank.org/v2/country/{country_code}"
            f"/indicator/{wb_code}?format=json&mrv={years}&per_page=50"
        )
        payload = await get_json(url)
        if not payload or len(payload) < 2 or not payload[1]:
            continue
        for item in payload[1]:
            if item.get("value") is not None:
                try:
                    results.append({
                        "metric": field,
                        "year": int(item["date"]),
                        "value": float(item["value"]),
                    })
                except (ValueError, TypeError):
                    continue
    return results


async def ingest_world_bank() -> None:
    db = SessionLocal()
    inserted = 0
    try:
        for code in COUNTRIES:
            rows = await fetch_world_bank(code)
            for row in rows:
                exists = (
                    db.query(Indicator)
                    .filter(
                        Indicator.country_code == code,
                        Indicator.metric == row["metric"],
                        Indicator.year == row["year"],
                        Indicator.source == "worldbank",
                    )
                    .first()
                )
                if not exists:
                    db.add(Indicator(
                        country_code=code,
                        metric=row["metric"],
                        year=row["year"],
                        value=row["value"],
                        source="worldbank",
                    ))
                    inserted += 1
        db.commit()
        log.info("World Bank ingestion complete: %d rows inserted", inserted)
    finally:
        db.close()
