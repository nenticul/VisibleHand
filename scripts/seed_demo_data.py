"""
Seed the database with realistic demo data so the API works immediately
without waiting for live ingestion pipelines.

Run once after `alembic upgrade head`:
    python -m scripts.seed_demo_data

Coverage: 44 countries across every region (G20 + major emerging markets +
crisis states). The eight "showcase" countries (US, BR, DE, AR, UA, IN, ZA, NG)
carry fully hand-curated time series plus political events and central-bank
statements. The remaining 36 "breadth" countries are generated from curated
real-world anchor points (start level, recent level, and pinned crisis/COVID
years) via deterministic interpolation — appropriate for clearly-labelled
`source="seed"` demo data and stable across runs.
"""

import sys
import os
import math
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, timedelta, datetime, timezone
from api.models.database import (
    SessionLocal, Base, engine, Indicator, PoliticalEvent,
    CentralBankStatement, GovernanceIndicator, CountryScore,
)


# ── Series generators (deterministic — stable across runs) ────────────────────

def S(s: float, e: float, anchors: dict[int, float] | None = None, w: float = 0.0):
    """Economic series 2013-2023 ramping s->e, with optional {year: value}
    anchors (to pin COVID dips / crisis spikes) and a deterministic wobble."""
    y0, y1 = 2013, 2023
    n = y1 - y0
    out = []
    for i, y in enumerate(range(y0, y1 + 1)):
        if anchors and y in anchors:
            out.append((y, float(anchors[y])))
            continue
        base = s + (e - s) * i / n
        out.append((y, round(base + w * math.sin(i * 1.7), 2)))
    return out


def G(s: float, e: float):
    """Governance series 2018-2023 ramping s->e (slow-moving institutional data)."""
    y0, y1 = 2018, 2023
    n = y1 - y0
    return [(y, round(s + (e - s) * i / n, 3)) for i, y in enumerate(range(y0, y1 + 1))]


def GOV(rs, re_, cs, ce, js, je, ts, te, ws, we, fhp, fhc):
    """Compact governance spec → seven-metric dict.
    rule, corruption-control, judicial-constraints, TI-CPI, WJP, FH(pol), FH(civ)."""
    return {
        "v2x_rule": G(rs, re_),
        "v2x_corr": G(cs, ce),
        "v2x_jucon": G(js, je),
        "ti_cpi": G(ts, te),
        "wjp_rule_of_law": G(ws, we),
        "fh_political": G(fhp, fhp),
        "fh_civil": G(fhc, fhc),
    }


# ── Economic indicators (10-indicator V3 set) ────────────────────────────────
# Showcase countries: fully hand-curated real series.

INDICATORS: dict[str, dict[str, list[tuple[int, float]]]] = {
    "US": {
        "gdp_growth":   [(y, v) for y, v in zip(range(2013, 2024), [2.6,2.5,3.1,2.3,2.3,2.9,2.3,-2.8,5.9,2.1,2.5])],
        "inflation":    [(y, v) for y, v in zip(range(2013, 2024), [1.5,1.6,0.1,1.3,2.1,2.4,1.8,1.2,4.7,8.0,4.1])],
        "debt_to_gdp":  [(y, v) for y, v in zip(range(2013, 2024), [103,104,104,106,107,106,107,127,127,121,120])],
        "fx_reserves":  [(y, v) for y, v in zip(range(2013, 2024), [2.1,2.0,1.9,1.8,1.8,2.0,2.2,1.9,2.1,2.3,2.4])],
        "current_account": [(y, v) for y, v in zip(range(2013, 2024), [-2.1,-2.1,-2.2,-2.3,-2.3,-2.1,-2.2,-3.1,-3.6,-3.8,-3.0])],
        "unemployment": [(y, v) for y, v in zip(range(2013, 2024), [7.4,6.2,5.3,4.9,4.4,3.9,3.5,8.1,5.4,3.6,3.4])],
        "bank_npl":     [(y, v) for y, v in zip(range(2015, 2024), [1.5,1.3,1.1,0.9,0.9,0.8,0.9,0.8,0.7])],
        "tax_revenue":  [(y, v) for y, v in zip(range(2013, 2024), [16.8,17.1,17.6,17.2,17.2,17.4,16.3,16.2,17.7,17.5,17.9])],
        "remittances":  [(y, v) for y, v in zip(range(2013, 2024), [0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1])],
    },
    "BR": {
        "gdp_growth":   [(y, v) for y, v in zip(range(2013, 2024), [3.0,0.5,-3.5,-3.3,1.3,1.8,1.4,-4.1,5.0,3.1,2.9])],
        "inflation":    [(y, v) for y, v in zip(range(2013, 2024), [6.2,6.3,9.0,8.7,3.4,3.7,4.3,3.2,8.3,9.3,5.1])],
        "debt_to_gdp":  [(y, v) for y, v in zip(range(2013, 2024), [60,62,66,70,74,74,78,89,88,88,88])],
        "fx_reserves":  [(y, v) for y, v in zip(range(2013, 2024), [14,14,15,14,12,12,14,16,15,14,13])],
        "current_account": [(y, v) for y, v in zip(range(2013, 2024), [-3.6,-4.2,-3.0,-1.3,-0.5,-0.8,-2.7,-1.7,-2.7,-2.9,-1.4])],
        "unemployment": [(y, v) for y, v in zip(range(2013, 2024), [7.1,6.8,8.3,11.2,12.7,12.3,11.9,13.5,13.2,9.3,7.9])],
        "bank_npl":     [(y, v) for y, v in zip(range(2015, 2024), [3.5,3.9,3.6,3.1,3.0,3.1,2.5,2.4,3.0])],
        "tax_revenue":  [(y, v) for y, v in zip(range(2013, 2024), [22.0,22.2,21.0,21.5,21.4,20.8,19.9,19.6,21.1,22.4,21.7])],
        "remittances":  [(y, v) for y, v in zip(range(2013, 2024), [0.1,0.1,0.1,0.2,0.2,0.2,0.3,0.3,0.3,0.3,0.4])],
    },
    "DE": {
        "gdp_growth":   [(y, v) for y, v in zip(range(2013, 2024), [0.4,2.2,1.5,2.2,2.9,1.5,0.6,-4.6,2.9,1.8,-0.3])],
        "inflation":    [(y, v) for y, v in zip(range(2013, 2024), [1.6,0.8,0.1,0.4,1.7,1.9,1.4,0.4,3.2,8.7,5.9])],
        "debt_to_gdp":  [(y, v) for y, v in zip(range(2013, 2024), [77,75,71,68,65,61,58,68,70,67,64])],
        "fx_reserves":  [(y, v) for y, v in zip(range(2013, 2024), [5.2,5.0,5.1,5.3,5.5,5.4,5.6,5.1,5.3,5.0,5.1])],
        "current_account": [(y, v) for y, v in zip(range(2013, 2024), [6.7,7.3,8.5,8.5,7.9,7.9,7.5,6.9,8.6,4.2,5.7])],
        "unemployment": [(y, v) for y, v in zip(range(2013, 2024), [5.2,5.0,4.6,4.2,3.8,3.4,3.0,3.8,3.6,3.0,2.9])],
        "bank_npl":     [(y, v) for y, v in zip(range(2015, 2024), [2.2,1.9,1.6,1.5,1.3,1.3,1.1,1.2,1.5])],
        "tax_revenue":  [(y, v) for y, v in zip(range(2013, 2024), [22.8,22.8,23.2,23.4,23.2,23.4,23.8,22.5,23.1,23.2,23.2])],
        "remittances":  [(y, v) for y, v in zip(range(2013, 2024), [0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5])],
    },
    "AR": {
        "gdp_growth":   [(y, v) for y, v in zip(range(2013, 2024), [2.4,-2.5,2.7,-1.8,2.8,-2.6,-2.1,10.4,5.0,5.2,-1.6])],
        "inflation":    [(y, v) for y, v in zip(range(2013, 2024), [10.6,23.9,26.9,41.0,24.8,34.3,53.5,42.0,48.4,94.8,211.4])],
        "debt_to_gdp":  [(y, v) for y, v in zip(range(2013, 2024), [39,43,52,53,57,57,86,103,80,84,89])],
        "fx_reserves":  [(y, v) for y, v in zip(range(2013, 2024), [6.5,5.4,5.2,4.1,4.3,3.6,2.0,4.6,3.1,1.8,1.4])],
        "current_account": [(y, v) for y, v in zip(range(2013, 2024), [-2.1,-1.5,-2.7,-2.7,-4.8,-4.9,0.9,0.7,-1.4,-0.3,0.5])],
        "unemployment": [(y, v) for y, v in zip(range(2013, 2024), [7.1,7.3,6.6,8.5,8.4,9.2,9.8,11.6,8.7,6.8,6.2])],
        "bank_npl":     [(y, v) for y, v in zip(range(2015, 2024), [1.6,1.7,2.1,3.2,4.2,4.0,3.4,2.8,3.5])],
        "tax_revenue":  [(y, v) for y, v in zip(range(2013, 2024), [23.5,22.9,22.5,22.0,22.4,21.5,22.9,23.7,23.7,22.2,19.5])],
        "remittances":  [(y, v) for y, v in zip(range(2013, 2024), [0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2])],
    },
    "UA": {
        "gdp_growth":   [(y, v) for y, v in zip(range(2013, 2024), [0.0,-6.6,-9.8,2.4,2.5,3.4,-4.0,3.4,3.3,-29.1,5.3])],
        "inflation":    [(y, v) for y, v in zip(range(2013, 2024), [-0.3,12.1,48.7,13.9,14.4,10.9,7.9,2.7,9.3,20.2,12.9])],
        "debt_to_gdp":  [(y, v) for y, v in zip(range(2013, 2024), [40,70,79,81,80,71,60,60,50,78,84])],
        "fx_reserves":  [(y, v) for y, v in zip(range(2013, 2024), [2.3,1.3,1.1,2.7,3.1,3.3,4.3,5.0,4.0,4.1,4.4])],
        "current_account": [(y, v) for y, v in zip(range(2013, 2024), [-9.2,-3.4,1.6,-1.5,-2.2,-2.2,-2.7,3.4,-1.9,5.3,4.8])],
        "unemployment": [(y, v) for y, v in zip(range(2013, 2024), [7.7,9.3,9.1,9.3,9.5,8.6,8.2,9.5,10.0,19.0,14.7])],
        "bank_npl":     [(y, v) for y, v in zip(range(2015, 2024), [28.0,30.5,54.5,55.0,52.9,48.4,41.5,36.2,38.0])],
        "tax_revenue":  [(y, v) for y, v in zip(range(2013, 2024), [26.8,25.4,26.7,25.5,26.5,27.6,28.4,27.9,30.0,33.7,32.1])],
        "remittances":  [(y, v) for y, v in zip(range(2013, 2024), [5.0,5.2,5.5,5.4,5.4,5.5,5.7,5.5,5.8,5.9,8.0])],
    },
    "IN": {
        "gdp_growth":   [(y, v) for y, v in zip(range(2013, 2024), [6.4,7.4,8.0,8.3,6.8,6.5,3.9,-6.6,8.9,7.0,8.2])],
        "inflation":    [(y, v) for y, v in zip(range(2013, 2024), [10.9,6.7,4.9,4.5,3.6,3.4,7.4,5.5,5.5,6.7,5.4])],
        "debt_to_gdp":  [(y, v) for y, v in zip(range(2013, 2024), [67,67,69,69,70,70,72,89,84,81,82])],
        "fx_reserves":  [(y, v) for y, v in zip(range(2013, 2024), [7.1,8.0,7.2,8.1,9.0,10.0,11.8,14.1,13.1,10.7,11.5])],
        "current_account": [(y, v) for y, v in zip(range(2013, 2024), [-1.7,-1.3,-1.0,-0.6,-1.8,-1.8,-0.9,0.9,-1.2,-2.0,-1.0])],
        "unemployment": [(y, v) for y, v in zip(range(2013, 2024), [4.0,3.8,3.5,3.5,3.5,3.5,5.4,7.1,5.9,3.6,3.1])],
        "bank_npl":     [(y, v) for y, v in zip(range(2015, 2024), [7.2,9.2,9.6,10.4,9.1,7.5,6.0,5.2,3.9])],
        "tax_revenue":  [(y, v) for y, v in zip(range(2013, 2024), [8.8,8.8,9.0,9.3,9.4,10.2,10.7,10.3,11.5,11.7,11.8])],
        "remittances":  [(y, v) for y, v in zip(range(2013, 2024), [3.5,3.2,3.1,2.9,2.8,2.9,2.9,3.1,2.8,3.0,3.3])],
    },
    "ZA": {
        "gdp_growth":   [(y, v) for y, v in zip(range(2013, 2024), [2.5,1.8,1.2,0.7,1.3,0.8,0.1,-6.3,4.9,1.9,0.7])],
        "inflation":    [(y, v) for y, v in zip(range(2013, 2024), [5.7,6.1,4.6,6.3,5.3,4.6,4.1,3.3,4.5,6.9,5.9])],
        "debt_to_gdp":  [(y, v) for y, v in zip(range(2013, 2024), [45,47,49,53,57,57,57,77,70,71,73])],
        "fx_reserves":  [(y, v) for y, v in zip(range(2013, 2024), [4.4,4.2,4.8,5.0,4.7,4.8,5.4,5.3,4.5,4.0,3.8])],
        "current_account": [(y, v) for y, v in zip(range(2013, 2024), [-5.8,-5.4,-4.6,-2.9,-2.5,-3.5,-3.0,2.0,3.7,-0.5,-1.7])],
        "unemployment": [(y, v) for y, v in zip(range(2013, 2024), [24.7,25.1,25.4,26.7,27.5,27.2,28.5,32.5,34.4,33.5,32.9])],
        "bank_npl":     [(y, v) for y, v in zip(range(2015, 2024), [3.3,3.1,2.8,2.8,3.2,4.0,4.4,4.2,4.9])],
        "tax_revenue":  [(y, v) for y, v in zip(range(2013, 2024), [25.7,26.5,26.3,26.0,26.3,26.0,26.0,23.3,25.0,25.4,24.8])],
        "remittances":  [(y, v) for y, v in zip(range(2013, 2024), [0.3,0.4,0.4,0.4,0.4,0.4,0.4,0.5,0.5,0.5,0.6])],
    },
    "NG": {
        "gdp_growth":   [(y, v) for y, v in zip(range(2013, 2024), [5.4,6.3,2.7,-1.6,0.8,1.9,2.2,-1.8,3.4,3.3,2.9])],
        "inflation":    [(y, v) for y, v in zip(range(2013, 2024), [8.5,8.1,9.0,15.7,16.5,12.1,11.4,13.2,16.0,18.9,24.7])],
        "debt_to_gdp":  [(y, v) for y, v in zip(range(2013, 2024), [11,12,13,18,22,25,29,35,37,38,42])],
        "fx_reserves":  [(y, v) for y, v in zip(range(2013, 2024), [5.2,5.0,4.9,3.3,4.6,5.0,5.4,4.9,4.5,3.9,3.4])],
        "current_account": [(y, v) for y, v in zip(range(2013, 2024), [3.7,0.2,-3.2,-0.7,2.5,2.0,-3.9,-4.1,-0.4,-0.1,0.3])],
        "unemployment": [(y, v) for y, v in zip(range(2013, 2024), [7.5,7.8,9.9,13.4,14.2,23.1,23.1,33.3,32.5,4.1,4.2])],
        "bank_npl":     [(y, v) for y, v in zip(range(2015, 2024), [5.3,11.7,14.8,12.4,9.3,7.4,5.4,4.2,4.6])],
        "tax_revenue":  [(y, v) for y, v in zip(range(2013, 2024), [3.5,3.1,3.2,3.0,3.0,3.1,3.6,3.1,4.1,5.6,5.3])],
        "remittances":  [(y, v) for y, v in zip(range(2013, 2024), [4.4,3.7,3.7,4.7,5.5,6.3,5.7,4.3,4.0,3.3,3.9])],
    },
}

