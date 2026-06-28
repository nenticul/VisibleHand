"""Tests for data ingestion fetchers (mocked HTTP)."""

import os
import pytest
from unittest.mock import AsyncMock, patch


# ── World Bank ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_worldbank_fetch_parses_payload():
    payload = [
        {"page": 1},
        [
            {"date": "2023", "value": 2.5},
            {"date": "2022", "value": 3.1},
            {"date": "2021", "value": None},  # nulls skipped
        ],
    ]
    with patch("core.ingestion.worldbank.get_json", new=AsyncMock(return_value=payload)):
        from core.ingestion.worldbank import fetch_world_bank
        results = await fetch_world_bank("BR")
    assert isinstance(results, list)
    assert all(r["value"] is not None for r in results)
    assert all("metric" in r and "year" in r for r in results)


@pytest.mark.asyncio
async def test_worldbank_handles_empty():
    with patch("core.ingestion.worldbank.get_json", new=AsyncMock(return_value=None)):
        from core.ingestion.worldbank import fetch_world_bank
        results = await fetch_world_bank("ZZ")
    assert results == []


# ── FRED ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fred_returns_empty_without_key():
    os.environ.pop("FRED_API_KEY", None)
    from api.config import get_settings
    get_settings.cache_clear()
    from core.ingestion.fred import fetch_fred_series
    results = await fetch_fred_series("DGS10")
    assert results == []


# ── HTTP helper ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_json_swallows_errors():
    with patch("core.ingestion.http.get", new=AsyncMock(side_effect=Exception("boom"))):
        from core.ingestion.http import get_json
        result = await get_json("https://example.com")
    assert result is None


# ── ILO ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ilo_fetch_parses_observations():
    fake_payload = {
        "data": {
            "Observation": {
                "2022:1:1:1:1": [4.5],
                "2021:1:1:1:1": [5.1],
                "2020:1:1:1:1": [6.2],
            }
        }
    }
    with patch("core.ingestion.ilo.get_json", new=AsyncMock(return_value=fake_payload)):
        from core.ingestion.ilo import fetch_ilo_unemployment
        results = await fetch_ilo_unemployment("DE")
    assert len(results) == 3
    assert all(r["metric"] == "unemployment" for r in results)
    years = {r["year"] for r in results}
    assert 2022 in years


@pytest.mark.asyncio
async def test_ilo_returns_empty_on_failure():
    with patch("core.ingestion.ilo.get_json", new=AsyncMock(return_value=None)):
        from core.ingestion.ilo import fetch_ilo_unemployment
        results = await fetch_ilo_unemployment("XX")
    assert results == []


# ── IMF FSI ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_imf_fsi_parses_npl():
    fake_payload = {
        "values": {
            "FSANL_PT": {
                "DE": {
                    "2022": 1.3,
                    "2021": 1.5,
                    "2019": 1.7,
                }
            }
        }
    }
    with patch("core.ingestion.imf_fsi.get_json", new=AsyncMock(return_value=fake_payload)):
        from core.ingestion.imf_fsi import fetch_imf_npl
        results = await fetch_imf_npl("DE")
    assert len(results) == 3
    assert all(r["metric"] == "bank_npl" for r in results)
    values = {r["year"]: r["value"] for r in results}
    assert values[2022] == pytest.approx(1.3)


@pytest.mark.asyncio
async def test_imf_fsi_returns_empty_on_bad_response():
    with patch("core.ingestion.imf_fsi.get_json", new=AsyncMock(return_value={})):
        from core.ingestion.imf_fsi import fetch_imf_npl
        results = await fetch_imf_npl("XX")
    assert results == []


# ── GDELT deduplication ───────────────────────────────────────────────────────

def test_gdelt_deduplication_collapses_same_day_type():
    from core.ingestion.gdelt import deduplicate_gdelt
    events = [
        {"event_type": "protest", "event_date": "2024-01-15", "severity": 1.0, "description": "A"},
        {"event_type": "protest", "event_date": "2024-01-15", "severity": 2.5, "description": "B"},
        {"event_type": "conflict", "event_date": "2024-01-15", "severity": 1.0, "description": "C"},
    ]
    result = deduplicate_gdelt(events, "NG")
    assert len(result) == 2
    protest = next(e for e in result if e["event_type"] == "protest")
    assert protest["severity"] == 2.5


def test_gdelt_deduplication_keeps_different_dates():
    from core.ingestion.gdelt import deduplicate_gdelt
    events = [
        {"event_type": "protest", "event_date": "2024-01-14", "severity": 1.0, "description": ""},
        {"event_type": "protest", "event_date": "2024-01-15", "severity": 1.5, "description": ""},
    ]
    result = deduplicate_gdelt(events, "NG")
    assert len(result) == 2


# ── ACLED (no credentials) ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_acled_returns_empty_without_credentials():
    from unittest.mock import MagicMock
    with patch("core.ingestion.acled.get_settings") as mock_get:
        mock_settings = MagicMock()
        mock_settings.acled_api_key = ""
        mock_settings.acled_email = ""
        mock_get.return_value = mock_settings
        from core.ingestion.acled import fetch_acled_events
        results = await fetch_acled_events("UA")
    assert results == []


# ── BIS ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bis_returns_empty_on_bad_response():
    with patch("core.ingestion.bis.get_json", new=AsyncMock(return_value=None)):
        from core.ingestion.bis import fetch_bis_credit_gap
        results = await fetch_bis_credit_gap("US")
    assert results == []
