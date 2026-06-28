from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, DateTime, Text, Index, UniqueConstraint,
    create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker

from api.config import get_settings

_settings = get_settings()
DATABASE_URL = _settings.database_url

# SQLite (used in tests / quick local runs) doesn't accept pool sizing args.
_engine_kwargs: dict = {"pool_pre_ping": _settings.db_pool_pre_ping}
if not DATABASE_URL.startswith("sqlite"):
    _engine_kwargs.update(
        pool_size=_settings.db_pool_size,
        max_overflow=_settings.db_max_overflow,
    )

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class CountryScore(Base):
    __tablename__ = "country_scores"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String(3), index=True, nullable=False)
    composite = Column(Float, nullable=False)
    ci_low = Column(Float, nullable=True)
    ci_high = Column(Float, nullable=True)
    economic = Column(Float, nullable=True)
    political = Column(Float, nullable=True)
    nlp_sentiment = Column(Float, nullable=True)
    governance = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    top_drivers = Column(Text, nullable=True)   # JSON string
    driver_attributions = Column(Text, nullable=True)  # JSON string
    methodology = Column(Text, nullable=True)
    forecast_6m = Column(Text, nullable=True)   # JSON string
    forecast_12m = Column(Text, nullable=True)  # JSON string
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Indicator(Base):
    __tablename__ = "indicators"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String(3), index=True, nullable=False)
    metric = Column(String(64), nullable=False)     # e.g. "gdp_growth"
    year = Column(Integer, nullable=True)
    date = Column(String(16), nullable=True)        # ISO date string for daily data
    value = Column(Float, nullable=False)
    source = Column(String(32), nullable=True)      # "worldbank", "fred", "imf"
    fetched_at = Column(DateTime, default=datetime.utcnow)


class PoliticalEvent(Base):
    __tablename__ = "political_events"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String(3), index=True, nullable=False)
    event_type = Column(String(64), nullable=False)  # "protest", "conflict", "election"
    event_date = Column(String(16), nullable=False)
    severity = Column(Float, default=1.0)
    description = Column(Text, nullable=True)
    source = Column(String(32), nullable=True)       # "gdelt", "acled"
    fetched_at = Column(DateTime, default=datetime.utcnow)


class CentralBankStatement(Base):
    __tablename__ = "central_bank_statements"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String(3), index=True, nullable=False)
    bank_name = Column(String(128), nullable=True)
    statement_date = Column(String(16), nullable=True)
    raw_text = Column(Text, nullable=True)
    sentiment_score = Column(Float, nullable=True)  # 0 (dovish) to 100 (hawkish)
    aspect_scores = Column(Text, nullable=True)     # JSON: per-aspect risk scores
    fetched_at = Column(DateTime, default=datetime.utcnow)


class GovernanceIndicator(Base):
    __tablename__ = "governance_indicators"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String(3), index=True, nullable=False)
    metric = Column(String(64), nullable=False)      # e.g. "v2x_rule", "ti_cpi"
    year = Column(Integer, nullable=True)
    value = Column(Float, nullable=False)
    source = Column(String(32), nullable=True)       # "vdem", "wjp", "ti", "fh"
    fetched_at = Column(DateTime, default=datetime.utcnow)


class IngestionLog(Base):
    __tablename__ = "ingestion_log"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(64), nullable=False)
    country_code = Column(String(3), nullable=True)
    status = Column(String(16), nullable=False)     # "ok", "error", "skipped"
    records_fetched = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    ran_at = Column(DateTime, default=datetime.utcnow)


# ── VH-WSM: World-State Model layer ──────────────────────────────────────────
# Second-generation modelling tables built on top of the base scoring system.
# Dates are stored as ISO strings (YYYY-MM-DD) for cross-DB portability and so
# that lexicographic comparison == chronological comparison (used for the
# no-future-leakage rules in analogue search and hazard training).


class CountryStateFeature(Base):
    """Materialised modelling features per country/date (the VH-WSM feature store)."""
    __tablename__ = "country_state_features"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String(3), index=True, nullable=False)
    as_of_date = Column(String(16), index=True, nullable=False)

    visiblehand_score = Column(Float, nullable=False)
    risk_band = Column(String(32), nullable=False)

    economic_score = Column(Float, nullable=True)
    political_score = Column(Float, nullable=True)
    nlp_score = Column(Float, nullable=True)
    governance_score = Column(Float, nullable=True)

    confidence = Column(Float, nullable=True)
    ci_low = Column(Float, nullable=True)
    ci_high = Column(Float, nullable=True)

    inflation_z = Column(Float, nullable=True)
    debt_to_gdp_z = Column(Float, nullable=True)
    fx_reserves_z = Column(Float, nullable=True)
    current_account_z = Column(Float, nullable=True)
    unemployment_z = Column(Float, nullable=True)
    bank_npl_z = Column(Float, nullable=True)
    tax_revenue_z = Column(Float, nullable=True)
    remittances_z = Column(Float, nullable=True)
    credit_gap_z = Column(Float, nullable=True)

    event_count_30d = Column(Integer, nullable=True)
    event_count_90d = Column(Integer, nullable=True)
    event_count_180d = Column(Integer, nullable=True)
    political_severity_30d = Column(Float, nullable=True)
    hawkes_branching_ratio = Column(Float, nullable=True)

    nlp_monetary_score = Column(Float, nullable=True)
    nlp_fiscal_score = Column(Float, nullable=True)
    nlp_financial_stability_score = Column(Float, nullable=True)
    nlp_external_sector_score = Column(Float, nullable=True)
    nlp_political_economy_score = Column(Float, nullable=True)

    governance_structural_score = Column(Float, nullable=True)

    regional_mean_score = Column(Float, nullable=True)
    regional_max_score = Column(Float, nullable=True)
    neighbour_mean_score = Column(Float, nullable=True)
    trade_weighted_partner_score = Column(Float, nullable=True)

    data_quality_score = Column(Float, nullable=True)
    missing_feature_count = Column(Integer, nullable=True)

    model_version = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("country_code", "as_of_date", "model_version",
                         name="uq_csf_country_date_version"),
    )


