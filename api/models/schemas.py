from __future__ import annotations

from typing import Optional, Any
from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    economic: Optional[float] = Field(None, description="Economic sub-score 0–100")
    political: Optional[float] = Field(None, description="Political sub-score 0–100")
    nlp_sentiment: Optional[float] = Field(None, description="NLP hawkishness sub-score 0–100")
    governance: Optional[float] = Field(None, description="Governance quality risk sub-score 0–100")


class ForecastPoint(BaseModel):
    composite: float
    ci_low: float
    ci_high: float


class DriverAttribution(BaseModel):
    name: str
    contribution: float = Field(description="Signed risk contribution (positive = risk-raising)")
    direction: str = Field(description="'risk' or 'stable'")
    sub_scorer: str


class RiskResponse(BaseModel):
    country: str = Field(..., description="ISO 3166-1 alpha-2 country code", examples=["BR"])
    name: str = Field(..., description="Country name", examples=["Brazil"])
    composite: float = Field(..., ge=0, le=100, description="Composite risk (0=stable, 100=high risk)")
    ci_low: Optional[float] = Field(None, description="95% confidence interval lower bound")
    ci_high: Optional[float] = Field(None, description="95% confidence interval upper bound")
    confidence: float = Field(0.0, ge=0, le=1, description="Data coverage confidence (0–1)")
    risk_level: str = Field("Unknown", description="Human-readable band, e.g. 'High'")
    breakdown: ScoreBreakdown
    top_drivers: list[str] = Field(default_factory=list)
    driver_attributions: list[DriverAttribution] = Field(
        default_factory=list,
        description="Signed per-indicator contributions to composite (linear decomposition)",
    )
    methodology: Optional[str] = Field(None, description="Plain-language score explanation")
    components: Optional[dict[str, Any]] = Field(None, description="Per-component detail")
    forecast: Optional[dict[str, ForecastPoint]] = Field(
        None, description="Score extrapolations: '6m', '12m' horizons"
    )
    regime_flags: Optional[dict[str, Any]] = Field(None, description="Regime detection flags")
    updated_at: str

    model_config = {"from_attributes": True}


class IndicatorRow(BaseModel):
    country_code: str
    metric: str
    value: float
    year: Optional[int] = None
    date: Optional[str] = None
    source: Optional[str] = None

    model_config = {"from_attributes": True}


class EventRow(BaseModel):
    country_code: str
    event_type: str
    event_date: str
    severity: float = 1.0
    description: Optional[str] = None
    source: Optional[str] = None

    model_config = {"from_attributes": True}


class HistoryPoint(BaseModel):
    date: str
    composite: float
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    economic: Optional[float] = None
    political: Optional[float] = None
    nlp_sentiment: Optional[float] = None
    governance: Optional[float] = None
    confidence: Optional[float] = None


class MoverPoint(BaseModel):
    country: str
    name: str
    composite: float
    delta: float
    direction: str  # "up" | "down"
    risk_level: str


class AspectScoresResponse(BaseModel):
    country: str
    monetary_policy: Optional[float] = None
    fiscal_policy: Optional[float] = None
    financial_stability: Optional[float] = None
    external_sector: Optional[float] = None
    political_economy: Optional[float] = None
    overall: float = 50.0
    document_count: int = 0
    updated_at: Optional[str] = None


class GovernanceResponse(BaseModel):
    country: str
    score: float
    confidence: float
    components: dict[str, float] = Field(default_factory=dict)
    drivers: list[str] = Field(default_factory=list)
    press_freedom_modifier: float = 1.0
    updated_at: Optional[str] = None


class CalibrationSummary(BaseModel):
    description: str
    methodology_version: str
    component_weights: dict[str, float]
    note: str


class WeightOverride(BaseModel):
    economic_weight: float = Field(0.45, ge=0, le=1)
    political_weight: float = Field(0.25, ge=0, le=1)
    nlp_weight: float = Field(0.20, ge=0, le=1)
    governance_weight: float = Field(0.10, ge=0, le=1)


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    scored_countries: int