# Breadth countries: generated from curated real-world anchors.
INDICATORS.update({
    # ── G20 / major advanced economies ──
    "CN": {
        "gdp_growth":   S(7.8, 5.2, {2020: 2.2, 2021: 8.4}, w=0.4),
        "inflation":    S(2.6, 0.2, {2020: 2.5}, w=0.3),
        "debt_to_gdp":  S(38, 83),
        "fx_reserves":  S(16, 12),
        "current_account": S(1.5, 1.5, w=0.6),
        "unemployment": S(4.6, 5.2, {2020: 5.6}),
        "bank_npl":     S(1.0, 1.6),
        "tax_revenue":  S(18, 17),
        "remittances":  S(0.2, 0.1),
    },
    "JP": {
        "gdp_growth":   S(2.0, 1.9, {2020: -4.2, 2021: 2.6}, w=0.5),
        "inflation":    S(0.4, 3.3, {2020: 0.0}, w=0.4),
        "debt_to_gdp":  S(230, 255),
        "fx_reserves":  S(14, 13),
        "current_account": S(0.9, 3.5),
        "unemployment": S(4.0, 2.6),
        "bank_npl":     S(1.5, 1.1),
        "tax_revenue":  S(11, 12),
        "remittances":  S(0.1, 0.1),
    },
    "GB": {
        "gdp_growth":   S(2.0, 0.1, {2020: -10.4, 2021: 8.7}, w=0.5),
        "inflation":    S(2.6, 7.3, {2022: 9.1}, w=0.4),
        "debt_to_gdp":  S(84, 100),
        "fx_reserves":  S(3, 4),
        "current_account": S(-5.5, -3.3),
        "unemployment": S(7.6, 4.0),
        "bank_npl":     S(3.1, 1.0),
        "tax_revenue":  S(25, 27),
        "remittances":  S(0.1, 0.1),
    },
    "FR": {
        "gdp_growth":   S(0.6, 0.9, {2020: -7.5, 2021: 6.4}, w=0.5),
        "inflation":    S(1.0, 4.9, {2022: 5.2}, w=0.4),
        "debt_to_gdp":  S(93, 110),
        "fx_reserves":  S(4, 5),
        "current_account": S(-0.9, -1.7),
        "unemployment": S(10.3, 7.3),
        "bank_npl":     S(4.5, 2.0),
        "tax_revenue":  S(45, 46),
        "remittances":  S(0.4, 0.4),
    },
    "IT": {
        "gdp_growth":   S(-1.8, 0.9, {2020: -9.0, 2021: 7.0}, w=0.5),
        "inflation":    S(1.2, 5.9, {2022: 8.7}, w=0.4),
        "debt_to_gdp":  S(129, 137),
        "fx_reserves":  S(4, 5),
        "current_account": S(0.9, 0.5),
        "unemployment": S(12.1, 7.7),
        "bank_npl":     S(16.5, 2.7),
        "tax_revenue":  S(43, 43),
        "remittances":  S(0.4, 0.4),
    },
    "CA": {
        "gdp_growth":   S(2.3, 1.1, {2020: -5.0, 2021: 5.3}, w=0.5),
        "inflation":    S(0.9, 3.9, {2022: 6.8}, w=0.4),
        "debt_to_gdp":  S(86, 106),
        "fx_reserves":  S(2, 3),
        "current_account": S(-3.2, -0.7),
        "unemployment": S(7.1, 5.4),
        "bank_npl":     S(0.6, 0.5),
        "tax_revenue":  S(38, 39),
        "remittances":  S(0.1, 0.1),
    },
    "KR": {
        "gdp_growth":   S(3.2, 1.4, {2020: -0.7, 2021: 4.3}, w=0.4),
        "inflation":    S(1.3, 3.6, {2022: 5.1}, w=0.4),
        "debt_to_gdp":  S(38, 55),
        "fx_reserves":  S(9, 8),
        "current_account": S(5.6, 1.8),
        "unemployment": S(3.1, 2.7),
        "bank_npl":     S(1.7, 0.4),
        "tax_revenue":  S(18, 22),
        "remittances":  S(0.5, 0.5),
    },
    "MX": {
        "gdp_growth":   S(1.4, 3.2, {2020: -8.0, 2021: 5.7}, w=0.5),
        "inflation":    S(3.8, 5.5, {2022: 7.9}, w=0.4),
        "debt_to_gdp":  S(46, 53),
        "fx_reserves":  S(4, 5),
        "current_account": S(-2.4, -0.3),
        "unemployment": S(4.9, 2.8),
        "bank_npl":     S(3.4, 2.1),
        "tax_revenue":  S(13, 17),
        "remittances":  S(1.8, 4.2),
    },
    "RU": {
        "gdp_growth":   S(1.8, 3.6, {2020: -2.7, 2022: -1.2}, w=0.5),
        "inflation":    S(6.8, 5.9, {2022: 13.8}, w=0.5),
        "debt_to_gdp":  S(13, 19),
        "fx_reserves":  S(12, 14),
        "current_account": S(1.5, 2.5, {2022: 10.5}),
        "unemployment": S(5.5, 3.2),
        "bank_npl":     S(6.0, 4.0),
        "tax_revenue":  S(18, 16),
        "remittances":  S(0.4, 0.3),
    },
    "AU": {
        "gdp_growth":   S(2.6, 2.0, {2020: -2.1, 2021: 5.5}, w=0.4),
        "inflation":    S(2.5, 5.6, {2022: 6.6}, w=0.4),
        "debt_to_gdp":  S(31, 50),
        "fx_reserves":  S(2, 3),
        "current_account": S(-3.4, 1.2),
        "unemployment": S(5.7, 3.7),
        "bank_npl":     S(1.1, 0.9),
        "tax_revenue":  S(23, 24),
        "remittances":  S(0.2, 0.2),
    },
    "ID": {
        "gdp_growth":   S(5.6, 5.0, {2020: -2.1, 2021: 3.7}, w=0.3),
        "inflation":    S(6.4, 3.7, {2022: 4.2}, w=0.4),
        "debt_to_gdp":  S(25, 39),
        "fx_reserves":  S(6, 6),
        "current_account": S(-3.2, -0.1),
        "unemployment": S(6.2, 5.3),
        "bank_npl":     S(1.8, 2.3),
        "tax_revenue":  S(11, 12),
        "remittances":  S(1.0, 0.7),
    },
    "TR": {
        "gdp_growth":   S(8.5, 4.5, {2020: 1.9, 2021: 11.4}, w=0.6),
        "inflation":    S(7.5, 53.9, {2022: 72.3}, w=0.8),
        "debt_to_gdp":  S(31, 34),
        "fx_reserves":  S(5, 4),
        "current_account": S(-6.7, -4.0),
        "unemployment": S(9.0, 9.4),
        "bank_npl":     S(2.7, 1.6),
        "tax_revenue":  S(20, 23),
        "remittances":  S(0.1, 0.1),
    },
    "SA": {
        "gdp_growth":   S(2.7, -0.8, {2020: -4.3, 2021: 3.9, 2022: 8.7}, w=0.5),
        "inflation":    S(3.5, 2.3, w=0.4),
        "debt_to_gdp":  S(2, 24),
        "fx_reserves":  S(30, 16),
        "current_account": S(18, 3, {2022: 13.7}),
        "unemployment": S(5.6, 4.9),
        "bank_npl":     S(1.3, 1.6),
        "tax_revenue":  S(4, 9),
        "remittances":  S(0.0, 0.0),
    },
    # ── Europe ──
    "PL": {
        "gdp_growth":   S(1.4, 0.2, {2020: -2.0, 2021: 6.9}, w=0.5),
        "inflation":    S(0.9, 11.4, {2022: 14.4}, w=0.5),
        "debt_to_gdp":  S(56, 49),
        "fx_reserves":  S(4, 5),
        "current_account": S(-1.3, 1.6),
        "unemployment": S(10.3, 2.8),
        "bank_npl":     S(4.5, 3.5),
        "tax_revenue":  S(32, 36),
        "remittances":  S(1.2, 1.5),
    },
    "ES": {
        "gdp_growth":   S(-1.4, 2.5, {2020: -11.2, 2021: 6.4}, w=0.5),
        "inflation":    S(1.5, 3.4, {2022: 8.4}, w=0.4),
        "debt_to_gdp":  S(95, 108),
        "fx_reserves":  S(3, 4),
        "current_account": S(1.5, 2.6),
        "unemployment": S(26.1, 12.1),
        "bank_npl":     S(9.4, 3.5),
        "tax_revenue":  S(37, 39),
        "remittances":  S(0.6, 0.6),
    },
    "GR": {
        "gdp_growth":   S(-3.2, 2.0, {2020: -9.0, 2021: 8.4}, w=0.5),
        "inflation":    S(-0.9, 4.2, {2022: 9.3}, w=0.4),
        "debt_to_gdp":  S(178, 168),
        "fx_reserves":  S(2, 3),
        "current_account": S(-2.0, -6.3, {2022: -10.3}),
        "unemployment": S(27.5, 11.1),
        "bank_npl":     S(31.9, 6.0),
        "tax_revenue":  S(38, 43),
        "remittances":  S(0.3, 0.3),
    },
    "NL": {
        "gdp_growth":   S(-0.1, 0.1, {2020: -3.9, 2021: 6.2}, w=0.4),
        "inflation":    S(2.6, 4.1, {2022: 11.6}, w=0.5),
        "debt_to_gdp":  S(67, 46),
        "fx_reserves":  S(3, 4),
        "current_account": S(10, 9),
        "unemployment": S(7.3, 3.6),
        "bank_npl":     S(3.2, 1.6),
        "tax_revenue":  S(38, 39),
        "remittances":  S(0.2, 0.2),
    },
    "HU": {
        "gdp_growth":   S(2.0, -0.9, {2020: -4.5, 2021: 7.1}, w=0.5),
        "inflation":    S(1.7, 17.1, {2022: 14.5}, w=0.6),
        "debt_to_gdp":  S(77, 73),
        "fx_reserves":  S(4, 3),
        "current_account": S(3.8, 0.2, {2022: -8.5}),
        "unemployment": S(10.2, 4.1),
        "bank_npl":     S(17.0, 3.0),
        "tax_revenue":  S(38, 34),
        "remittances":  S(3.0, 3.0),
    },
    "CH": {
        "gdp_growth":   S(1.9, 0.8, {2020: -2.3, 2021: 5.4}, w=0.4),
        "inflation":    S(-0.2, 2.1, {2022: 2.8}, w=0.3),
        "debt_to_gdp":  S(43, 38),
        "fx_reserves":  S(60, 50),
        "current_account": S(11, 8),
        "unemployment": S(4.5, 4.0),
        "bank_npl":     S(0.7, 0.6),
        "tax_revenue":  S(27, 28),
        "remittances":  S(0.4, 0.4),
    },
    # ── Latin America ──
    "CO": {
        "gdp_growth":   S(5.1, 0.6, {2020: -7.0, 2021: 10.8}, w=0.5),
        "inflation":    S(2.0, 11.7, {2022: 10.2}, w=0.5),
        "debt_to_gdp":  S(38, 55),
        "fx_reserves":  S(7, 9),
        "current_account": S(-3.2, -2.5, {2022: -6.2}),
        "unemployment": S(9.7, 10.2),
        "bank_npl":     S(2.8, 4.5),
        "tax_revenue":  S(14, 16),
        "remittances":  S(1.2, 2.5),
    },
    "CL": {
        "gdp_growth":   S(4.0, 0.2, {2020: -6.1, 2021: 11.7}, w=0.5),
        "inflation":    S(1.8, 7.6, {2022: 11.6}, w=0.4),
        "debt_to_gdp":  S(12, 38),
        "fx_reserves":  S(5, 6),
        "current_account": S(-4.0, -3.5, {2022: -9.0}),
        "unemployment": S(5.9, 8.5),
        "bank_npl":     S(2.1, 1.8),
        "tax_revenue":  S(18, 20),
        "remittances":  S(0.1, 0.1),
    },
    "PE": {
        "gdp_growth":   S(5.8, -0.6, {2020: -11.0, 2021: 13.4}, w=0.5),
        "inflation":    S(2.8, 6.3, {2022: 7.9}, w=0.4),
        "debt_to_gdp":  S(19, 33),
        "fx_reserves":  S(14, 14),
        "current_account": S(-4.7, 0.6),
        "unemployment": S(5.9, 6.8),
        "bank_npl":     S(2.5, 4.0),
        "tax_revenue":  S(16, 15),
        "remittances":  S(1.4, 1.5),
    },
    "VE": {
        "gdp_growth":   S(1.3, 4.0, {2017: -15.7, 2018: -19.6, 2019: -27.7, 2020: -30.0, 2021: 1.0}),
        "inflation":    S(40, 190, {2018: 65000, 2019: 19900, 2020: 2360, 2021: 1589, 2022: 186}),
        "debt_to_gdp":  S(60, 160, {2020: 300}),
        "fx_reserves":  S(3, 1),
        "current_account": S(2, 5),
        "unemployment": S(7.5, 5.5, {2019: 35}),
        "bank_npl":     S(1.0, 2.0),
        "tax_revenue":  S(14, 6),
        "remittances":  S(0.0, 4.0),
    },
    # ── Middle East / North Africa ──
    "EG": {
        "gdp_growth":   S(2.2, 3.8, {2020: 3.6, 2021: 3.3}, w=0.4),
        "inflation":    S(9.0, 24.4, {2017: 29.5, 2023: 33.9}, w=0.6),
        "debt_to_gdp":  S(84, 93, {2017: 103}),
        "fx_reserves":  S(3, 3),
        "current_account": S(-2.4, -1.2),
        "unemployment": S(13.0, 7.0),
        "bank_npl":     S(8.5, 3.4),
        "tax_revenue":  S(13, 12),
        "remittances":  S(6.0, 6.0),
    },
    "MA": {
        "gdp_growth":   S(4.5, 3.0, {2020: -7.2, 2021: 8.0}, w=0.4),
        "inflation":    S(1.9, 6.1, {2022: 6.6}, w=0.4),
        "debt_to_gdp":  S(61, 70),
        "fx_reserves":  S(5, 6),
        "current_account": S(-7.6, -1.5),
        "unemployment": S(9.2, 11.8),
        "bank_npl":     S(6.0, 8.5),
        "tax_revenue":  S(22, 23),
        "remittances":  S(6.5, 8.0),
    },
    "LB": {
        "gdp_growth":   S(3.0, -0.5, {2019: -6.9, 2020: -21.4, 2021: -10.0, 2022: -2.6}),
        "inflation":    S(3.0, 221, {2020: 84.9, 2021: 154.8, 2022: 171.2}),
        "debt_to_gdp":  S(140, 280, {2021: 283}),
        "fx_reserves":  S(6, 1),
        "current_account": S(-25, -25, {2022: -28}),
        "unemployment": S(6.5, 29),
        "bank_npl":     S(3.7, 25),
        "tax_revenue":  S(15, 6),
        "remittances":  S(13, 30),
    },
    # ── Sub-Saharan Africa ──
    "KE": {
        "gdp_growth":   S(5.9, 5.0, {2020: -0.3, 2021: 7.6}, w=0.4),
        "inflation":    S(5.7, 7.7, {2017: 8.0}, w=0.4),
        "debt_to_gdp":  S(41, 70),
        "fx_reserves":  S(4, 4),
        "current_account": S(-8.8, -4.0),
        "unemployment": S(5.0, 5.5),
        "bank_npl":     S(5.0, 14.0),
        "tax_revenue":  S(16, 14),
        "remittances":  S(2.9, 3.3),
    },
    "ET": {
        "gdp_growth":   S(10.6, 7.2, {2020: 6.1, 2021: 6.3}, w=0.5),
        "inflation":    S(8.5, 30.2, {2022: 33.9}, w=0.6),
        "debt_to_gdp":  S(45, 38),
        "fx_reserves":  S(2, 1),
        "current_account": S(-5.8, -3.0),
        "unemployment": S(5.2, 3.5),
        "bank_npl":     S(3.0, 4.0),
        "tax_revenue":  S(12, 7),
        "remittances":  S(1.5, 0.5),
    },
    "GH": {
        "gdp_growth":   S(7.3, 2.9, {2020: 0.5, 2021: 5.1}, w=0.5),
        "inflation":    S(11.7, 38.1, {2022: 31.9}, w=0.6),
        "debt_to_gdp":  S(43, 85, {2022: 93}),
        "fx_reserves":  S(3, 2),
        "current_account": S(-11.7, -2.0),
        "unemployment": S(5.0, 4.7),
        "bank_npl":     S(12.0, 18.0),
        "tax_revenue":  S(14, 13),
        "remittances":  S(4.0, 6.0),
    },
    # ── South / Southeast Asia ──
    "PK": {
        "gdp_growth":   S(4.4, -0.2, {2020: -0.9, 2021: 5.8, 2022: 6.2}, w=0.4),
        "inflation":    S(7.4, 29.2, {2023: 29.2}, w=0.6),
        "debt_to_gdp":  S(64, 77),
        "fx_reserves":  S(2, 1),
        "current_account": S(-1.1, -0.7, {2022: -4.7}),
        "unemployment": S(6.0, 8.5),
        "bank_npl":     S(13.0, 7.4),
        "tax_revenue":  S(11, 10),
        "remittances":  S(6.3, 7.5),
    },
    "BD": {
        "gdp_growth":   S(6.0, 5.8, {2020: 3.4, 2021: 6.9}, w=0.4),
        "inflation":    S(7.5, 9.0, w=0.4),
        "debt_to_gdp":  S(30, 42),
        "fx_reserves":  S(5, 4),
        "current_account": S(1.2, -1.0, {2022: -4.1}),
        "unemployment": S(4.4, 5.0),
        "bank_npl":     S(8.9, 9.0),
        "tax_revenue":  S(9, 8),
        "remittances":  S(8.0, 5.0),
    },
    "VN": {
        "gdp_growth":   S(5.4, 5.0, {2020: 2.9, 2021: 2.6}, w=0.4),
        "inflation":    S(6.6, 3.3, w=0.4),
        "debt_to_gdp":  S(42, 37),
        "fx_reserves":  S(2, 3),
        "current_account": S(4.5, 1.0),
        "unemployment": S(2.0, 2.3),
        "bank_npl":     S(3.4, 2.0),
        "tax_revenue":  S(18, 16),
        "remittances":  S(6.5, 4.5),
    },
    "PH": {
        "gdp_growth":   S(6.8, 5.6, {2020: -9.5, 2021: 5.7}, w=0.4),
        "inflation":    S(2.9, 6.0, {2023: 6.0}, w=0.4),
        "debt_to_gdp":  S(39, 57),
        "fx_reserves":  S(8, 7),
        "current_account": S(4.2, -2.5),
        "unemployment": S(7.1, 4.5),
        "bank_npl":     S(2.4, 3.4),
        "tax_revenue":  S(14, 15),
        "remittances":  S(9.8, 8.5),
    },
    "TH": {
        "gdp_growth":   S(2.7, 1.9, {2020: -6.1, 2021: 1.5}, w=0.4),
        "inflation":    S(2.2, 1.2, {2022: 6.1}, w=0.4),
        "debt_to_gdp":  S(42, 62),
        "fx_reserves":  S(8, 9),
        "current_account": S(-1.2, 1.4, {2022: -3.2}),
        "unemployment": S(0.7, 1.0),
        "bank_npl":     S(2.2, 2.7),
        "tax_revenue":  S(17, 16),
        "remittances":  S(1.5, 1.2),
    },
    "MY": {
        "gdp_growth":   S(4.7, 3.7, {2020: -5.5, 2021: 3.3}, w=0.4),
        "inflation":    S(2.1, 2.5, {2022: 3.4}, w=0.3),
        "debt_to_gdp":  S(53, 66),
        "fx_reserves":  S(5, 5),
        "current_account": S(3.5, 1.2),
        "unemployment": S(3.1, 3.4),
        "bank_npl":     S(1.8, 1.6),
        "tax_revenue":  S(16, 12),
        "remittances":  S(0.4, 0.4),
    },
    "LK": {
        "gdp_growth":   S(3.4, -2.3, {2020: -4.6, 2021: 3.5, 2022: -7.3}),
        "inflation":    S(6.9, 17.4, {2022: 46.4}, w=0.6),
        "debt_to_gdp":  S(71, 128, {2022: 128}),
        "fx_reserves":  S(4, 1),
        "current_account": S(-3.8, -1.9, {2022: -4.0}),
        "unemployment": S(4.4, 4.7),
        "bank_npl":     S(5.6, 13.0),
        "tax_revenue":  S(11, 8),
        "remittances":  S(8.0, 4.0),
    },
})

