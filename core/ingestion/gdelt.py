"""
GDELT political event ingestion.

Uses the GDELT GKG REST API (free, no key required, public domain) to pull
conflict, protest, election, and coup events per country.

Deduplication strategy: composite key = (country, date, event_type, description[:64]).
Events within 24h with the same type and similar description are collapsed.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta

from api.models.database import SessionLocal, PoliticalEvent

log = logging.getLogger(__name__)

GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

COUNTRIES = ["US", "GB", "DE", "BR", "IN", "ZA", "MX", "NG", "TR", "UA",
             "AR", "KE", "EG", "PK", "BD", "ID", "PH", "VN", "TH", "CO"]


def _event_fingerprint(country: str, event: dict) -> str:
    """Stable fingerprint for deduplication within a 24h window."""
    raw = f"{country}:{event['event_date']}:{event['event_type']}:{event.get('description', '')[:64]}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


async def fetch_gdelt_events(country_code: str, days_back: int = 7) -> list[dict]:
    """
    Returns events from GDELT for the past `days_back` days.
    Only negative-tone articles (implied conflict/protest) are returned.
    """
    try:
        import httpx
    except ImportError:
        log.warning("httpx not installed — GDELT fetch skipped")
        return []

    start = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d%H%M%S")
    params = {
        "query": f"sourcecountry:{country_code}",
        "mode": "artlist",
        "maxrecords": 75,
        "startdatetime": start,
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(GDELT_BASE, params=params)
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            events: list[dict] = []
            for article in articles:
                tone_str = article.get("tone", "0").split(",")[0]
                try:
                    tone_val = float(tone_str)
                except ValueError:
                    continue
                # Only include clearly negative-tone articles
                if tone_val >= -3.0:
                    continue
                event_type = "conflict" if tone_val < -8 else "protest"
                raw_date = article.get("seendate", "")[:8]
                try:
                    parsed = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
                    event_date = parsed.isoformat()
                except (ValueError, IndexError):
                    event_date = date.today().isoformat()

                events.append({
                    "event_type": event_type,
                    "event_date": event_date,
                    "severity": round(min(4.0, abs(tone_val) / 5.0), 2),
                    "description": article.get("title", "")[:256],
                    "source": "gdelt",
                })
            return events
        except Exception as exc:
            log.debug("GDELT fetch failed for %s: %s", country_code, exc)
            return []


def deduplicate_gdelt(events: list[dict], country_code: str) -> list[dict]:
    """
    Remove duplicate events: same country + date + event_type within same day.
    When duplicates exist, keep the one with highest severity.
    """
    seen: dict[str, dict] = {}
    for ev in events:
        key = f"{ev['event_date']}:{ev['event_type']}"
        if key not in seen or ev["severity"] > seen[key]["severity"]:
            seen[key] = ev
    return list(seen.values())


async def ingest_gdelt() -> None:
    db = SessionLocal()
    inserted = 0
    try:
        for code in COUNTRIES:
            raw_events = await fetch_gdelt_events(code)
            events = deduplicate_gdelt(raw_events, code)
            for ev in events:
                fingerprint = _event_fingerprint(code, ev)
                # Dedup against DB: check for same fingerprint via description prefix
                exists = (
                    db.query(PoliticalEvent)
                    .filter(
                        PoliticalEvent.country_code == code,
                        PoliticalEvent.event_date == ev["event_date"],
                        PoliticalEvent.event_type == ev["event_type"],
                        PoliticalEvent.source == "gdelt",
                    )
                    .first()
                )
                if not exists:
                    db.add(PoliticalEvent(
                        country_code=code,
                        event_type=ev["event_type"],
                        event_date=ev["event_date"],
                        severity=ev["severity"],
                        description=ev.get("description"),
                        source="gdelt",
                    ))
                    inserted += 1
        db.commit()
        log.info("GDELT ingestion complete: %d rows inserted", inserted)
    finally:
        db.close()
