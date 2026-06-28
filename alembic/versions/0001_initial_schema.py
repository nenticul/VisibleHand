"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "country_scores",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("country_code", sa.String(3), nullable=False, index=True),
        sa.Column("composite", sa.Float, nullable=False),
        sa.Column("economic", sa.Float, nullable=True),
        sa.Column("political", sa.Float, nullable=True),
        sa.Column("nlp_sentiment", sa.Float, nullable=True),
        sa.Column("top_drivers", sa.Text, nullable=True),
        sa.Column("methodology", sa.Text, nullable=True),
        sa.Column("computed_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "indicators",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("country_code", sa.String(3), nullable=False, index=True),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("date", sa.String(16), nullable=True),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("fetched_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "political_events",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("country_code", sa.String(3), nullable=False, index=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_date", sa.String(16), nullable=False),
        sa.Column("severity", sa.Float, default=1.0),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("fetched_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "central_bank_statements",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("country_code", sa.String(3), nullable=False, index=True),
        sa.Column("bank_name", sa.String(128), nullable=True),
        sa.Column("statement_date", sa.String(16), nullable=True),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("sentiment_score", sa.Float, nullable=True),
        sa.Column("fetched_at", sa.DateTime, nullable=True),
    )

    # Composite indexes for the hot query paths.
    op.create_index("ix_indicators_country_metric", "indicators", ["country_code", "metric"])
    op.create_index("ix_events_country_type", "political_events", ["country_code", "event_type"])
    op.create_index("ix_scores_country_time", "country_scores", ["country_code", "computed_at"])


def downgrade() -> None:
    op.drop_index("ix_scores_country_time", table_name="country_scores")
    op.drop_index("ix_events_country_type", table_name="political_events")
    op.drop_index("ix_indicators_country_metric", table_name="indicators")
    op.drop_table("central_bank_statements")
    op.drop_table("political_events")
    op.drop_table("indicators")
    op.drop_table("country_scores")