# ── Governance indicators (seed values from V-Dem, WJP, TI, FH) ────────────
# Scale: most indicators 0–1 (higher = better governance) except fh_* (1–7, higher=worse)

GOVERNANCE: dict[str, dict[str, list[tuple[int, float]]]] = {
    "US": {
        "v2x_rule":    [(y, v) for y, v in zip(range(2018, 2024), [0.92,0.90,0.89,0.88,0.87,0.86])],
        "v2x_corr":    [(y, v) for y, v in zip(range(2018, 2024), [0.88,0.87,0.85,0.84,0.83,0.82])],
        "v2x_jucon":   [(y, v) for y, v in zip(range(2018, 2024), [0.89,0.86,0.84,0.83,0.83,0.82])],
        "ti_cpi":      [(y, v) for y, v in zip(range(2018, 2024), [71,69,67,67,69,65])],
        "wjp_rule_of_law": [(y, v) for y, v in zip(range(2018, 2024), [0.69,0.69,0.68,0.67,0.67,0.66])],
        "fh_political": [(y, v) for y, v in zip(range(2018, 2024), [1,1,1,1,1,1])],
        "fh_civil":    [(y, v) for y, v in zip(range(2018, 2024), [1,1,1,1,1,1])],
    },
    "DE": {
        "v2x_rule":    [(y, v) for y, v in zip(range(2018, 2024), [0.97,0.97,0.96,0.96,0.96,0.95])],
        "v2x_corr":    [(y, v) for y, v in zip(range(2018, 2024), [0.95,0.95,0.95,0.95,0.95,0.94])],
        "v2x_jucon":   [(y, v) for y, v in zip(range(2018, 2024), [0.95,0.95,0.94,0.94,0.94,0.93])],
        "ti_cpi":      [(y, v) for y, v in zip(range(2018, 2024), [80,80,80,80,79,78])],
        "wjp_rule_of_law": [(y, v) for y, v in zip(range(2018, 2024), [0.84,0.84,0.83,0.83,0.82,0.81])],
        "fh_political": [(y, v) for y, v in zip(range(2018, 2024), [1,1,1,1,1,1])],
        "fh_civil":    [(y, v) for y, v in zip(range(2018, 2024), [1,1,1,1,1,1])],
    },
    "BR": {
        "v2x_rule":    [(y, v) for y, v in zip(range(2018, 2024), [0.72,0.68,0.65,0.64,0.65,0.66])],
        "v2x_corr":    [(y, v) for y, v in zip(range(2018, 2024), [0.62,0.60,0.58,0.57,0.60,0.61])],
        "v2x_jucon":   [(y, v) for y, v in zip(range(2018, 2024), [0.74,0.72,0.69,0.67,0.68,0.69])],
        "ti_cpi":      [(y, v) for y, v in zip(range(2018, 2024), [35,35,38,38,36,38])],
        "wjp_rule_of_law": [(y, v) for y, v in zip(range(2018, 2024), [0.51,0.51,0.50,0.49,0.50,0.51])],
        "fh_political": [(y, v) for y, v in zip(range(2018, 2024), [2,2,2,2,2,2])],
        "fh_civil":    [(y, v) for y, v in zip(range(2018, 2024), [2,2,2,2,2,2])],
    },
    "AR": {
        "v2x_rule":    [(y, v) for y, v in zip(range(2018, 2024), [0.68,0.66,0.64,0.62,0.61,0.60])],
        "v2x_corr":    [(y, v) for y, v in zip(range(2018, 2024), [0.55,0.53,0.51,0.50,0.50,0.49])],
        "v2x_jucon":   [(y, v) for y, v in zip(range(2018, 2024), [0.70,0.67,0.65,0.63,0.62,0.61])],
        "ti_cpi":      [(y, v) for y, v in zip(range(2018, 2024), [40,45,42,42,38,37])],
        "wjp_rule_of_law": [(y, v) for y, v in zip(range(2018, 2024), [0.47,0.46,0.45,0.44,0.43,0.43])],
        "fh_political": [(y, v) for y, v in zip(range(2018, 2024), [2,2,2,2,2,2])],
        "fh_civil":    [(y, v) for y, v in zip(range(2018, 2024), [2,2,2,2,2,2])],
    },
    "UA": {
        "v2x_rule":    [(y, v) for y, v in zip(range(2018, 2024), [0.60,0.62,0.63,0.63,0.64,0.63])],
        "v2x_corr":    [(y, v) for y, v in zip(range(2018, 2024), [0.40,0.42,0.44,0.43,0.43,0.42])],
        "v2x_jucon":   [(y, v) for y, v in zip(range(2018, 2024), [0.55,0.55,0.56,0.54,0.52,0.51])],
        "ti_cpi":      [(y, v) for y, v in zip(range(2018, 2024), [32,30,33,33,33,36])],
        "wjp_rule_of_law": [(y, v) for y, v in zip(range(2018, 2024), [0.49,0.49,0.48,0.48,0.49,0.48])],
        "fh_political": [(y, v) for y, v in zip(range(2018, 2024), [3,3,3,3,3,4])],
        "fh_civil":    [(y, v) for y, v in zip(range(2018, 2024), [3,3,3,3,3,4])],
    },
    "IN": {
        "v2x_rule":    [(y, v) for y, v in zip(range(2018, 2024), [0.74,0.72,0.69,0.67,0.65,0.63])],
        "v2x_corr":    [(y, v) for y, v in zip(range(2018, 2024), [0.60,0.58,0.55,0.53,0.52,0.51])],
        "v2x_jucon":   [(y, v) for y, v in zip(range(2018, 2024), [0.71,0.67,0.64,0.61,0.60,0.59])],
        "ti_cpi":      [(y, v) for y, v in zip(range(2018, 2024), [41,41,40,40,40,39])],
        "wjp_rule_of_law": [(y, v) for y, v in zip(range(2018, 2024), [0.54,0.53,0.52,0.50,0.49,0.48])],
        "fh_political": [(y, v) for y, v in zip(range(2018, 2024), [2,2,3,3,3,3])],
        "fh_civil":    [(y, v) for y, v in zip(range(2018, 2024), [3,3,3,3,3,3])],
    },
    "ZA": {
        "v2x_rule":    [(y, v) for y, v in zip(range(2018, 2024), [0.78,0.76,0.75,0.73,0.72,0.71])],
        "v2x_corr":    [(y, v) for y, v in zip(range(2018, 2024), [0.58,0.56,0.57,0.58,0.58,0.57])],
        "v2x_jucon":   [(y, v) for y, v in zip(range(2018, 2024), [0.79,0.78,0.78,0.77,0.77,0.76])],
        "ti_cpi":      [(y, v) for y, v in zip(range(2018, 2024), [43,44,44,44,43,41])],
        "wjp_rule_of_law": [(y, v) for y, v in zip(range(2018, 2024), [0.55,0.55,0.55,0.54,0.54,0.53])],
        "fh_political": [(y, v) for y, v in zip(range(2018, 2024), [2,2,2,2,2,2])],
        "fh_civil":    [(y, v) for y, v in zip(range(2018, 2024), [2,2,2,2,2,2])],
    },
    "NG": {
        "v2x_rule":    [(y, v) for y, v in zip(range(2018, 2024), [0.45,0.44,0.42,0.40,0.40,0.39])],
        "v2x_corr":    [(y, v) for y, v in zip(range(2018, 2024), [0.30,0.28,0.27,0.26,0.26,0.25])],
        "v2x_jucon":   [(y, v) for y, v in zip(range(2018, 2024), [0.42,0.40,0.38,0.37,0.36,0.35])],
        "ti_cpi":      [(y, v) for y, v in zip(range(2018, 2024), [27,26,25,25,24,24])],
        "wjp_rule_of_law": [(y, v) for y, v in zip(range(2018, 2024), [0.40,0.38,0.37,0.37,0.37,0.36])],
        "fh_political": [(y, v) for y, v in zip(range(2018, 2024), [4,4,4,4,4,4])],
        "fh_civil":    [(y, v) for y, v in zip(range(2018, 2024), [4,4,4,4,4,5])],
    },
}

