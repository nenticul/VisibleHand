"""
Historical analogue search — the flagship VH-WSM feature.

Given a country-state embedding, find the most similar *past* country-states and
attach what happened next (6/12/18-month outcomes from the crisis dataset).

Leakage rules (enforced + unit-tested):
  * never return an analogue dated after the query date;
  * exclude the same country within ``min_date_gap_days`` of the query;
  * outcomes are looked up strictly after the analogue date.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from core.worldstate import registry as R


def _year(d: str) -> int:
    return int(d[:4])


def _days_between(a: str, b: str) -> int:
    da = datetime.strptime(a[:10], "%Y-%m-%d").date()
    db_ = datetime.strptime(b[:10], "%Y-%m-%d").date()
    return abs((da - db_).days)


# ── crisis outcome index ─────────────────────────────────────────────────────
def _build_outcome_index() -> dict[str, list[tuple[int, str]]]:
    """code → sorted [(year, crisis_type)] for label==1 events."""
    from core.calibration.crisis_dataset import ALL_EVENTS

    idx: dict[str, list[tuple[int, str]]] = {}
    for e in ALL_EVENTS:
        if e.label != 1:
            continue
        idx.setdefault(e.country, []).append((e.year, e.crisis_type))
    for c in idx:
        idx[c].sort()
    return idx


def _outcome(idx: dict, code: str, analogue_date: str, years_ahead: list[int]) -> Optional[str]:
    alias = R.aliased_for_crisis_dataset(code)
    y = _year(analogue_date)
    target_years = {y + a for a in years_ahead}
    for (ey, etype) in idx.get(alias, []):
        if ey in target_years:
            mapped = R.CRISIS_TYPE_TO_TARGET.get(etype, etype)
            return mapped
    return None


class AnalogueSearchService:
    def __init__(self, db: Session, embedding_version: str = R.EMBEDDING_VERSION):
        self.db = db
        self.embedding_version = embedding_version
        self._cache: Optional[list[tuple[str, str, np.ndarray]]] = None
        self._outcomes = _build_outcome_index()

    def _all_embeddings(self) -> list[tuple[str, str, np.ndarray]]:
        if self._cache is not None:
            return self._cache
        from api.models.database import CountryStateEmbedding

        rows = (
            self.db.query(CountryStateEmbedding)
            .filter(CountryStateEmbedding.embedding_version == self.embedding_version)
            .all()
        )
        out = []
        for r in rows:
            try:
                vec = np.asarray(json.loads(r.embedding), dtype=float)
            except Exception:
                continue
            out.append((r.country_code, r.as_of_date, vec))
        self._cache = out
        return out

    def find_analogues(
        self,
        country_code: str,
        as_of_date: str,
        k: int = 10,
        min_date_gap_days: int = 180,
        exclude_same_country_recent: bool = True,
    ) -> list[dict]:
        code = country_code.upper()
        embeddings = self._all_embeddings()

        query = next(
            (v for (c, d, v) in embeddings if c == code and d == as_of_date), None
        )
        if query is None:
            return []

        scored: list[tuple[float, str, str]] = []
        for (c, d, v) in embeddings:
            if c == code and d == as_of_date:
                continue
            if d > as_of_date:           # no future leakage
                continue
            if c == code and exclude_same_country_recent:
                if _days_between(d, as_of_date) < min_date_gap_days:
                    continue
            sim = float(np.dot(query, v))   # vectors are L2-normalised
            scored.append((sim, c, d))

        scored.sort(key=lambda t: t[0], reverse=True)
        results = []
        for rank, (sim, c, d) in enumerate(scored[:k], start=1):
            results.append({
                "rank": rank,
                "country": c,
                "date": d,
                "similarity": round(sim, 4),
                "outcome_6m": _outcome(self._outcomes, c, d, [1]),
                "outcome_12m": _outcome(self._outcomes, c, d, [1]),
                "outcome_18m": _outcome(self._outcomes, c, d, [1, 2]),
            })
        return results


def persist_analogues(db: Session, query_code: str, query_date: str,
                      analogues: list[dict], version: str = R.EMBEDDING_VERSION) -> int:
    from api.models.database import HistoricalAnalogue

    db.query(HistoricalAnalogue).filter(
        HistoricalAnalogue.query_country_code == query_code,
        HistoricalAnalogue.query_date == query_date,
        HistoricalAnalogue.embedding_version == version,
    ).delete()
    for a in analogues:
        db.add(HistoricalAnalogue(
            query_country_code=query_code, query_date=query_date,
            analogue_country_code=a["country"], analogue_date=a["date"],
            similarity=a["similarity"], rank=a["rank"],
            outcome_6m=a.get("outcome_6m"), outcome_12m=a.get("outcome_12m"),
            outcome_18m=a.get("outcome_18m"), embedding_version=version,
        ))
    db.commit()
    return len(analogues)
