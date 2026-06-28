"""Governance, forecast, confidence intervals, ingestion log

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-27

Adds:
  - country_scores: ci_low, ci_high, governance, confidence, driver_attributions,
    forecast_6m, forecast_12m columns
  - central_bank_statements: aspect_scores column
  - New tables: governance_indicators, ingestion_log
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── country_scores additions ─────────────────────────────────────────────
    with op.batch_alter_table("country_scores") as batch_op:
        batch_op.add_column(sa.Column("ci_low", sa.Float, nullable=True))
        batch_op.add_column(sa.Column("ci_high", sa.Float, nullable=True))
        batch_op.add_column(sa.Column("governance", sa.Float, nullable=True))
        batch_op.add_column(sa.Column("confidence", sa.Float, nullable=True))
        batch_op.add_column(sa.Column("driver_attributions", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("forecast_6m", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("forecast_12m", sa.Text, nullable=True))

    # ── central_bank_statements: aspect scores ───────────────────────────────
    with op.batch_alter_table("central_bank_statements") as batch_op:
        batch_op.add_column(sa.Column("aspect_scores", sa.Text, nullable=True))

    # ── governance_indicators ────────────────────────────────────────────────
    op.create_table(
        "governance_indicators",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("country_code", sa.String(3), nullable=False, index=True),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("fetched_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "ix_governance_country_metric",
        "governance_indicators",
        ["country_code", "metric"],
    )

    # ── ingestion_log ────────────────────────────────────────────────────────
    op.create_table(
        "ingestion_log",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("country_code", sa.String(3), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("records_fetched", sa.Integer, default=0),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("ran_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ingestion_log")
    op.drop_index("ix_governance_country_metric", table_name="governance_indicators")
    op.drop_table("governance_indicators")

    with op.batch_alter_table("central_bank_statements") as batch_op:
        batch_op.drop_column("aspect_scores")

    with op.batch_alter_table("country_scores") as batch_op:
        batch_op.drop_column("forecast_12m")
        batch_op.drop_column("forecast_6m")
        batch_op.drop_column("driver_attributions")
        batch_op.drop_column("confidence")
        batch_op.drop_column("governance")
        batch_op.drop_column("ci_high")
        batch_op.drop_column("ci_low")
