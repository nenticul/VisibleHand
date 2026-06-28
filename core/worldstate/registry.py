"""
Static configuration & model registry for VH-WSM.

Holds version strings, the country universe, the feature schema, hazard targets,
and the deterministic geography/trade graph used for spillover features. Kept
dependency-free so every other module (and the test stub environment) can import
it cheaply.
"""

from __future__ import annotations

import os

# ── Versions ─────────────────────────────────────────────────────────────────
MODEL_VERSION = "vh-wsm-0.1.0"
FEATURE_VERSION = "vh-wsm-features-0.1"
EMBEDDING_VERSION = "vh-wsm-pca-0.1"
HAZARD_MODEL_NAME = "vh-wsm-hazard-logistic"
HAZARD_MODEL_VERSION = "0.1.0"
BASE_SCORE_VERSION = "visiblehand-0.3.0"

# ── Artefact storage ─────────────────────────────────────────────────────────
DATA_ROOT = os.environ.get("VH_WSM_DATA_ROOT", os.path.join("data", "models", "worldstate"))
PCA_ARTEFACT_DIR = os.path.join(DATA_ROOT, "pca", "v0.1")
HAZARD_ARTEFACT_DIR = os.path.join(DATA_ROOT, "hazard", "v0.1")

# ── Country universe (44 seed countries) ─────────────────────────────────────
UNIVERSE = [
    "AR", "PH", "PE", "UA", "MY", "ZA", "BD", "MA", "TR", "PK", "HU", "ET",
    "KR", "NG", "LB", "RU", "CN", "SA", "GB", "CH", "CL", "LK", "KE", "AU",
    "CA", "VE", "BR", "JP", "MX", "VN", "IT", "GH", "DE", "NL", "US", "PL",
    "CO", "ES", "TH", "GR", "FR", "ID", "EG", "IN",
]

# Crisis_dataset uses ISO-2 codes that mostly match; Sri Lanka is "SL" there.
CRISIS_DATASET_ALIASES = {"LK": "SL"}

# ── Economic indicators → *_z feature columns ────────────────────────────────
ECON_METRICS = [
    "inflation", "debt_to_gdp", "fx_reserves", "current_account",
    "unemployment", "bank_npl", "tax_revenue", "remittances", "credit_gap",
]
# Sign of risk: +1 means "higher value = higher risk" (used only for the
# historical economic risk proxy, never for the raw stored z-scores).
ECON_RISK_SIGN = {
    "inflation": +1, "debt_to_gdp": +1, "fx_reserves": -1, "current_account": -1,
    "unemployment": +1, "bank_npl": +1, "tax_revenue": -1, "remittances": 0,
    "credit_gap": +1,
}

# Ordered feature columns that form the embedding input vector. Chosen for broad
# historical availability across the 44-country annual panel.
EMBEDDING_FEATURE_COLUMNS = [
    "inflation_z", "debt_to_gdp_z", "fx_reserves_z", "current_account_z",
    "unemployment_z", "bank_npl_z", "tax_revenue_z", "remittances_z",
    "credit_gap_z", "governance_structural_score", "visiblehand_score",
]

# ── Hazard targets ───────────────────────────────────────────────────────────
HAZARD_TARGETS = [
    "sovereign_default", "currency_crisis", "imf_programme", "banking_crisis",
    "civil_conflict", "coup", "sanctions_shock", "political_instability",
]
HORIZONS_MONTHS = [6, 12, 18]

# crisis_dataset.crisis_type  →  VH-WSM hazard target
CRISIS_TYPE_TO_TARGET = {
    "default": "sovereign_default",
    "imf_programme": "imf_programme",
    "currency": "currency_crisis",
    "banking": "banking_crisis",
    "civil_war": "civil_conflict",
    "coup": "coup",
}
# Targets that aggregate political instability signals when no direct label exists.
POLITICAL_INSTABILITY_SOURCES = {"coup", "civil_war"}

# ── Risk bands (shared with the base scorer) ─────────────────────────────────
def risk_band(score: float | None) -> str:
    if score is None:
        return "N/A"
    if score < 20:
        return "VERY LOW"
    if score < 40:
        return "LOW"
    if score < 60:
        return "MODERATE"
    if score < 75:
        return "HIGH"
    if score < 90:
        return "VERY HIGH"
    return "CRITICAL"


# ── Deterministic geography / trade graph ────────────────────────────────────
# region per country
REGION = {
    "US": "N. America", "CA": "N. America", "MX": "N. America",
    "BR": "S. America", "AR": "S. America", "CO": "S. America",
    "CL": "S. America", "PE": "S. America", "VE": "S. America",
    "DE": "Europe", "GB": "Europe", "FR": "Europe", "IT": "Europe",
    "ES": "Europe", "GR": "Europe", "NL": "Europe", "HU": "Europe",
    "CH": "Europe", "PL": "Europe", "UA": "Europe", "RU": "Europe",
    "TR": "MENA", "SA": "MENA", "EG": "MENA", "MA": "MENA", "LB": "MENA",
    "ZA": "Sub-Saharan", "NG": "Sub-Saharan", "KE": "Sub-Saharan",
    "ET": "Sub-Saharan", "GH": "Sub-Saharan",
    "CN": "Asia-Pacific", "JP": "Asia-Pacific", "KR": "Asia-Pacific",
    "IN": "Asia-Pacific", "ID": "Asia-Pacific", "PK": "Asia-Pacific",
    "BD": "Asia-Pacific", "VN": "Asia-Pacific", "PH": "Asia-Pacific",
    "TH": "Asia-Pacific", "MY": "Asia-Pacific", "LK": "Asia-Pacific",
    "AU": "Asia-Pacific",
}

