"""
ACLED (Armed Conflict Location & Event Data) ingestion.

Auth: ACLED now uses OAuth2 password grant (Keycloak) — set:
  ACLED_EMAIL=your@email.com
  ACLED_PASSWORD=your_account_password

A 24-hour access token is fetched automatically and cached in memory for
the lifetime of the process. The legacy ACLED_API_KEY is no longer used.

Non-commercial only — see DATA_SOURCES.md and TERMS_OF_USE.md.
API docs: https://acleddata.com/api-documentation/
"""

from __future__ import annotations

import logging
import time

import httpx

from core.ingestion.http import get_json
from api.config import get_settings
from api.models.database import SessionLocal, PoliticalEvent

log = logging.getLogger(__name__)

_ACLED_AUTH_URL = "https://acleddata.com/realms/acled/protocol/openid-connect/token"
_ACLED_BASE = "https://api.acleddata.com/acled/read"

# All 44 scored countries: ISO2 → ACLED country name
_COUNTRIES: dict[str, str] = {
    "AR": "Argentina",       "AU": "Australia",      "BD": "Bangladesh",
    "BR": "Brazil",          "CA": "Canada",         "CH": "Switzerland",
    "CL": "Chile",           "CN": "China",          "CO": "Colombia",
    "DE": "Germany",         "EG": "Egypt",          "ES": "Spain",
    "ET": "Ethiopia",        "FR": "France",         "GB": "United Kingdom",
    "GH": "Ghana",           "GR": "Greece",         "HU": "Hungary",
    "ID": "Indonesia",       "IN": "India",          "IT": "Italy",
    "JP": "Japan",           "KE": "Kenya",          "KR": "South Korea",
    "LB": "Lebanon",         "LK": "Sri Lanka",      "MA": "Morocco",
    "MX": "Mexico",          "MY": "Malaysia",       "NG": "Nigeria",
    "NL": "Netherlands",     "PE": "Peru",           "PH": "Philippines",
    "PK": "Pakistan",        "PL": "Poland",         "RU": "Russia",
    "SA": "Saudi Arabia",    "TH": "Thailand",       "TR": "Turkey",
    "UA": "Ukraine",         "US": "United States",  "VE": "Venezuela",
    "VN": "Vietnam",         "ZA": "South Africa",
}

_token_cache: dict = {"token": "", "expires_at": 0.0}


async def _get_token(email: str, password: str) -> str:
    """Return a cached Bearer token, refreshing if within 5 min of expiry."""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 300:
        return _token_cache["token"]
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _ACLED_AUTH_URL,
            data={
                "username": email,
                "password": password,
                "grant_type": "password",
                "client_id": "acled",
                "scope": "authenticated",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    token = payload["access_token"]
    expires_in = float(payload.get("expires_in", 86400))
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + expires_in
    log.info("ACLED token refreshed, valid for %.0fs", expires_in)
    return token


async def fetch_acled_events(
    country_iso2: str,
    days_back: int = 30,
) -> list[dict]:
    """
    Fetch ACLED events for a country (ISO2 code).
    Returns event dicts compatible with the political scorer / PoliticalEvent model.
    """
    settings = get_settings()
    email = getattr(settings, "acled_email", "")
    password = getattr(settings, "acled_password", "")

    if not email or not password:
        log.debug("ACLED credentials not configured — skipping %s", country_iso2)
        return []

    country_name = _COUNTRIES.get(country_iso2)
    if not country_name:
        log.debug("Unknown country %s — skipping", country_iso2)
        return []

    try:
        token = await _get_token(email, password)
    except Exception as exc:
        log.warning("ACLED token fetch failed: %s", exc)
        return []

    from datetime import date, timedelta
    since = (date.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    params = {
        "country": country_name,
        "event_date": since,
        "event_date_where": ">=",
        "fields": "event_date|event_type|sub_event_type|fatalities|notes",
        "limit": 500,
    }
    try:
        data = await get_json(
            _ACLED_BASE,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if not data or "data" not in data:
            return []

        events: list[dict] = []
        for row in data["data"]:
            fatalities = int(row.get("fatalities") or 0)
            # Encode fatalities into severity (base 1, +0.1 per death, cap 10)
            severity = min(1.0 + fatalities * 0.1, 10.0)
            desc = (row.get("notes") or "")[:200].strip()
            if fatalities:
                desc = f"[{fatalities} fatalities] {desc}"[:256]
            events.append({
                "event_type": row.get("event_type", "Unknown"),
                "event_date": row.get("event_date", ""),
                "severity": severity,
                "description": desc,
                "source": "acled",
            })
        return events
    except Exception as exc:
        log.warning("ACLED fetch failed for %s: %s", country_iso2, exc)
        return []


async def ingest_acled() -> None:
    """Ingest ACLED events for all 44 scored countries."""
    db = SessionLocal()
    inserted = 0
    try:
        for iso2 in _COUNTRIES:
            events = await fetch_acled_events(iso2)
            for ev in events:
                exists = (
                    db.query(PoliticalEvent)
                    .filter(
                        PoliticalEvent.country_code == iso2,
                        PoliticalEvent.event_date == ev["event_date"],
                        PoliticalEvent.event_type == ev["event_type"],
                        PoliticalEvent.source == "acled",
                    )
                    .first()
                )
                if not exists:
                    db.add(PoliticalEvent(
                        country_code=iso2,
                        event_type=ev["event_type"],
                        event_date=ev["event_date"],
                        severity=ev["severity"],
                        description=ev.get("description"),
                        source="acled",
                    ))
                    inserted += 1
        db.commit()
        log.info("ACLED ingestion complete: %d rows inserted", inserted)
    finally:
        db.close()
