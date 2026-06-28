"""
Materialise the VH-WSM feature store.

Builds the historical annual panel (leakage-safe proxies from indicators +
governance) and one "live" snapshot row per country (using the latest real
CountryScore), then fills deterministic spillover features per date.

Usage:
    python scripts/materialize_worldstate.py --date today --all
    python scripts/materialize_worldstate.py --date 2026-06-27 --countries AR TR PK
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.models.database import SessionLocal, Base, engine, CountryScore
from core.worldstate import registry as R
from core.worldstate import graph
from core.worldstate.features import CountryStateFeatureBuilder, persist_features


def _latest_scores(db, countries):
    out = {}
    for c in countries:
        s = (
            db.query(CountryScore)
            .filter(CountryScore.country_code == c)
            .order_by(CountryScore.computed_at.desc())
            .first()
        )
        if s is not None:
            out[c] = s
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="today", help="'today' or ISO YYYY-MM-DD")
    ap.add_argument("--countries", nargs="*", default=None)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    Base.metadata.create_all(bind=engine)
    live_date = date.today().isoformat() if args.date == "today" else args.date
    countries = R.UNIVERSE if (args.all or not args.countries) else [c.upper() for c in args.countries]

    db = SessionLocal()
    try:
        builder = CountryStateFeatureBuilder(db)
        latest = _latest_scores(db, countries)

        # Collect the union of historical year-end dates across countries.
        date_set = set()
        for c in countries:
            date_set.update(builder.historical_dates(c))
        hist_dates = sorted(date_set)

        total = 0
        # Historical panel (proxy scores, leakage-safe).
        for d in hist_dates:
            rows = [builder.build(c, d) for c in countries]
            graph.add_spillover(rows)
            total += persist_features(db, rows)

        # Live snapshot (real CountryScore where available).
        live_rows = [builder.build(c, live_date, source_score=latest.get(c)) for c in countries]
        graph.add_spillover(live_rows)
        total += persist_features(db, live_rows)

        print(f"Materialised {total} feature rows for {len(countries)} countries.")
        print(f"  historical dates: {hist_dates[0]} .. {hist_dates[-1]} ({len(hist_dates)} years)")
        print(f"  live snapshot:    {live_date}")
        print(f"  with-live-score:  {sum(1 for c in countries if c in latest)}/{len(countries)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