# Land/maritime neighbours within the universe (approximate, undirected).
NEIGHBOURS = {
    "US": ["CA", "MX"], "CA": ["US"], "MX": ["US"],
    "BR": ["AR", "CO", "PE", "VE"], "AR": ["BR", "CL"], "CO": ["BR", "PE", "VE"],
    "CL": ["AR", "PE"], "PE": ["BR", "CO", "CL"], "VE": ["BR", "CO"],
    "DE": ["FR", "NL", "PL", "CH"], "FR": ["DE", "IT", "ES", "CH"],
    "IT": ["FR", "CH"], "ES": ["FR"], "GR": ["TR"], "NL": ["DE"],
    "HU": ["UA"], "CH": ["DE", "FR", "IT"], "PL": ["DE", "UA"],
    "UA": ["RU", "PL", "HU"], "RU": ["UA", "CN"],
    "TR": ["GR", "LB"], "SA": ["EG"], "EG": ["SA", "LB"], "MA": [], "LB": ["TR", "EG"],
    "ZA": [], "NG": ["GH"], "KE": ["ET"], "ET": ["KE"], "GH": ["NG"],
    "CN": ["RU", "IN", "VN"], "JP": ["KR"], "KR": ["JP", "CN"],
    "IN": ["CN", "PK", "BD", "LK"], "ID": ["MY"], "PK": ["IN"], "BD": ["IN"],
    "VN": ["CN", "TH"], "PH": [], "TH": ["VN", "MY"], "MY": ["TH", "ID"],
    "LK": ["IN"], "AU": [],
}

# Top trade partners within the universe with rough weights (sum need not be 1).
TRADE_PARTNERS = {
    "AR": {"BR": 0.4, "CN": 0.3, "US": 0.2}, "BR": {"CN": 0.4, "US": 0.3, "AR": 0.1},
    "MX": {"US": 0.8, "CN": 0.1}, "CA": {"US": 0.75, "CN": 0.1},
    "CO": {"US": 0.4, "CN": 0.2, "BR": 0.1}, "CL": {"CN": 0.4, "US": 0.2},
    "PE": {"CN": 0.4, "US": 0.2}, "VE": {"CN": 0.4, "US": 0.2, "BR": 0.1},
    "DE": {"US": 0.3, "CN": 0.3, "FR": 0.2, "NL": 0.1}, "FR": {"DE": 0.3, "IT": 0.2, "ES": 0.2, "US": 0.1},
    "IT": {"DE": 0.3, "FR": 0.2, "US": 0.1}, "ES": {"FR": 0.3, "DE": 0.2, "IT": 0.1},
    "GR": {"IT": 0.2, "DE": 0.2, "TR": 0.2}, "NL": {"DE": 0.4, "GB": 0.1},
    "HU": {"DE": 0.4, "PL": 0.1}, "CH": {"DE": 0.4, "US": 0.2, "IT": 0.1},
    "PL": {"DE": 0.4, "UA": 0.1}, "UA": {"RU": 0.2, "PL": 0.2, "CN": 0.2},
    "RU": {"CN": 0.5, "IN": 0.2, "TR": 0.1}, "TR": {"DE": 0.3, "RU": 0.2, "GB": 0.1},
    "SA": {"CN": 0.4, "IN": 0.2, "JP": 0.2}, "EG": {"CN": 0.2, "SA": 0.2, "US": 0.1},
    "MA": {"ES": 0.3, "FR": 0.3}, "LB": {"CN": 0.2, "TR": 0.2, "EG": 0.1},
    "ZA": {"CN": 0.4, "DE": 0.1, "US": 0.1}, "NG": {"CN": 0.3, "IN": 0.2, "US": 0.1},
    "KE": {"CN": 0.3, "IN": 0.1}, "ET": {"CN": 0.4, "US": 0.1}, "GH": {"CN": 0.3, "US": 0.1},
    "CN": {"US": 0.4, "JP": 0.1, "KR": 0.1}, "JP": {"CN": 0.4, "US": 0.3},
    "KR": {"CN": 0.4, "US": 0.2, "JP": 0.1}, "IN": {"CN": 0.3, "US": 0.3},
    "ID": {"CN": 0.4, "JP": 0.1, "US": 0.1}, "PK": {"CN": 0.4, "US": 0.2},
    "BD": {"CN": 0.3, "IN": 0.2, "US": 0.1}, "VN": {"CN": 0.4, "US": 0.3, "KR": 0.1},
    "PH": {"CN": 0.3, "JP": 0.2, "US": 0.2}, "TH": {"CN": 0.4, "US": 0.1, "JP": 0.1},
    "MY": {"CN": 0.4, "US": 0.1, "JP": 0.1}, "LK": {"IN": 0.3, "CN": 0.2, "US": 0.2},
    "AU": {"CN": 0.5, "JP": 0.2, "KR": 0.1}, "GB": {"US": 0.3, "DE": 0.2, "NL": 0.1},
    "US": {"CN": 0.3, "CA": 0.2, "MX": 0.2},
}

# Countries under significant sanctions pressure (heuristic for v0.1).
SANCTIONED = {"RU": 1.0, "VE": 0.8, "LB": 0.3}
# Countries with active/recent civil conflict (heuristic).
CONFLICT_COUNTRIES = {"UA", "RU", "ET", "NG", "LB"}


def aliased_for_crisis_dataset(code: str) -> str:
    return CRISIS_DATASET_ALIASES.get(code, code)
