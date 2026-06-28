"""Dataclasses and API response models for VH-WSM."""

from __future__ import annotations

from dataclasses import dataclass, asdict, fields
from typing import Optional

from pydantic import BaseModel


# ── Internal feature row (mirrors country_state_features) ─────────────────────
@dataclass
class CountryStateFeatureRow:
    country_code: str
    as_of_date: str
    visiblehand_score: float
    risk_band: str

    economic_score: Optional[float] = None
    political_score: Optional[float] = None
    nlp_score: Optional[float] = None
    governance_score: Optional[float] = None

    confidence: Optional[float] = None
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None

    inflation_z: Optional[float] = None
    debt_to_gdp_z: Optional[float] = None
    fx_reserves_z: Optional[float] = None
    current_account_z: Optional[float] = None
    unemployment_z: Optional[float] = None
    bank_npl_z: Optional[float] = None
    tax_revenue_z: Optional[float] = None
    remittances_z: Optional[float] = None
    credit_gap_z: Optional[float] = None

    event_count_30d: Optional[int] = None
    event_count_90d: Optional[int] = None
    event_count_180d: Optional[int] = None
    political_severity_30d: Optional[float] = None
    hawkes_branching_ratio: Optional[float] = None

    nlp_monetary_score: Optional[float] = None
    nlp_fiscal_score: Optional[float] = None
    nlp_financial_stability_score: Optional[float] = None
    nlp_external_sector_score: Optional[float] = None
    nlp_political_economy_score: Optional[float] = None

    governance_structural_score: Optional[float] = None

    regional_mean_score: Optional[float] = None
    regional_max_score: Optional[float] = None
    neighbour_mean_score: Optional[float] = None
    trade_weighted_partner_score: Optional[float] = None

    data_quality_score: Optional[float] = None
    missing_feature_count: Optional[int] = None

    model_version: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def column_names(cls) -> list[str]:
        return [f.name for f in fields(cls)]


# ── API response models ──────────────────────────────────────────────────────
class AnalogueItem(BaseModel):
    rank: int
    country: str
    date: str
    similarity: float
    outcome_6m: Optional[str] = None
    outcome_12m: Optional[str] = None
    outcome_18m: Optional[str] = None


class AnaloguesResponse(BaseModel):
    country: str
    date: str
    embedding_version: str
    analogues: list[AnalogueItem]


class HazardsResponse(BaseModel):
    country: str
    date: str
    horizon_months: int
    model: str
    model_version: str
    calibration_status: str
    hazards: dict[str, float]


class SpilloverResponse(BaseModel):
    country: str
    date: str
    spillover: dict[str, float | bool | None]


class UncertaintyResponse(BaseModel):
    country: str
    date: str
    score: float
    conformal_90: list[float]
    coverage_target: float
    empirical_coverage: Optional[float] = None
    abstain: bool
    abstain_reasons: list[str] = []


class EmbeddingResponse(BaseModel):
    country: str
    date: str
    embedding_version: str
    embedding_dim: int
    embedding: list[float]
    cluster: Optional[str] = None
    cluster_confidence: Optional[float] = None


class LeaderboardEntry(BaseModel):
    model_name: str
    model_version: str
    target: str
    horizon_months: int
    auc: Optional[float] = None
    pr_auc: Optional[float] = None
    brier_score: Optional[float] = None
    calibration_error: Optional[float] = None
    log_loss: Optional[float] = None
    train_period: Optional[str] = None
    test_period: Optional[str] = None
    n_samples: Optional[int] = None
    n_events: Optional[int] = None


class StateResponse(BaseModel):
    country: str
    name: str
    date: str
    base_score: dict
    world_state: dict
    hazards_12m: dict[str, float]
    nearest_analogues: list[AnalogueItem]
    spillover: dict
    uncertainty: dict
    model_metadata: dict