# Breadth countries: generated governance from curated anchors.
GOVERNANCE.update({
    # ── G20 / advanced ──
    "CN": GOV(0.15, 0.12, 0.35, 0.30, 0.25, 0.20, 39, 42, 0.47, 0.47, 7, 6),
    "JP": GOV(0.92, 0.90, 0.90, 0.88, 0.90, 0.89, 73, 73, 0.79, 0.78, 1, 1),
    "GB": GOV(0.93, 0.88, 0.92, 0.89, 0.92, 0.90, 80, 71, 0.81, 0.79, 1, 1),
    "FR": GOV(0.89, 0.86, 0.87, 0.85, 0.88, 0.86, 72, 71, 0.74, 0.72, 1, 2),
    "IT": GOV(0.80, 0.77, 0.70, 0.70, 0.79, 0.77, 52, 56, 0.66, 0.66, 1, 1),
    "CA": GOV(0.94, 0.91, 0.93, 0.91, 0.93, 0.92, 81, 76, 0.80, 0.79, 1, 1),
    "KR": GOV(0.85, 0.83, 0.80, 0.80, 0.82, 0.81, 57, 63, 0.73, 0.72, 2, 2),
    "MX": GOV(0.55, 0.50, 0.45, 0.42, 0.55, 0.50, 28, 31, 0.45, 0.43, 2, 3),
    "RU": GOV(0.25, 0.18, 0.25, 0.20, 0.22, 0.16, 28, 26, 0.45, 0.43, 6, 6),
    "AU": GOV(0.93, 0.90, 0.92, 0.90, 0.93, 0.91, 77, 75, 0.80, 0.79, 1, 1),
    "ID": GOV(0.58, 0.52, 0.50, 0.46, 0.55, 0.50, 38, 34, 0.53, 0.51, 2, 3),
    "TR": GOV(0.35, 0.25, 0.35, 0.28, 0.32, 0.22, 41, 34, 0.42, 0.40, 5, 5),
    "SA": GOV(0.20, 0.18, 0.35, 0.34, 0.25, 0.22, 49, 52, 0.40, 0.40, 7, 7),
    # ── Europe ──
    "PL": GOV(0.70, 0.55, 0.65, 0.58, 0.68, 0.50, 60, 54, 0.66, 0.62, 1, 2),
    "ES": GOV(0.82, 0.80, 0.80, 0.78, 0.81, 0.79, 58, 60, 0.69, 0.68, 1, 1),
    "GR": GOV(0.75, 0.72, 0.60, 0.60, 0.74, 0.72, 45, 49, 0.60, 0.59, 2, 2),
    "NL": GOV(0.95, 0.92, 0.94, 0.92, 0.94, 0.93, 82, 79, 0.84, 0.83, 1, 1),
    "HU": GOV(0.55, 0.45, 0.50, 0.42, 0.52, 0.40, 46, 42, 0.50, 0.47, 3, 3),
    "CH": GOV(0.96, 0.94, 0.95, 0.94, 0.95, 0.94, 85, 82, 0.85, 0.84, 1, 1),
    # ── Latin America ──
    "CO": GOV(0.58, 0.55, 0.50, 0.48, 0.58, 0.55, 36, 40, 0.50, 0.49, 3, 3),
    "CL": GOV(0.82, 0.78, 0.78, 0.74, 0.80, 0.77, 67, 66, 0.65, 0.64, 1, 1),
    "PE": GOV(0.55, 0.48, 0.45, 0.40, 0.54, 0.46, 35, 33, 0.49, 0.47, 3, 3),
    "VE": GOV(0.12, 0.10, 0.20, 0.16, 0.15, 0.10, 18, 13, 0.30, 0.28, 7, 7),
    # ── MENA / Africa ──
    "EG": GOV(0.25, 0.22, 0.30, 0.28, 0.25, 0.22, 35, 35, 0.36, 0.35, 6, 5),
    "MA": GOV(0.42, 0.40, 0.40, 0.38, 0.42, 0.40, 43, 38, 0.50, 0.49, 4, 4),
    "LB": GOV(0.35, 0.28, 0.30, 0.24, 0.34, 0.26, 28, 24, 0.42, 0.38, 4, 4),
    "KE": GOV(0.45, 0.43, 0.35, 0.33, 0.45, 0.43, 27, 31, 0.43, 0.42, 3, 3),
    "ET": GOV(0.30, 0.25, 0.35, 0.32, 0.30, 0.25, 34, 37, 0.38, 0.36, 6, 6),
    "GH": GOV(0.60, 0.55, 0.50, 0.48, 0.58, 0.54, 41, 43, 0.55, 0.54, 2, 2),
    # ── South / Southeast Asia ──
    "PK": GOV(0.35, 0.32, 0.30, 0.28, 0.35, 0.30, 33, 29, 0.42, 0.40, 4, 4),
    "BD": GOV(0.38, 0.32, 0.35, 0.30, 0.36, 0.30, 26, 24, 0.41, 0.39, 4, 4),
    "VN": GOV(0.25, 0.22, 0.35, 0.33, 0.25, 0.22, 33, 41, 0.49, 0.49, 7, 5),
    "PH": GOV(0.45, 0.40, 0.40, 0.36, 0.45, 0.40, 36, 34, 0.47, 0.46, 3, 3),
    "TH": GOV(0.42, 0.40, 0.40, 0.38, 0.40, 0.38, 36, 35, 0.50, 0.49, 5, 4),
    "MY": GOV(0.58, 0.55, 0.50, 0.48, 0.57, 0.54, 47, 50, 0.57, 0.56, 4, 4),
    "LK": GOV(0.50, 0.42, 0.45, 0.40, 0.48, 0.40, 38, 34, 0.50, 0.48, 3, 4),
})

