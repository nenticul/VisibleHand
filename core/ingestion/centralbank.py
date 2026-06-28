"""
Central bank statement ingestion.

Downloads PDF press releases and passes them through the NLP scorer.
Add more banks to CENTRAL_BANKS as needed.
"""

import httpx
from datetime import date

from api.models.database import SessionLocal, CentralBankStatement
from core.nlp.parsers import extract_text_from_pdf
from core.nlp.sentiment import score_statement

# Format: country_code → (bank_name, press_release_url)
# Most central banks publish statements at predictable URLs.
CENTRAL_BANKS: dict[str, tuple[str, str]] = {
    "US": ("Federal Reserve", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
    "GB": ("Bank of England", "https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes"),
    "DE": ("ECB", "https://www.ecb.europa.eu/press/pressconf/html/index.en.html"),
    "JP": ("Bank of Japan", "https://www.boj.or.jp/en/mopo/mpmdeci/"),
    "BR": ("Banco Central do Brasil", "https://www.bcb.gov.br/en/monetarypolicy/copomstatementsresults"),
}


async def _fetch_url(url: str) -> bytes | None:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": "VisibleHand/0.1"})
            resp.raise_for_status()
            return resp.content
        except Exception:
            return None


async def ingest_central_banks() -> None:
    db = SessionLocal()
    try:
        for country_code, (bank_name, url) in CENTRAL_BANKS.items():
            content = await _fetch_url(url)
            if content is None:
                continue

            if url.endswith(".pdf"):
                text = extract_text_from_pdf(content)
            else:
                # HTML page — extract visible text (basic strip)
                import re
                text = re.sub(r"<[^>]+>", " ", content.decode("utf-8", errors="ignore"))
                text = re.sub(r"\s+", " ", text).strip()[:4000]

            if len(text) < 100:
                continue

            sentiment = score_statement(text)
            db.add(
                CentralBankStatement(
                    country_code=country_code,
                    bank_name=bank_name,
                    statement_date=date.today().isoformat(),
                    raw_text=text[:8000],
                    sentiment_score=sentiment,
                )
            )
        db.commit()
    finally:
        db.close()
