"""
VisibleHand Python SDK v0.3.0

Full typed client for the VisibleHand political-economic risk API.

Usage:
    from visiblehand import Client

    client = Client()                        # public API
    score = client.risk("BR")
    print(score.composite)                   # 52.0
    print(score.ci_low, score.ci_high)       # 46.5, 57.6
    print(score.top_drivers)                 # ['rapid_escalation', ...]
    print(score.governance)                  # 45.5

    # Async client
    import asyncio
    from visiblehand import AsyncClient
    async def main():
        async with AsyncClient() as c:
            score = await c.risk("UA")
            print(score.composite, score.confidence)
    asyncio.run(main())

    # Compare multiple countries
    scores = client.compare("US", "DE", "BR", "IN")
    for s in sorted(scores, key=lambda x: x.composite, reverse=True):
        print(f"{s.country}: {s.composite:.1f} [{s.ci_low:.1f}-{s.ci_high:.1f}]")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import httpx


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ScoreBreakdown:
    economic: Optional[float] = None
    political: Optional[float] = None
    nlp_sentiment: Optional[float] = None
    governance: Optional[float] = None

    @classmethod
    def _from_dict(cls, d: dict) -> "ScoreBreakdown":
        return cls(
            economic=d.get("economic"),
            political=d.get("political"),
            nlp_sentiment=d.get("nlp_sentiment"),
            governance=d.get("governance"),
        )


@dataclass
class DriverAttribution:
    name: str
    contribution: float
    direction: str   # "risk" | "stable"
    sub_scorer: str

    @classmethod
    def _from_dict(cls, d: dict) -> "DriverAttribution":
        return cls(
            name=d["name"],
            contribution=d["contribution"],
            direction=d["direction"],
            sub_scorer=d["sub_scorer"],
        )


@dataclass
class ForecastPoint:
    composite: float
    ci_low: float
    ci_high: float

    @classmethod
    def _from_dict(cls, d: dict) -> "ForecastPoint":
        return cls(
            composite=d["composite"],
            ci_low=d["ci_low"],
            ci_high=d["ci_high"],
        )


@dataclass
class RiskScore:
    country: str
    name: str
    composite: float
    breakdown: ScoreBreakdown
    top_drivers: list[str]
    # V3 fields
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    confidence: float = 0.0
    risk_level: str = "Unknown"
    economic: Optional[float] = None
    political: Optional[float] = None
    nlp_sentiment: Optional[float] = None
    governance: Optional[float] = None
    driver_attributions: list[DriverAttribution] = field(default_factory=list)
    forecast: Optional[dict[str, ForecastPoint]] = None
    regime_flags: dict = field(default_factory=dict)
    methodology: Optional[str] = None
    components: Optional[dict] = None
    updated_at: str = ""

    @classmethod
    def _from_dict(cls, data: dict) -> "RiskScore":
        bd = data.get("breakdown", {})
        attributions = [
            DriverAttribution._from_dict(a)
            for a in data.get("driver_attributions", [])
        ]
        forecast_raw = data.get("forecast") or {}
        forecast = {
            k: ForecastPoint._from_dict(v)
            for k, v in forecast_raw.items()
            if isinstance(v, dict)
        } or None

        return cls(
            country=data["country"],
            name=data.get("name", data["country"]),
            composite=data["composite"],
            breakdown=ScoreBreakdown._from_dict(bd),
            top_drivers=data.get("top_drivers", []),
            ci_low=data.get("ci_low"),
            ci_high=data.get("ci_high"),
            confidence=data.get("confidence", 0.0),
            risk_level=data.get("risk_level", "Unknown"),
            economic=bd.get("economic"),
            political=bd.get("political"),
            nlp_sentiment=bd.get("nlp_sentiment"),
            governance=bd.get("governance"),
            driver_attributions=attributions,
            forecast=forecast,
            regime_flags=data.get("regime_flags") or {},
            methodology=data.get("methodology"),
            components=data.get("components"),
            updated_at=data.get("updated_at", ""),
        )

    def __repr__(self) -> str:
        ci = f" [{self.ci_low:.1f}-{self.ci_high:.1f}]" if self.ci_low is not None else ""
        return f"<RiskScore {self.country} {self.composite:.1f}{ci} {self.risk_level}>"


@dataclass
class GovernanceScore:
    country: str
    score: float
    confidence: float
    components: dict
    drivers: list[str] = field(default_factory=list)

    @classmethod
    def _from_dict(cls, data: dict) -> "GovernanceScore":
        return cls(
            country=data["country"],
            score=data["score"],
            confidence=data["confidence"],
            components=data.get("components", {}),
            drivers=data.get("drivers", []),
        )


@dataclass
class AspectScores:
    overall: float
    monetary_policy: Optional[float] = None
    fiscal_policy: Optional[float] = None
    financial_stability: Optional[float] = None
    external_sector: Optional[float] = None
    political_economy: Optional[float] = None
    sentence_count: int = 0

    @classmethod
    def _from_dict(cls, data: dict) -> "AspectScores":
        return cls(
            overall=data.get("overall", 50.0),
            monetary_policy=data.get("monetary_policy"),
            fiscal_policy=data.get("fiscal_policy"),
            financial_stability=data.get("financial_stability"),
            external_sector=data.get("external_sector"),
            political_economy=data.get("political_economy"),
            sentence_count=data.get("sentence_count", 0),
        )


@dataclass
class HistoryPoint:
    date: str
    composite: float
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    economic: Optional[float] = None
    political: Optional[float] = None
    governance: Optional[float] = None
    confidence: Optional[float] = None

    @classmethod
    def _from_dict(cls, data: dict) -> "HistoryPoint":
        return cls(
            date=data["date"],
            composite=data["composite"],
            ci_low=data.get("ci_low"),
            ci_high=data.get("ci_high"),
            economic=data.get("economic"),
            political=data.get("political"),
            governance=data.get("governance"),
            confidence=data.get("confidence"),
        )


# ── Sync client ───────────────────────────────────────────────────────────────

class Client:
    """
    Synchronous VisibleHand API client.

    Args:
        api_key: Optional API key for authenticated access.
        base_url: Base URL of the API. Defaults to the public hosted instance.
        timeout: Request timeout in seconds.
    """

    DEFAULT_BASE = "https://api.visiblehand.dev"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = {"X-API-Key": api_key} if api_key else {}

    def _get(self, path: str, **params) -> dict:
        url = f"{self.base_url}{path}"
        resp = httpx.get(url, params=params, headers=self._headers, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def risk(
        self,
        country_code: str,
        economic_weight: Optional[float] = None,
        political_weight: Optional[float] = None,
        nlp_weight: Optional[float] = None,
        governance_weight: Optional[float] = None,
    ) -> RiskScore:
        """Return composite risk score for a country (V3: includes CI, governance, forecast)."""
        params: dict = {}
        if economic_weight is not None:
            params["economic_weight"] = economic_weight
        if political_weight is not None:
            params["political_weight"] = political_weight
        if nlp_weight is not None:
            params["nlp_weight"] = nlp_weight
        if governance_weight is not None:
            params["governance_weight"] = governance_weight
        return RiskScore._from_dict(self._get(f"/risk/{country_code.upper()}", **params))

    def compare(self, *country_codes: str, **weights: float) -> list[RiskScore]:
        """Compare risk scores for multiple countries."""
        params = {"countries": ",".join(c.upper() for c in country_codes)}
        params.update({k: str(v) for k, v in weights.items()})
        data = self._get("/risk/compare", **params)
        return [RiskScore._from_dict(r) for r in data]

    def history(self, country_code: str, limit: int = 90) -> list[HistoryPoint]:
        """Return historical composite scores (oldest first)."""
        data = self._get(f"/risk/{country_code.upper()}/history", limit=limit)
        return [HistoryPoint._from_dict(r) for r in data]

    def forecast(self, country_code: str) -> dict:
        """Return 6m and 12m Theil-Sen score extrapolations."""
        return self._get(f"/risk/{country_code.upper()}/forecast")

    def drivers(self, country_code: str) -> dict:
        """Return signed driver attributions for a country."""
        return self._get(f"/risk/{country_code.upper()}/drivers")

    def governance(self, country_code: str) -> GovernanceScore:
        """Return governance sub-score breakdown."""
        return GovernanceScore._from_dict(self._get(f"/governance/{country_code.upper()}"))

    def aspects(self, country_code: str) -> AspectScores:
        """Return NLP aspect scores from latest central-bank statement."""
        return AspectScores._from_dict(self._get(f"/risk/{country_code.upper()}/aspects"))

    def movers(self, days: int = 7, limit: int = 10) -> list[dict]:
        """Return countries with the largest composite score changes."""
        return self._get("/risk/movers", days=days, limit=limit)

    def bulk(self, page: int = 1, page_size: int = 30) -> list[RiskScore]:
        """Return all scored countries, paginated."""
        data = self._get("/risk/bulk", page=page, page_size=page_size)
        return [RiskScore._from_dict(r) for r in data]

    def calibration(self) -> dict:
        """Return methodology summary and backtest AUC."""
        return self._get("/calibration/summary")

    def health(self) -> dict:
        """Check API health."""
        return self._get("/health")


# ── Async client ──────────────────────────────────────────────────────────────

class AsyncClient:
    """
    Async VisibleHand API client. Use as an async context manager.

    Example:
        async with AsyncClient() as client:
            score = await client.risk("BR")
    """

    DEFAULT_BASE = "https://api.visiblehand.dev"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = {"X-API-Key": api_key} if api_key else {}
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "AsyncClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=self._timeout,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def _get(self, path: str, **params) -> dict:
        assert self._client is not None, "Use AsyncClient as an async context manager"
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def risk(self, country_code: str, **weights: float) -> RiskScore:
        return RiskScore._from_dict(
            await self._get(f"/risk/{country_code.upper()}", **weights)
        )

    async def compare(self, *country_codes: str, **weights: float) -> list[RiskScore]:
        params = {"countries": ",".join(c.upper() for c in country_codes)}
        params.update({k: str(v) for k, v in weights.items()})
        data = await self._get("/risk/compare", **params)
        return [RiskScore._from_dict(r) for r in data]

    async def history(self, country_code: str, limit: int = 90) -> list[HistoryPoint]:
        data = await self._get(f"/risk/{country_code.upper()}/history", limit=limit)
        return [HistoryPoint._from_dict(r) for r in data]

    async def governance(self, country_code: str) -> GovernanceScore:
        return GovernanceScore._from_dict(
            await self._get(f"/governance/{country_code.upper()}")
        )

    async def movers(self, days: int = 7, limit: int = 10) -> list[dict]:
        return await self._get("/risk/movers", days=days, limit=limit)

    async def bulk(self, page: int = 1, page_size: int = 30) -> list[RiskScore]:
        data = await self._get("/risk/bulk", page=page, page_size=page_size)
        return [RiskScore._from_dict(r) for r in data]


__all__ = [
    "Client",
    "AsyncClient",
    "RiskScore",
    "ScoreBreakdown",
    "DriverAttribution",
    "ForecastPoint",
    "GovernanceScore",
    "AspectScores",
    "HistoryPoint",
]