# ── Political events ──────────────────────────────────────────────────────────

def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


EVENTS: list[dict] = [
    # Argentina — hyperinflation crisis, political instability
    {"country": "AR", "event_type": "protest",          "event_date": _days_ago(3),   "severity": 2.5, "description": "Cost-of-living protests Buenos Aires"},
    {"country": "AR", "event_type": "protest",          "event_date": _days_ago(8),   "severity": 2.0, "description": "Pension reform protests"},
    {"country": "AR", "event_type": "protest",          "event_date": _days_ago(15),  "severity": 2.5, "description": "University funding protests"},
    {"country": "AR", "event_type": "leadership_change","event_date": _days_ago(180), "severity": 2.0, "description": "Presidential election — Milei sworn in"},
    {"country": "AR", "event_type": "sanction",         "event_date": _days_ago(45),  "severity": 2.0, "description": "IMF programme renegotiation"},
    # Ukraine — active conflict
    {"country": "UA", "event_type": "conflict",         "event_date": _days_ago(1),   "severity": 5.0, "description": "Active armed conflict, eastern regions", "fatalities": 15},
    {"country": "UA", "event_type": "conflict",         "event_date": _days_ago(2),   "severity": 5.0, "description": "Drone attacks on infrastructure", "fatalities": 5},
    {"country": "UA", "event_type": "conflict",         "event_date": _days_ago(4),   "severity": 5.0, "description": "Artillery exchanges, Donbas", "fatalities": 20},
    {"country": "UA", "event_type": "conflict",         "event_date": _days_ago(6),   "severity": 4.5, "description": "Missile strikes on Kyiv", "fatalities": 8},
    {"country": "UA", "event_type": "conflict",         "event_date": _days_ago(10),  "severity": 4.0, "description": "Naval drone attack, Black Sea"},
    {"country": "UA", "event_type": "sanction",         "event_date": _days_ago(900), "severity": 3.0, "description": "Western sanctions on Russia"},
    # Nigeria
    {"country": "NG", "event_type": "protest",          "event_date": _days_ago(14),  "severity": 2.0, "description": "Fuel subsidy protests"},
    {"country": "NG", "event_type": "conflict",         "event_date": _days_ago(20),  "severity": 2.5, "description": "Boko Haram activity, northeast", "fatalities": 10},
    {"country": "NG", "event_type": "conflict",         "event_date": _days_ago(35),  "severity": 2.0, "description": "Banditry, northwest", "fatalities": 6},
    # Brazil
    {"country": "BR", "event_type": "protest",          "event_date": _days_ago(30),  "severity": 1.5, "description": "Teachers' strike, Sao Paulo"},
    {"country": "BR", "event_type": "election",         "event_date": _days_ago(600), "severity": 1.0, "description": "Presidential election 2022"},
    # South Africa
    {"country": "ZA", "event_type": "protest",          "event_date": _days_ago(10),  "severity": 2.0, "description": "Rolling blackout protests"},
    {"country": "ZA", "event_type": "protest",          "event_date": _days_ago(25),  "severity": 1.8, "description": "Service delivery protests, townships"},
    {"country": "ZA", "event_type": "leadership_change","event_date": _days_ago(60),  "severity": 1.5, "description": "ANC leadership contest"},
    # India
    {"country": "IN", "event_type": "election",         "event_date": _days_ago(90),  "severity": 0.5, "description": "General election completed"},
    {"country": "IN", "event_type": "protest",          "event_date": _days_ago(120), "severity": 1.0, "description": "Farmers' protest, Punjab"},
    # United States
    {"country": "US", "event_type": "election",         "event_date": _days_ago(240), "severity": 0.5, "description": "Presidential election cycle"},
    # Germany
    {"country": "DE", "event_type": "election",         "event_date": _days_ago(120), "severity": 0.5, "description": "Federal election 2025"},
    {"country": "DE", "event_type": "protest",          "event_date": _days_ago(200), "severity": 0.8, "description": "AfD counter-protests"},
    # ── Breadth countries ──
    # Russia — war footing, sanctions
    {"country": "RU", "event_type": "conflict",         "event_date": _days_ago(2),   "severity": 4.5, "description": "Cross-border shelling, Belgorod", "fatalities": 4},
    {"country": "RU", "event_type": "sanction",         "event_date": _days_ago(120), "severity": 3.0, "description": "New EU sanctions package"},
    {"country": "RU", "event_type": "leadership_change","event_date": _days_ago(450), "severity": 2.0, "description": "Wagner mutiny aftermath"},
    # Venezuela — economic collapse, contested politics
    {"country": "VE", "event_type": "protest",          "event_date": _days_ago(5),   "severity": 3.0, "description": "Anti-government protests, Caracas"},
    {"country": "VE", "event_type": "leadership_change","event_date": _days_ago(30),  "severity": 2.5, "description": "Disputed election results"},
    {"country": "VE", "event_type": "sanction",         "event_date": _days_ago(220), "severity": 2.5, "description": "US oil sanctions reinstated"},
    # Lebanon — financial collapse
    {"country": "LB", "event_type": "protest",          "event_date": _days_ago(12),  "severity": 2.5, "description": "Depositors storm banks over frozen savings"},
    {"country": "LB", "event_type": "leadership_change","event_date": _days_ago(90),  "severity": 2.0, "description": "Presidential vacancy, caretaker government"},
    # Pakistan — political crisis
    {"country": "PK", "event_type": "protest",          "event_date": _days_ago(7),   "severity": 2.5, "description": "PTI supporters clash with police"},
    {"country": "PK", "event_type": "leadership_change","event_date": _days_ago(60),  "severity": 2.0, "description": "Contested general election"},
    {"country": "PK", "event_type": "conflict",         "event_date": _days_ago(40),  "severity": 2.5, "description": "Militant attack, Khyber Pakhtunkhwa", "fatalities": 9},
    # Sri Lanka — post-default recovery
    {"country": "LK", "event_type": "protest",          "event_date": _days_ago(50),  "severity": 2.0, "description": "Cost-of-living protests, Colombo"},
    {"country": "LK", "event_type": "sanction",         "event_date": _days_ago(120), "severity": 1.5, "description": "IMF bailout conditionality review"},
    # Ethiopia — post-conflict fragility
    {"country": "ET", "event_type": "conflict",         "event_date": _days_ago(25),  "severity": 3.5, "description": "Amhara region clashes", "fatalities": 14},
    {"country": "ET", "event_type": "protest",          "event_date": _days_ago(70),  "severity": 1.8, "description": "Ethnic tension protests"},
    # Turkey
    {"country": "TR", "event_type": "protest",          "event_date": _days_ago(40),  "severity": 1.5, "description": "Anti-inflation labour protests"},
    {"country": "TR", "event_type": "election",         "event_date": _days_ago(400), "severity": 1.0, "description": "Presidential run-off, Erdogan re-elected"},
    # Egypt
    {"country": "EG", "event_type": "protest",          "event_date": _days_ago(80),  "severity": 1.5, "description": "Bread price protests"},
    # Ghana — debt distress
    {"country": "GH", "event_type": "protest",          "event_date": _days_ago(35),  "severity": 1.8, "description": "Economic hardship protests, Accra"},
    # Kenya
    {"country": "KE", "event_type": "protest",          "event_date": _days_ago(18),  "severity": 2.2, "description": "Anti-tax 'Finance Bill' protests", "fatalities": 3},
    # Colombia
    {"country": "CO", "event_type": "protest",          "event_date": _days_ago(45),  "severity": 1.8, "description": "Reform protests, Bogota"},
    # Mexico — cartel violence
    {"country": "MX", "event_type": "conflict",         "event_date": _days_ago(15),  "severity": 2.5, "description": "Cartel violence, Sinaloa", "fatalities": 12},
    {"country": "MX", "event_type": "election",         "event_date": _days_ago(20),  "severity": 0.8, "description": "General election, Sheinbaum wins"},
    # France — social unrest
    {"country": "FR", "event_type": "protest",          "event_date": _days_ago(55),  "severity": 1.5, "description": "Pension reform strikes"},
    # Thailand
    {"country": "TH", "event_type": "protest",          "event_date": _days_ago(110), "severity": 1.5, "description": "Pro-reform youth protests"},
    # Bangladesh
    {"country": "BD", "event_type": "protest",          "event_date": _days_ago(28),  "severity": 2.5, "description": "Student quota protests, Dhaka", "fatalities": 5},
    # Indonesia
    {"country": "ID", "event_type": "election",         "event_date": _days_ago(130), "severity": 0.8, "description": "Presidential election, Prabowo wins"},
]

