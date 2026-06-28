"""VH-WSM World-State Model layer

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-27

Adds the second-generation modelling tables:
  - country_state_features      (materialised feature store)
  - country_state_embeddings    (dense vectors for analogue search)
  - historical_analogues        (precomputed nearest neighbours)
  - crisis_hazard_predictions   (per-crisis-type probabilities)
  - model_leaderboard           (benchmark results)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "country_state_features",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("country_code", sa.String(3), nullable=False, index=True),
        sa.Column("as_of_date", sa.String(16), nullable=False, index=True),
        sa.Column("visiblehand_score", sa.Float, nullable=False),
        sa.Column("risk_band", sa.String(32), nullable=False),
        sa.Column("economic_score", sa.Float, nullable=True),
        sa.Column("political_score", sa.Float, nullable=True),
        sa.Column("nlp_score", sa.Float, nullable=True),
        sa.Column("governance_score", sa.Float, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("ci_low", sa.Float, nullable=True),
        sa.Column("ci_high", sa.Float, nullable=True),
        sa.Column("inflation_z", sa.Float, nullable=True),
        sa.Column("debt_to_gdp_z", sa.Float, nullable=True),
        sa.Column("fx_reserves_z", sa.Float, nullable=True),
        sa.Column("current_account_z", sa.Float, nullable=True),
        sa.Column("unemployment_z", sa.Float, nullable=True),
        sa.Column("bank_npl_z", sa.Float, nullable=True),
        sa.Column("tax_revenue_z", sa.Float, nullable=True),
        sa.Column("remittances_z", sa.Float, nullable=True),
        sa.Column("credit_gap_z", sa.Float, nullable=True),
        sa.Column("event_count_30d", sa.Integer, nullable=True),
        sa.Column("event_count_90d", sa.Integer, nullable=True),
        sa.Column("event_count_180d", sa.Integer, nullable=True),
        sa.Column("political_severity_30d", sa.Float, nullable=True),
        sa.Column("hawkes_branching_ratio", sa.Float, nullable=True),
        sa.Column("nlp_monetary_score", sa.Float, nullable=True),
        sa.Column("nlp_fiscal_score", sa.Float, nullable=True),
        sa.Column("nlp_financial_stability_score", sa.Float, nullable=True),
        sa.Column("nlp_external_sector_score", sa.Float, nullable=True),
        sa.Column("nlp_political_economy_score", sa.Float, nullable=True),
        sa.Column("governance_structural_score", sa.Float, nullable=True),
        sa.Column("regional_mean_score", sa.Float, nullable=True),
        sa.Column("regional_max_score", sa.Float, nullable=True),
        sa.Column("neighbour_mean_score", sa.Float, nullable=True),
        sa.Column("trade_weighted_partner_score", sa.Float, nullable=True),
        sa.Column("data_quality_score", sa.Float, nullable=True),
        sa.Column("missing_feature_count", sa.Integer, nullable=True),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("country_code", "as_of_date", "model_version",
                            name="uq_csf_country_date_version"),
    )
    op.create_index("ix_csf_country_date", "country_state_features",
                    ["country_code", "as_of_date"])

    op.create_table(
        "country_state_embeddings",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("country_code", sa.String(3), nullable=False, index=True),
        sa.Column("as_of_date", sa.String(16), nullable=False, index=True),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("embedding_dim", sa.Integer, nullable=False),
        sa.Column("embedding", sa.Text, nullable=False),
        sa.Column("cluster_label", sa.String(128), nullable=True),
        sa.Column("cluster_confidence", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("country_code", "as_of_date", "embedding_version",
                            name="uq_cse_country_date_version"),
    )
    op.create_index("ix_cse_country_date", "country_state_embeddings",
                    ["country_code", "as_of_date"])

    op.create_table(
        "historical_analogues",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("query_country_code", sa.String(3), nullable=False, index=True),
        sa.Column("query_date", sa.String(16), nullable=False, index=True),
        sa.Column("analogue_country_code", sa.String(3), nullable=False),
        sa.Column("analogue_date", sa.String(16), nullable=False),
        sa.Column("similarity", sa.Float, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("outcome_6m", sa.String(128), nullable=True),
        sa.Column("outcome_12m", sa.String(128), nullable=True),
        sa.Column("outcome_18m", sa.String(128), nullable=True),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_analogue_query", "historical_analogues",
                    ["query_country_code", "query_date"])

    op.create_table(
        "crisis_hazard_predictions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("country_code", sa.String(3), nullable=False, index=True),
        sa.Column("as_of_date", sa.String(16), nullable=False, index=True),
        sa.Column("horizon_months", sa.Integer, nullable=False),
        sa.Column("sovereign_default_prob", sa.Float, nullable=True),
        sa.Column("currency_crisis_prob", sa.Float, nullable=True),
        sa.Column("imf_programme_prob", sa.Float, nullable=True),
        sa.Column("banking_crisis_prob", sa.Float, nullable=True),
        sa.Column("civil_conflict_prob", sa.Float, nullable=True),
        sa.Column("coup_prob", sa.Float, nullable=True),
        sa.Column("sanctions_shock_prob", sa.Float, nullable=True),
        sa.Column("political_instability_prob", sa.Float, nullable=True),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("calibration_status", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("country_code", "as_of_date", "horizon_months",
                            "model_name", "model_version",
                            name="uq_chp_country_date_horizon_model"),
    )
    op.create_index("ix_hazard_country_date", "crisis_hazard_predictions",
                    ["country_code", "as_of_date"])

    op.create_table(
        "model_leaderboard",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("horizon_months", sa.Integer, nullable=False),
        sa.Column("auc", sa.Float, nullable=True),
        sa.Column("pr_auc", sa.Float, nullable=True),
        sa.Column("brier_score", sa.Float, nullable=True),
        sa.Column("calibration_error", sa.Float, nullable=True),
        sa.Column("log_loss", sa.Float, nullable=True),
        sa.Column("train_period", sa.String(64), nullable=True),
        sa.Column("test_period", sa.String(64), nullable=True),
        sa.Column("n_samples", sa.Integer, nullable=True),
        sa.Column("n_events", sa.Integer, nullable=True),
        sa.Column("report_path", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("model_leaderboard")
    op.drop_index("ix_hazard_country_date", table_name="crisis_hazard_predictions")
    op.drop_table("crisis_hazard_predictions")
    op.drop_index("ix_analogue_query", table_name="historical_analogues")
    op.drop_table("historical_analogues")
    op.drop_index("ix_cse_country_date", table_name="country_state_embeddings")
    op.drop_table("country_state_embeddings")
    op.drop_index("ix_csf_country_date", table_name="country_state_features")
    op.drop_table("country_state_features")