class CountryStateEmbedding(Base):
    """Dense vector embeddings for analogue search / clustering.

    The vector is stored as a JSON array string so the schema is portable across
    SQLite (dev/tests) and Postgres (prod). Swap to pgvector for large scale."""
    __tablename__ = "country_state_embeddings"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String(3), index=True, nullable=False)
    as_of_date = Column(String(16), index=True, nullable=False)
    embedding_version = Column(String(64), nullable=False)
    embedding_dim = Column(Integer, nullable=False)
    embedding = Column(Text, nullable=False)             # JSON list[float]
    cluster_label = Column(String(128), nullable=True)
    cluster_confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("country_code", "as_of_date", "embedding_version",
                         name="uq_cse_country_date_version"),
    )


class HistoricalAnalogue(Base):
    """Precomputed nearest-neighbour historical states."""
    __tablename__ = "historical_analogues"

    id = Column(Integer, primary_key=True, index=True)
    query_country_code = Column(String(3), index=True, nullable=False)
    query_date = Column(String(16), index=True, nullable=False)
    analogue_country_code = Column(String(3), nullable=False)
    analogue_date = Column(String(16), nullable=False)
    similarity = Column(Float, nullable=False)
    rank = Column(Integer, nullable=False)
    outcome_6m = Column(String(128), nullable=True)
    outcome_12m = Column(String(128), nullable=True)
    outcome_18m = Column(String(128), nullable=True)
    embedding_version = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CrisisHazardPrediction(Base):
    """Per-country crisis-type hazard probabilities at a horizon."""
    __tablename__ = "crisis_hazard_predictions"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String(3), index=True, nullable=False)
    as_of_date = Column(String(16), index=True, nullable=False)
    horizon_months = Column(Integer, nullable=False)

    sovereign_default_prob = Column(Float, nullable=True)
    currency_crisis_prob = Column(Float, nullable=True)
    imf_programme_prob = Column(Float, nullable=True)
    banking_crisis_prob = Column(Float, nullable=True)
    civil_conflict_prob = Column(Float, nullable=True)
    coup_prob = Column(Float, nullable=True)
    sanctions_shock_prob = Column(Float, nullable=True)
    political_instability_prob = Column(Float, nullable=True)

    model_name = Column(String(128), nullable=False)
    model_version = Column(String(64), nullable=False)
    calibration_status = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("country_code", "as_of_date", "horizon_months",
                         "model_name", "model_version",
                         name="uq_chp_country_date_horizon_model"),
    )


class ModelLeaderboard(Base):
    """Benchmark results for hazard / world-state models."""
    __tablename__ = "model_leaderboard"

    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String(128), nullable=False)
    model_version = Column(String(64), nullable=False)
    target = Column(String(128), nullable=False)
    horizon_months = Column(Integer, nullable=False)

    auc = Column(Float, nullable=True)
    pr_auc = Column(Float, nullable=True)
    brier_score = Column(Float, nullable=True)
    calibration_error = Column(Float, nullable=True)
    log_loss = Column(Float, nullable=True)

    train_period = Column(String(64), nullable=True)
    test_period = Column(String(64), nullable=True)
    n_samples = Column(Integer, nullable=True)
    n_events = Column(Integer, nullable=True)

    report_path = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# Composite indexes for the hot query paths
Index("ix_indicators_country_metric", Indicator.country_code, Indicator.metric)
Index("ix_events_country_type", PoliticalEvent.country_code, PoliticalEvent.event_type)
Index("ix_scores_country_time", CountryScore.country_code, CountryScore.computed_at)
Index("ix_governance_country_metric", GovernanceIndicator.country_code, GovernanceIndicator.metric)
Index("ix_csf_country_date", CountryStateFeature.country_code, CountryStateFeature.as_of_date)
Index("ix_cse_country_date", CountryStateEmbedding.country_code, CountryStateEmbedding.as_of_date)
Index("ix_analogue_query", HistoricalAnalogue.query_country_code, HistoricalAnalogue.query_date)
Index("ix_hazard_country_date", CrisisHazardPrediction.country_code, CrisisHazardPrediction.as_of_date)