# ── Central bank statements ──────────────────────────────────────────────────

STATEMENTS: list[dict] = [
    {
        "country": "US", "bank": "Federal Reserve",
        "date": _days_ago(15),
        "text": (
            "The Committee seeks to achieve maximum employment and inflation at the rate of 2 percent over the longer run. "
            "In support of these goals, the Committee decided to maintain the target range for the federal funds rate at 5-1/4 to 5-1/2 percent. "
            "The Committee remains highly attentive to inflation risks and is prepared to adjust the stance of monetary policy as appropriate. "
            "Inflation remains elevated and the Committee is firmly committed to returning inflation to its 2 percent objective. "
            "Recent indicators suggest that economic activity has continued to expand at a solid pace. "
            "Job gains have been strong, and the unemployment rate has remained low. "
            "The U.S. banking system is sound and resilient."
        ),
        "sentiment": 72.0,
    },
    {
        "country": "GB", "bank": "Bank of England",
        "date": _days_ago(10),
        "text": (
            "The Monetary Policy Committee voted to maintain Bank Rate at 5.25%. "
            "CPI inflation is expected to return sustainably to the 2% target. "
            "The Committee will ensure that Bank Rate is sufficiently restrictive for sufficiently long. "
            "There are risks that inflation could prove more persistent than expected. "
            "The labour market has been loosening gradually. "
            "GDP growth has been subdued in recent quarters."
        ),
        "sentiment": 68.0,
    },
    {
        "country": "BR", "bank": "Banco Central do Brasil",
        "date": _days_ago(20),
        "text": (
            "The Copom decided to reduce the Selic rate by 0.25 percentage points to 10.50% p.a. "
            "The environment continues to require serenity and moderation in the conduct of monetary policy. "
            "Inflation expectations remain above target. The Committee will remain vigilant. "
            "Fiscal risks and uncertainty about the global economic outlook require caution. "
            "The fiscal framework constitutes an important element for anchoring inflation expectations. "
            "Uncertainty remains high regarding the sustainability of public debt trajectory."
        ),
        "sentiment": 58.0,
    },
    {
        "country": "DE", "bank": "ECB",
        "date": _days_ago(12),
        "text": (
            "The Governing Council today decided to lower the three key ECB interest rates by 25 basis points. "
            "Based on its updated assessment of the inflation outlook, the dynamics of underlying inflation "
            "and the strength of monetary policy transmission, it is now appropriate to moderate the degree of "
            "monetary policy restriction. The Governing Council remains data-dependent and does not pre-commit "
            "to a particular rate path. The euro area economy is recovering gradually. "
            "Inflation is declining but domestic price pressures remain elevated."
        ),
        "sentiment": 42.0,
    },
    {
        "country": "AR", "bank": "Banco Central de la República Argentina",
        "date": _days_ago(8),
        "text": (
            "El Banco Central redujo la tasa de política monetaria al 40%. "
            "La inflación sigue siendo el principal desafío de política económica. "
            "The central bank is implementing emergency measures to stabilize the peso. "
            "Exchange rate unification remains a priority. Significant uncertainty persists. "
            "Capital controls remain in place to protect foreign exchange reserves. "
            "The reserve position has declined substantially. Financial stability risks remain elevated."
        ),
        "sentiment": 85.0,
    },
    {
        "country": "UA", "bank": "National Bank of Ukraine",
        "date": _days_ago(18),
        "text": (
            "The NBU Board decided to keep the key policy rate at 13.5%. "
            "Wartime economic conditions continue to create extraordinary challenges for monetary policy. "
            "Inflation is gradually declining but remains elevated due to supply disruptions. "
            "The NBU continues to support financial system stability under martial law conditions. "
            "International financial support is critical for macroeconomic stability. "
            "Foreign exchange reserves remain at adequate levels due to donor support."
        ),
        "sentiment": 78.0,
    },
    {
        "country": "ZA", "bank": "South African Reserve Bank",
        "date": _days_ago(25),
        "text": (
            "The Monetary Policy Committee decided to keep the repo rate unchanged at 8.25%. "
            "The risks to the inflation outlook are assessed to be on the upside. "
            "Electricity supply constraints continue to weigh on economic growth. "
            "Load shedding has caused significant damage to productive capacity. "
            "The current account deficit reflects structural vulnerabilities. "
            "Inflation is expected to moderate gradually within the target band."
        ),
        "sentiment": 61.0,
    },
    {
        "country": "IN", "bank": "Reserve Bank of India",
        "date": _days_ago(22),
        "text": (
            "The Monetary Policy Committee voted to keep the policy repo rate unchanged at 6.50%. "
            "The MPC remains focused on withdrawal of accommodation to ensure that inflation progressively aligns to the target. "
            "GDP growth remains strong driven by investment demand and robust domestic consumption. "
            "Headline inflation has moderated but food price pressures remain a concern. "
            "The banking system remains well-capitalised with improving asset quality. "
            "External sector remains resilient with comfortable foreign exchange reserves."
        ),
        "sentiment": 55.0,
    },
    # ── Breadth countries ──
    {
        "country": "JP", "bank": "Bank of Japan",
        "date": _days_ago(14),
        "text": (
            "The Bank decided to maintain the short-term policy interest rate at around 0 to 0.1 percent. "
            "Japan's economy is recovering moderately although some weakness has been seen in part. "
            "Inflation expectations have risen moderately and wage growth is gradually strengthening. "
            "The Bank will patiently continue with monetary easing to achieve the price stability target. "
            "Uncertainties surrounding economies and financial markets remain extremely high. "
            "The Bank will not hesitate to take additional easing measures if necessary."
        ),
        "sentiment": 35.0,
    },
    {
        "country": "CN", "bank": "People's Bank of China",
        "date": _days_ago(16),
        "text": (
            "The People's Bank of China will maintain a prudent monetary policy that is targeted and effective. "
            "The Bank cut the reserve requirement ratio to support credit growth and the real economy. "
            "Domestic demand remains insufficient and the foundation for economic recovery is not yet solid. "
            "The property sector continues to face downward pressure and requires policy support. "
            "The Bank will keep liquidity reasonably ample and guide financing costs lower. "
            "Risks in some small and medium financial institutions warrant continued attention."
        ),
        "sentiment": 38.0,
    },
    {
        "country": "TR", "bank": "Central Bank of the Republic of Türkiye",
        "date": _days_ago(11),
        "text": (
            "The Committee decided to raise the policy rate to 50 percent to establish disinflation. "
            "Inflation remains exceptionally elevated and the outlook continues to pose significant risks. "
            "Monetary tightening will be maintained until a significant and sustained decline in inflation is achieved. "
            "The Committee remains highly attentive to inflation expectations and pricing behaviour. "
            "Additional tightening will be delivered should the inflation outlook deteriorate. "
            "External financing conditions and reserve adequacy remain under close monitoring."
        ),
        "sentiment": 88.0,
    },
    {
        "country": "MX", "bank": "Banco de México",
        "date": _days_ago(19),
        "text": (
            "The Board of Governors decided to keep the overnight interbank interest rate at 11.00%. "
            "The inflationary environment remains complex and the balance of risks is biased to the upside. "
            "Core inflation has shown a downward trend but services inflation remains persistent. "
            "The Board will maintain a restrictive monetary stance for an extended period. "
            "The Mexican peso has shown resilience supported by strong remittance inflows. "
            "Future decisions will depend on the evolution of the inflation outlook."
        ),
        "sentiment": 64.0,
    },
    {
        "country": "RU", "bank": "Bank of Russia",
        "date": _days_ago(21),
        "text": (
            "The Bank of Russia raised the key rate to 16 percent amid elevated inflationary pressure. "
            "Domestic demand continues to outpace the capacity to expand output. "
            "Pro-inflationary risks remain significant including a tight labour market. "
            "Wartime fiscal expansion and exchange rate volatility complicate the outlook. "
            "Tight monetary conditions will be maintained for a prolonged period. "
            "The Bank will assess the feasibility of further rate increases at upcoming meetings."
        ),
        "sentiment": 82.0,
    },
    {
        "country": "KR", "bank": "Bank of Korea",
        "date": _days_ago(17),
        "text": (
            "The Monetary Policy Board decided to maintain the Base Rate at 3.50 percent. "
            "Inflation is expected to continue its slowing trend toward the target level. "
            "The Board will maintain a restrictive policy stance for a sufficient period. "
            "Household debt and financial stability risks warrant continued vigilance. "
            "Domestic growth is projected to improve led by exports of semiconductors. "
            "Uncertainties regarding the pace of disinflation remain high."
        ),
        "sentiment": 52.0,
    },
    {
        "country": "ID", "bank": "Bank Indonesia",
        "date": _days_ago(23),
        "text": (
            "Bank Indonesia decided to hold the BI-Rate at 6.25 percent to ensure inflation control. "
            "The decision is consistent with pre-emptive and forward-looking monetary policy. "
            "Rupiah stability is a priority amid global financial market uncertainty. "
            "Inflation remains under control within the target corridor. "
            "Domestic economic growth remains solid supported by household consumption. "
            "Bank Indonesia will optimise its policy mix to safeguard stability."
        ),
        "sentiment": 50.0,
    },
    {
        "country": "AU", "bank": "Reserve Bank of Australia",
        "date": _days_ago(13),
        "text": (
            "The Board decided to leave the cash rate target unchanged at 4.35 percent. "
            "Inflation remains above target and is proving persistent in the services sector. "
            "The Board is not ruling anything in or out regarding future policy. "
            "Returning inflation to target within a reasonable timeframe remains the priority. "
            "The labour market remains tight although conditions are gradually easing. "
            "The economic outlook remains uncertain and data-dependence will guide decisions."
        ),
        "sentiment": 60.0,
    },
]


