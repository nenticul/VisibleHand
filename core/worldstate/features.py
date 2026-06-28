"""
VH-WSM feature store builder.

Materialises modelling features per (country, as_of_date) from data already
persisted by the base VisibleHand system. No network calls, deterministic for a
given (country, date, model_version), and leakage-safe: every historical row is
computed using only indicator/governance/event data dated on or before
``as_of_date`` (expanding-window robust z-scores).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from api.models.database import (
    Indicator, GovernanceIndicator, PoliticalEvent, CountryScore,
    CentralBankStatement, CountryStateFeature,
)
from core.worldstate import registry as R
from core.worldstate.schemas import CountryStateFeatureRow

# Governance metric → conversion to a 0-100 risk score (higher = worse).
_GOV_BETTER_0_1 = {"v2x_rule", "v2x_corr", "v2x_jucon", "wjp_rule_of_law"}
_GOV_BETTER_0_100 = {"ti_cpi"}
_GOV_WORSE_1_7 = {"fh_political", "fh_civil"}


def _robust_z(history: list[float], current: float) -> Optional[float]:
    """Median/MAD z-score of ``current`` against ``history`` (which includes it)."""
    arr = np.asarray([v for v in history if v is not None], dtype=float)
    if arr.size < 3:
        return None
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    if mad <= 1e-9:
        std = float(arr.std())
        if std <= 1e-9:
            return 0.0
        return float((current - med) / std)
    return float((current - med) / (1.4826 * mad))


def _z_to_risk(z: Optional[float], sign: int) -> Optional[float]:
    """Map a signed z-score to a 0-100 risk via logistic squashing."""
    if z is None or sign == 0:
        return None
    x = max(-8.0, min(8.0, sign * z))
    return float(100.0 / (1.0 + math.exp(-x)))


def _gov_metric_to_risk(metric: str, value: float) -> Optional[float]:
    if metric in _GOV_BETTER_0_1:
        return float((1.0 - value) * 100.0)
    if metric in _GOV_BETTER_0_100:
        return float(100.0 - value)
    if metric in _GOV_WORSE_1_7:
        return float((value - 1.0) / 6.0 * 100.0)
    return None


def _parse_iso(d: str) -> Optional[date]:
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d").date()
    except Exception:
        return None


class CountryStateFeatureBuilder:
    """Builds :class:`CountryStateFeatureRow` objects from persisted data."""

    def __init__(self, db: Session, model_version: str = R.FEATURE_VERSION):
        self.db = db
        self.model_version = model_version

    # ── public API ────────────────────────────────────────────────────────────
    def historical_dates(self, country_code: str) -> list[str]:
        """Year-end ISO dates for which this country has economic indicators."""
        years = (
            self.db.query(Indicator.year)
            .filter(Indicator.country_code == country_code)
            .filter(Indicator.year.isnot(None))
            .distinct().all()
        )
        ys = sorted({int(y[0]) for y in years if y[0] is not None})
        return [f"{y}-12-31" for y in ys]

    def build(
        self,
        country_code: str,
        as_of_date: str,
        source_score: Optional[CountryScore] = None,
    ) -> CountryStateFeatureRow:
        code = country_code.upper()
        year = int(as_of_date[:4])

        # ── economic z-scores (expanding window <= year) ──────────────────────
        z_by_metric = self._economic_z(code, year)

        # ── governance structural risk (<= year) ──────────────────────────────
        gov_risk = self._governance_risk(code, year)

        # ── economic risk proxy ────────────────────────────────────────────────
        econ_risks = [
            _z_to_risk(z_by_metric.get(m), R.ECON_RISK_SIGN.get(m, 0))
            for m in R.ECON_METRICS
        ]
        econ_risks = [r for r in econ_risks if r is not None]
        economic_proxy = float(np.mean(econ_risks)) if econ_risks else None

        # ── base score / components ────────────────────────────────────────────
        if source_score is not None:
            visiblehand_score = float(source_score.composite)
            economic_score = source_score.economic
            political_score = source_score.political
            nlp_score = source_score.nlp_sentiment
            governance_score = source_score.governance if source_score.governance is not None else gov_risk
            confidence = source_score.confidence
            ci_low, ci_high = source_score.ci_low, source_score.ci_high
        else:
            # Historical proxy: blend economic + governance risk.
            economic_score = economic_proxy
            political_score = None
            nlp_score = None
            governance_score = gov_risk
            parts, weights = [], []
            if economic_proxy is not None:
                parts.append(economic_proxy); weights.append(0.7)
            if gov_risk is not None:
                parts.append(gov_risk); weights.append(0.3)
            visiblehand_score = (
                float(np.average(parts, weights=weights)) if parts else 50.0
            )
            confidence = None
            ci_low = ci_high = None

        # ── political event windows ────────────────────────────────────────────
        ev30, ev90, ev180, sev30 = self._event_windows(code, as_of_date)

        # ── nlp aspect scores (live only — from latest statement) ─────────────
        nlp_aspects = self._nlp_aspects(code, as_of_date)

        row = CountryStateFeatureRow(
            country_code=code,
            as_of_date=as_of_date,
            visiblehand_score=round(visiblehand_score, 4),
            risk_band=R.risk_band(visiblehand_score),
            economic_score=_round(economic_score),
            political_score=_round(political_score),
            nlp_score=_round(nlp_score),
            governance_score=_round(governance_score),
            confidence=_round(confidence),
            ci_low=_round(ci_low),
            ci_high=_round(ci_high),
            inflation_z=_round(z_by_metric.get("inflation")),
            debt_to_gdp_z=_round(z_by_metric.get("debt_to_gdp")),
            fx_reserves_z=_round(z_by_metric.get("fx_reserves")),
            current_account_z=_round(z_by_metric.get("current_account")),
            unemployment_z=_round(z_by_metric.get("unemployment")),
            bank_npl_z=_round(z_by_metric.get("bank_npl")),
            tax_revenue_z=_round(z_by_metric.get("tax_revenue")),
            remittances_z=_round(z_by_metric.get("remittances")),
            credit_gap_z=_round(z_by_metric.get("credit_gap")),
            event_count_30d=ev30,
            event_count_90d=ev90,
            event_count_180d=ev180,
            political_severity_30d=_round(sev30),
            hawkes_branching_ratio=None,
            nlp_monetary_score=_round(nlp_aspects.get("monetary_policy")),
            nlp_fiscal_score=_round(nlp_aspects.get("fiscal_policy")),
            nlp_financial_stability_score=_round(nlp_aspects.get("financial_stability")),
            nlp_external_sector_score=_round(nlp_aspects.get("external_sector")),
            nlp_political_economy_score=_round(nlp_aspects.get("political_economy")),
            governance_structural_score=_round(gov_risk),
            model_version=self.model_version,
        )
        # spillover fields are filled by graph.add_spillover() across a batch
        self._set_quality(row)
        return row

    def build_panel(
        self, country_code: str, source_score: Optional[CountryScore] = None
    ) -> list[CountryStateFeatureRow]:
        """All historical year rows for a country (latest gets ``source_score``)."""
        dates = self.historical_dates(country_code)
        rows: list[CountryStateFeatureRow] = []
        for i, d in enumerate(dates):
            ss = source_score if (i == len(dates) - 1) else None
            rows.append(self.build(country_code, d, source_score=ss))
        return rows

    # ── internals ─────────────────────────────────────────────────────────────
    def _economic_z(self, code: str, year: int) -> dict[str, Optional[float]]:
        rows = (
            self.db.query(Indicator)
            .filter(Indicator.country_code == code)
            .filter(Indicator.year.isnot(None))
            .filter(Indicator.year <= year)
            .all()
        )
        series: dict[str, list[tuple[int, float]]] = {}
        for r in rows:
            series.setdefault(r.metric, []).append((int(r.year), float(r.value)))
        out: dict[str, Optional[float]] = {}
        for metric in R.ECON_METRICS:
            # Use the most recent observation on or before `year` as "current"
            # (so an as-of date past the last indicator year still resolves).
            pts = sorted(series.get(metric, []))
            if not pts:
                out[metric] = None
                continue
            history = [v for (_, v) in pts]
            out[metric] = _robust_z(history, pts[-1][1])
        return out

    def _governance_risk(self, code: str, year: int) -> Optional[float]:
        rows = (
            self.db.query(GovernanceIndicator)
            .filter(GovernanceIndicator.country_code == code)
            .filter(GovernanceIndicator.year.isnot(None))
            .filter(GovernanceIndicator.year <= year)
            .all()
        )
        # latest value per metric (<= year)
        latest: dict[str, tuple[int, float]] = {}
        for r in rows:
            y = int(r.year)
            if r.metric not in latest or y > latest[r.metric][0]:
                latest[r.metric] = (y, float(r.value))
        risks = []
        for metric, (_, val) in latest.items():
            rk = _gov_metric_to_risk(metric, val)
            if rk is not None:
                risks.append(rk)
        return float(np.mean(risks)) if risks else None

    def _event_windows(self, code: str, as_of_date: str):
        as_of = _parse_iso(as_of_date)
        if as_of is None:
            return 0, 0, 0, 0.0
        rows = (
            self.db.query(PoliticalEvent)
            .filter(PoliticalEvent.country_code == code)
            .all()
        )
        ev30 = ev90 = ev180 = 0
        sev30 = 0.0
        for r in rows:
            d = _parse_iso(r.event_date)
            if d is None or d > as_of:
                continue
            delta = (as_of - d).days
            if 0 <= delta < 30:
                ev30 += 1
                sev30 += float(r.severity or 0.0)
            if 0 <= delta < 90:
                ev90 += 1
            if 0 <= delta < 180:
                ev180 += 1
        return ev30, ev90, ev180, sev30

    def _nlp_aspects(self, code: str, as_of_date: str) -> dict:
        import json
        as_of = _parse_iso(as_of_date)
        stmt = (
            self.db.query(CentralBankStatement)
            .filter(CentralBankStatement.country_code == code)
            .order_by(CentralBankStatement.fetched_at.desc())
            .first()
        )
        if not stmt:
            return {}
        sd = _parse_iso(stmt.statement_date) if stmt.statement_date else None
        if as_of is not None and sd is not None and sd > as_of:
            return {}
        if not stmt.aspect_scores:
            return {}
        try:
            data = json.loads(stmt.aspect_scores)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _set_quality(self, row: CountryStateFeatureRow) -> None:
        expected = R.EMBEDDING_FEATURE_COLUMNS + ["economic_score", "governance_score"]
        present = sum(1 for c in expected if getattr(row, c) is not None)
        missing = len(expected) - present
        row.missing_feature_count = missing
        row.data_quality_score = round(present / len(expected), 4)


def _round(v, nd: int = 4):
    return round(float(v), nd) if isinstance(v, (int, float)) else (None if v is None else v)


# ── persistence ──────────────────────────────────────────────────────────────
def persist_features(db: Session, rows: list[CountryStateFeatureRow]) -> int:
    """Upsert feature rows (delete-then-insert on the natural key)."""
    n = 0
    for row in rows:
        db.query(CountryStateFeature).filter(
            CountryStateFeature.country_code == row.country_code,
            CountryStateFeature.as_of_date == row.as_of_date,
            CountryStateFeature.model_version == row.model_version,
        ).delete()
        db.add(CountryStateFeature(**row.to_dict()))
        n += 1
    db.commit()
    return n
