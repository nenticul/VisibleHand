"""
ACLED (Armed Conflict Location & Event Data) ingestion.

REQUIRES: ACLED_API_KEY and ACLED_EMAIL environment variables.
ACLED is free for non-commercial use with registration. Set:
  ACLED_API_KEY=your_key
  ACLED_EMAIL=your@email.com

Non-commercial only — see DATA_SOURCES.md and TERMS_OF_USE.md.
API docs: https://acleddata.com/acleddatanerd/acled-developer/
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from core.ingestion.http import get_json
from api.config import get_settings
from api.models.database import SessionLocal, PoliticalEvent

log = logging.getLogger(__name__)

_ACLED_BASE = "https://api.acleddata.com/acled/read"

# ACLED event types we care about, mapped to our internal taxonomy
_ACLED_TYPE_MAP: dict[str, str] = {
    "Battles": "Battles",
    "Explosions/Remote violence": "Explosions/Remote violence",
    "Violence against civilians": "Violence against civilians",
    "Riots": "Riots",
    "Protests": "Protests",
    "Strategic developments": "Strategic developments",
}

COUNTRIES = [
    "UA", "NG", "ET", "CD", "ML", "SS", "SO", "AF", "SY", "YE",
    "MM", "MX", "BR", "IN", "PK", "BD", "ZA", "KE", "EG", "TR",
]


async def fetch_acled_events(
    country_code: str,
    days_back: int = 30,
) -> list[dict]:
    """
    Fetch ACLED events for a country. Requires API key and email.
    Returns list of event dicts compatible with the political scorer.
    """
    settings = get_settings()
    api_key = getattr(settings, "acled_api_key", "")
    email = getattr(settings, "acled_email", "")

    if not api_key or not email:
        log.debug("ACLED credentials not set — skipping %s", country_code)
        return []

    since = (date.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    params = {
        "key": api_key,
        "email": email,
        "iso": country_code,
        "event_date": since,
        "event_date_where": ">=",
        "fields": "event_date|event_type|sub_event_type|fatalities|notes",
        "limit": 500,
    }
    try:
        data = await get_json(_ACLED_BASE, params=params)
        if not data or "data" not in data:
            return []

        events: list[dict] = []
        for row in data["data"]:
            etype = row.get("event_type", "default")
            # Map to our internal taxonomy (passes through ACLED event types
            # directly since the political scorer has ACLED_INTENSITY lookup)
            events.append({
                "event_type": etype,
                "event_date": row.get("event_date", ""),
                "severity": 1.0,  # ACLED doesn't have severity; intensity from ACLED_INTENSITY
                "fatalities": int(row.get("fatalities") or 0),
                "description": (row.get("notes") or "")[:256],
                "source": "acled",
            })
        return events
    except Exception as exc:
        log.warning("ACLED fetch failed for %s: %s", country_code, exc)
        return []


async def ingest_acled() -> None:
    """Ingest ACLED events for all conflict-affected countries."""
    db = SessionLocal()
    inserted = 0
    try:
        for code in COUNTRIES:
            events = await fetch_acled_events(code)
            for ev in events:
                # Deduplicate by (country, date, type, source)
                exists = (
                    db.query(PoliticalEvent)
                    .filter(
                        PoliticalEvent.country_code == code,
                        PoliticalEvent.event_date == ev["event_date"],
                        PoliticalEvent.event_type == ev["event_type"],
                        PoliticalEvent.source == "acled",
                    )
                    .first()
                )
                if not exists:
                    db.add(PoliticalEvent(
                        country_code=code,
                        event_type=ev["event_type"],
                        event_date=ev["event_date"],
                        severity=ev["severity"],
                        fatalities=ev.get("fatalities"),
                        description=ev.get("description"),
                        source="acled",
                    ))
                    inserted += 1
        db.commit()
        log.info("ACLED ingestion complete: %d rows inserted", inserted)
    finally:
        db.close()