def _compute_scores(db) -> int:
    """Compute and persist a CountryScore snapshot for every seeded country so
    the dashboard is populated immediately after seeding (no manual /risk call).
    Mirrors the data-loading + scoring path in api.routers.risk._build_response."""
    from core.scoring.composite import compute_composite

    codes = sorted(set(INDICATORS) | set(GOVERNANCE))
    n = 0
    for code in codes:
        rows = db.query(Indicator).filter(Indicator.country_code == code).all()
        rows = sorted(rows, key=lambda r: (r.year or 0, r.date or ""))
        indicators: dict[str, list[float]] = {}
        for r in rows:
            indicators.setdefault(r.metric, []).append(r.value)

        events = db.query(PoliticalEvent).filter(PoliticalEvent.country_code == code).all()
        event_dicts = [
            {"event_type": e.event_type, "event_date": e.event_date,
             "severity": e.severity, "description": e.description}
            for e in events
        ]

        stmt = (
            db.query(CentralBankStatement)
            .filter(CentralBankStatement.country_code == code)
            .order_by(CentralBankStatement.fetched_at.desc())
            .first()
        )
        nlp_raw = stmt.sentiment_score if stmt else None

        gov_rows = db.query(GovernanceIndicator).filter(GovernanceIndicator.country_code == code).all()
        gov_rows = sorted(gov_rows, key=lambda r: r.year or 0)
        governance_indicators: dict[str, list[float]] = {}
        for r in gov_rows:
            governance_indicators.setdefault(r.metric, []).append(r.value)

        result = compute_composite(
            indicators=indicators,
            events=event_dicts,
            nlp_score=nlp_raw,
            governance_indicators=governance_indicators or None,
            nlp_confidence=0.7 if stmt else 0.5,
            country=code,
        )

        f6 = result.get("forecast_6m")
        f12 = result.get("forecast_12m")
        db.add(CountryScore(
            country_code=code,
            composite=result["composite"],
            ci_low=result.get("ci_low"),
            ci_high=result.get("ci_high"),
            economic=result.get("economic"),
            political=result.get("political"),
            nlp_sentiment=result.get("nlp_sentiment"),
            governance=result.get("governance"),
            confidence=result.get("confidence"),
            top_drivers=json.dumps(result.get("top_drivers", [])),
            driver_attributions=json.dumps(result.get("driver_attributions", [])),
            methodology=result.get("methodology"),
            forecast_6m=json.dumps(f6) if f6 else None,
            forecast_12m=json.dumps(f12) if f12 else None,
            computed_at=datetime.now(timezone.utc),
        ))
        n += 1
    db.commit()
    return n


