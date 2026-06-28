"""
Fit the conformal calibrator and print a VH-WSM evaluation summary.

The score calibrator is fitted on year-over-year score movements across the
historical panel (a predictive-stability residual distribution), yielding an
empirically grounded interval half-width. Coverage is reported alongside.

Usage:
    python scripts/evaluate_worldstate.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np

from api.models.database import (
    SessionLocal, Base, engine, CountryStateFeature, ModelLeaderboard,
)
from core.worldstate import registry as R
from core.worldstate.uncertainty import ConformalCalibrator
from core.worldstate.service import _CONFORMAL_PATH


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        rows = (
            db.query(CountryStateFeature)
            .filter(CountryStateFeature.model_version == R.FEATURE_VERSION)
            .order_by(CountryStateFeature.country_code, CountryStateFeature.as_of_date)
            .all()
        )
        if not rows:
            print("No feature rows. Run materialize_worldstate.py first.")
            return

        # year-over-year score change per country = predictive residual proxy
        by_country: dict[str, list] = {}
        for r in rows:
            by_country.setdefault(r.country_code, []).append(r)
        y_true, y_pred = [], []
        for c, rs in by_country.items():
            rs = sorted(rs, key=lambda r: r.as_of_date)
            for a, b in zip(rs, rs[1:]):
                y_pred.append(float(a.visiblehand_score))   # naive persistence forecast
                y_true.append(float(b.visiblehand_score))   # realised next state

        cal = ConformalCalibrator().fit(np.asarray(y_true), np.asarray(y_pred))
        os.makedirs(os.path.dirname(_CONFORMAL_PATH), exist_ok=True)
        cal.save(_CONFORMAL_PATH)
        rep = cal.coverage_report(alpha=0.1)
        print("Conformal calibrator fitted (predictive-stability residuals):")
        print(f"  n={rep['n']}  half_width(90%)={rep['half_width']}  "
              f"empirical_coverage={rep['empirical_coverage']} "
              f"(target {rep['coverage_target']})")
        print(f"  saved -> {_CONFORMAL_PATH}")

        # leaderboard summary
        lb = db.query(ModelLeaderboard).order_by(
            ModelLeaderboard.target, ModelLeaderboard.horizon_months).all()
        print(f"\nLeaderboard ({len(lb)} entries):")
        for e in lb:
            auc = "n/a" if e.auc is None else f"{e.auc:.3f}"
            print(f"  {e.target:22s} h={e.horizon_months:>2} {e.model_name:28s} "
                  f"AUC={auc} brier={e.brier_score:.3f} n={e.n_samples} pos={e.n_events}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
