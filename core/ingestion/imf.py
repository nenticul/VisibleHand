"""
IMF IFS ingestion.

Uses the IMF Data API to fetch debt-to-GDP and reserves data.
No API key required.
"""

import httpx

from api.models.database import SessionLocal, Indicator

# IMF IFS dataset codes: https://datahelp.imf.org/knowledgebase/articles/630877
IMF_INDICATORS: dict[str, str] = {
    "GGXWDG_NGDP": "debt_to_gdp_imf",  # General govt gross debt % GDP
    "BFI_BP6_USD": "fdi_inflows",
}

COUNTRIES = ["US", "GB", "DE", "JP", "CN", "BR", "IN", "ZA", "MX", "TR"]
IMF_BASE = "https://www.imf.org/external/datamapper/api/v1"


async def fetch_imf_indicator(indicator: str) -> dict[str, list[dict]]:
    """Return {country_code: [{year, value}, ...]}"""
    url = f"{IMF_BASE}/{indicator}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.json().get("values", {}).get(indicator, {})
            results: dict[str, list[dict]] = {}
            for country, yearly in raw.items():
                rows = [
                    {"year": int(y), "value": float(v)}
                    for y, v in yearly.items()
                    if v is not None
                ]
                if rows:
                    results[country] = rows
            return results
        except Exception:
            return {}


async def ingest_imf() -> None:
    db = SessionLocal()
    try:
        for wb_code, metric in IMF_INDICATORS.items():
            country_data = await fetch_imf_indicator(wb_code)
            for country_code, rows in country_data.items():
                if country_code not in COUNTRIES:
                    continue
                for row in rows:
                    exists = (
                        db.query(Indicator)
                        .filter(
                            Indicator.country_code == country_code,
                            Indicator.metric == metric,
                            Indicator.year == row["year"],
                            Indicator.source == "imf",
                        )
                        .first()
                    )
                    if not exists:
                        db.add(
                            Indicator(
                                country_code=country_code,
                                metric=metric,
                                year=row["year"],
                                value=row["value"],
                                source="imf",
                            )
                        )
        db.commit()
    finally:
        db.close()