def _ensure_schema() -> None:
    """Make sure the tables exist before seeding.

    In Docker the schema is created by `alembic upgrade head` at container
    start, which may still be running when this script is invoked. Racing it
    with create_all() triggers a duplicate-type error on Postgres
    (pg_type_typname_nsp_index), so on a managed DB we *wait* for alembic
    instead of creating tables ourselves. On plain SQLite (local dev, no
    alembic) we create them directly."""
    import time
    from sqlalchemy import inspect

    required = ["indicators", "governance_indicators", "political_events",
                "central_bank_statements", "country_scores"]

    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(bind=engine, checkfirst=True)
        return

    for _ in range(45):  # up to ~90s
        try:
            have = set(inspect(engine).get_table_names())
            if all(t in have for t in required):
                return
        except Exception:
            pass
        time.sleep(2)

    raise RuntimeError(
        "Database schema is not ready after 90s. Is `alembic upgrade head` "
        "still running or failing? Check `docker compose logs api`."
    )


def seed() -> None:
    _ensure_schema()
    db = SessionLocal()
    try:
        count_ind = 0
        for country_code, metrics in INDICATORS.items():
            for metric, series in metrics.items():
                for year, value in series:
                    if not db.query(Indicator).filter(
                        Indicator.country_code == country_code,
                        Indicator.metric == metric,
                        Indicator.year == year,
                        Indicator.source == "seed",
                    ).first():
                        db.add(Indicator(
                            country_code=country_code, metric=metric,
                            year=year, value=value, source="seed",
                        ))
                        count_ind += 1

        count_gov = 0
        for country_code, metrics in GOVERNANCE.items():
            for metric, series in metrics.items():
                for year, value in series:
                    if not db.query(GovernanceIndicator).filter(
                        GovernanceIndicator.country_code == country_code,
                        GovernanceIndicator.metric == metric,
                        GovernanceIndicator.year == year,
                    ).first():
                        db.add(GovernanceIndicator(
                            country_code=country_code, metric=metric,
                            year=year, value=value, source="seed",
                        ))
                        count_gov += 1

        count_ev = 0
        for ev in EVENTS:
            if db.query(PoliticalEvent).filter(
                PoliticalEvent.country_code == ev["country"],
                PoliticalEvent.event_type == ev["event_type"],
                PoliticalEvent.event_date == ev["event_date"],
                PoliticalEvent.description == ev.get("description"),
            ).first():
                continue
            db.add(PoliticalEvent(
                country_code=ev["country"],
                event_type=ev["event_type"],
                event_date=ev["event_date"],
                severity=ev["severity"],
                description=ev.get("description"),
                source=ev.get("source", "seed"),
            ))
            count_ev += 1

        count_st = 0
        for st in STATEMENTS:
            if db.query(CentralBankStatement).filter(
                CentralBankStatement.country_code == st["country"],
                CentralBankStatement.bank_name == st["bank"],
                CentralBankStatement.statement_date == st["date"],
            ).first():
                continue
            db.add(CentralBankStatement(
                country_code=st["country"],
                bank_name=st["bank"],
                statement_date=st["date"],
                raw_text=st["text"],
                sentiment_score=st["sentiment"],
            ))
            count_st += 1

        db.commit()
        countries = sorted(set(INDICATORS) | set(GOVERNANCE))
        print(f"Seeded: {count_ind} indicators, {count_gov} governance, {count_ev} events, {count_st} statements")

        count_sc = _compute_scores(db)
        print(f"Computed {count_sc} country scores (dashboard is now populated).")
        print(f"Countries ({len(countries)}): {', '.join(countries)}")
        print("Run the API and visit /dashboard or GET /risk/BR to see results.")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
