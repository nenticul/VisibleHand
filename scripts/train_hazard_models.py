"""
Train crisis-hazard baselines, populate the leaderboard, and persist per-country
hazard predictions.

Trains a class-weighted logistic baseline per (target, horizon) with a temporal
train/test split (no future leakage) and logs both the logistic model and a
transparent heuristic baseline to the leaderboard for honest comparison.

Usage:
    python scripts/train_hazard_models.py --all
    python scripts/train_hazard_models.py --target currency_crisis --horizon 12 \
        --train-end 2018 --test-start 2019 --test-end 2023
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np

from api.models.database import (
    SessionLocal, Base, engine, CountryStateFeature, ModelLeaderboard,
    CrisisHazardPrediction,
)
from core.worldstate import registry as R
from core.worldstate import hazards as H
from core.worldstate.analogues import _build_outcome_index


def _load_rows(db):
    return (
        db.query(CountryStateFeature)
        .filter(CountryStateFeature.model_version == R.FEATURE_VERSION)
        .order_by(CountryStateFeature.as_of_date.asc())
        .all()
    )


def _row_vec(r):
    return [getattr(r, c) if getattr(r, c) is not None else np.nan
            for c in H.HAZARD_FEATURE_COLUMNS]


def _year(r):
    return int(r.as_of_date[:4])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--target", default=None)
    ap.add_argument("--horizon", type=int, default=12)
    ap.add_argument("--train-end", type=int, default=2018)
    ap.add_argument("--test-start", type=int, default=2019)
    ap.add_argument("--test-end", type=int, default=2023)
    args = ap.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        rows = _load_rows(db)
        if not rows:
            print("No feature rows. Run materialize_worldstate.py first.")
            return
        outcome_idx = _build_outcome_index()

        # historical rows only (exclude the live snapshot — no label horizon yet)
        hist_rows = [r for r in rows if r.as_of_date.endswith("-12-31")]

        targets = R.HAZARD_TARGETS if args.all else [args.target or "currency_crisis"]
        horizons = R.HORIZONS_MONTHS if args.all else [args.horizon]

        trained: dict[tuple[str, int], H.LogisticHazardModel] = {}
        db.query(ModelLeaderboard).delete()

        for target in targets:
            for horizon in horizons:
                X, y, yr = [], [], []
                for r in hist_rows:
                    lab = H.build_label(outcome_idx, r.country_code, _year(r), target, horizon)
                    if lab is None:
                        continue
                    X.append(_row_vec(r)); y.append(lab); yr.append(_year(r))
                if not X:
                    continue
                X = np.asarray(X, float); y = np.asarray(y, int); yr = np.asarray(yr, int)

                tr = yr <= args.train_end
                te = (yr >= args.test_start) & (yr <= args.test_end)
                n_pos_tr = int(y[tr].sum())

                # heuristic baseline on the test split (always logged)
                _log_heuristic(db, hist_rows, target, horizon, te, yr, y, args)

                if tr.sum() >= 10 and n_pos_tr >= 3 and te.sum() >= 5 and 0 < y[te].sum():
                    model = H.LogisticHazardModel()
                    model.fit(X[tr], y[tr])
                    p_te = model.predict_proba(X[te])
                    m = H.all_metrics(y[te], p_te)
                    db.add(ModelLeaderboard(
                        model_name=H.LogisticHazardModel.name,
                        model_version=H.LogisticHazardModel.version,
                        target=target, horizon_months=horizon,
                        auc=m["auc"], pr_auc=m["pr_auc"], brier_score=m["brier_score"],
                        calibration_error=m["calibration_error"], log_loss=m["log_loss"],
                        train_period=f"..{args.train_end}",
                        test_period=f"{args.test_start}..{args.test_end}",
                        n_samples=int(te.sum()), n_events=int(y[te].sum()),
                    ))
                    # retrain on all labelled history for serving
                    full = H.LogisticHazardModel(); full.fit(X, y)
                    full.save(os.path.join(R.HAZARD_ARTEFACT_DIR, f"{target}_{horizon}"))
                    trained[(target, horizon)] = full
                    auc = m["auc"]
                    print(f"  trained {target:22s} h={horizon:>2} "
                          f"AUC={auc if auc is None else round(auc,3)} "
                          f"n_test={int(te.sum())} pos={int(y[te].sum())}")
                else:
                    print(f"  skipped {target:22s} h={horizon:>2} "
                          f"(insufficient labels: train_pos={n_pos_tr}, test={int(te.sum())}) "
                          f"-> heuristic only")
        db.commit()

        # ── persist per-country latest predictions ─────────────────────────────
        latest = {}
        for r in rows:
            if r.country_code not in latest or r.as_of_date > latest[r.country_code].as_of_date:
                latest[r.country_code] = r

        n_pred = 0
        for code, r in latest.items():
            row_dict = {c.name: getattr(r, c.name) for c in r.__table__.columns}
            # Served probabilities use the heuristic: the benchmark shows the
            # class-weighted logistic is over-confident (high Brier) on this
            # sparse-label panel, so raw logistic probs are NOT served. The
            # logistic model is still trained and logged to the leaderboard for
            # honest AUC/discrimination comparison (see BENCHMARK_vh_wsm_0.1.md).
            heur = H.heuristic_hazards(row_dict, code=code)
            for horizon in R.HORIZONS_MONTHS:
                probs = dict(heur)
                db.query(CrisisHazardPrediction).filter(
                    CrisisHazardPrediction.country_code == code,
                    CrisisHazardPrediction.as_of_date == r.as_of_date,
                    CrisisHazardPrediction.horizon_months == horizon,
                    CrisisHazardPrediction.model_name == "vh-wsm-hazard-ensemble",
                    CrisisHazardPrediction.model_version == R.HAZARD_MODEL_VERSION,
                ).delete()
                db.add(CrisisHazardPrediction(
                    country_code=code, as_of_date=r.as_of_date, horizon_months=horizon,
                    sovereign_default_prob=probs["sovereign_default"],
                    currency_crisis_prob=probs["currency_crisis"],
                    imf_programme_prob=probs["imf_programme"],
                    banking_crisis_prob=probs["banking_crisis"],
                    civil_conflict_prob=probs["civil_conflict"],
                    coup_prob=probs["coup"],
                    sanctions_shock_prob=probs["sanctions_shock"],
                    political_instability_prob=probs["political_instability"],
                    model_name="vh-wsm-hazard-ensemble",
                    model_version=R.HAZARD_MODEL_VERSION,
                    calibration_status="heuristic",
                ))
                n_pred += 1
        db.commit()
        n_lb = db.query(ModelLeaderboard).count()
        print(f"Leaderboard entries: {n_lb}. Persisted {n_pred} hazard predictions "
              f"for {len(latest)} countries.")
    finally:
        db.close()


def _log_heuristic(db, hist_rows, target, horizon, te_mask, yr, y, args):
    from core.worldstate.analogues import _build_outcome_index  # noqa
    idx = 0
    X_te_rows = [r for r in hist_rows
                 if args.test_start <= int(r.as_of_date[:4]) <= args.test_end]
    if not X_te_rows:
        return
    outcome_idx = _build_outcome_index()
    p, yy = [], []
    for r in X_te_rows:
        lab = H.build_label(outcome_idx, r.country_code, int(r.as_of_date[:4]), target, horizon)
        if lab is None:
            return
        row_dict = {c.name: getattr(r, c.name) for c in r.__table__.columns}
        p.append(H.heuristic_hazards(row_dict, code=r.country_code)[target])
        yy.append(lab)
    p = np.asarray(p, float); yy = np.asarray(yy, int)
    if yy.sum() == 0:
        return
    m = H.all_metrics(yy, p)
    db.add(ModelLeaderboard(
        model_name="vh-wsm-hazard-heuristic", model_version=R.HAZARD_MODEL_VERSION,
        target=target, horizon_months=horizon,
        auc=m["auc"], pr_auc=m["pr_auc"], brier_score=m["brier_score"],
        calibration_error=m["calibration_error"], log_loss=m["log_loss"],
        train_period="n/a", test_period=f"{args.test_start}..{args.test_end}",
        n_samples=int(len(yy)), n_events=int(yy.sum()),
    ))


if __name__ == "__main__":
    main()
