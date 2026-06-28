"""
Resilient HTTP helper for ingestion pipelines.

External data APIs (World Bank, FRED, IMF, GDELT) are flaky: rate limits,
transient 5xx, timeouts. This wraps httpx with exponential-backoff retries so a
single hiccup doesn't abort a nightly ingestion run.
"""

from __future__ import annotations

import logging

import httpx

from api.config import get_settings

log = logging.getLogger("visiblehand.ingestion")
_settings = get_settings()

try:
    from tenacity import (
        retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
    )
    _HAS_TENACITY = True
except ImportError:
    _HAS_TENACITY = False


_RETRYABLE = (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError)


async def _do_get(url: str, params: dict | None, headers: dict | None) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_settings.http_timeout, follow_redirects=True) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp


if _HAS_TENACITY:
    @retry(
        stop=stop_after_attempt(_settings.http_max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    async def get(url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
        return await _do_get(url, params, headers)
else:
    async def get(url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
        # No tenacity: a single manual retry so we still tolerate one transient fail.
        try:
            return await _do_get(url, params, headers)
        except _RETRYABLE:
            return await _do_get(url, params, headers)


async def get_json(url: str, params: dict | None = None, headers: dict | None = None):
    """GET and parse JSON, returning None on any failure (logged)."""
    try:
        resp = await get(url, params=params, headers=headers)
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("ingestion GET failed: %s (%s)", url, exc)
        return None
