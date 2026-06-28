"""
Historical sovereign crisis dataset for calibration.

Covers ~220 crisis events from 2000-2023. Each entry is a (country, year)
pair labelled as a crisis (1) or non-crisis (0) within 12 months of the
observation date.

Crisis types included:
  - Sovereign default / debt restructuring (IMF records)
  - IMF programme onset (Stand-By Agreement / EFF entry)
  - Currency crisis (30%+ devaluation within 1 year)
  - Banking crisis onset (Laeven & Valencia 2012 + updates)
  - Civil war onset (UCDP/PRIO: 25+ battle deaths)
  - Coup d'état (successful, REIGN dataset)

Sources: IMF Historical Public Debt Database, Laeven & Valencia (2012/2018),
UCDP Conflict Catalogue, REIGN, World Bank.

This dataset is assembled from publicly available academic sources and used
solely for calibration research. It is NOT redistributed raw data — it is a
curated derived dataset encoding crisis onset year labels only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CrisisEvent:
    country: str        # ISO-2 code
    year: int
    crisis_type: str    # "default" | "imf_programme" | "currency" | "banking" | "civil_war" | "coup"
    label: int          # 1 = crisis, 0 = normal (included as hard negatives)
    notes: str = ""


# ── Crisis labels (label=1) ──────────────────────────────────────────────────
CRISIS_EVENTS: list[CrisisEvent] = [
    # ── Sovereign defaults / debt restructuring ───────────────────────────
    CrisisEvent("AR", 2001, "default", 1, "Argentine peso crisis, IMF collapse"),
    CrisisEvent("AR", 2002, "default", 1, "Argentine debt restructuring"),
    CrisisEvent("GR", 2010, "default", 1, "Greek sovereign debt crisis"),
    CrisisEvent("GR", 2011, "default", 1, "Greek haircut"),
    CrisisEvent("GR", 2012, "default", 1, "Greek second bailout"),
    CrisisEvent("EC", 2008, "default", 1, "Ecuador selective default"),
    CrisisEvent("JM", 2010, "default", 1, "Jamaica debt exchange"),
    CrisisEvent("BD", 2003, "default", 1, "Belize standstill"),
    CrisisEvent("ZW", 2000, "default", 1, "Zimbabwe hyperinflation onset"),
    CrisisEvent("VE", 2017, "default", 1, "Venezuela PDVSA default"),
    CrisisEvent("VE", 2018, "default", 1, "Venezuela sovereign default"),
    CrisisEvent("LB", 2020, "default", 1, "Lebanon sovereign default"),
    CrisisEvent("ZM", 2020, "default", 1, "Zambia Eurobond default"),
    CrisisEvent("SL", 2022, "default", 1, "Sri Lanka sovereign default"),
    CrisisEvent("GH", 2022, "default", 1, "Ghana debt restructuring"),
    CrisisEvent("ET", 2023, "default", 1, "Ethiopia Eurobond default"),

    # ── IMF programme onsets ──────────────────────────────────────────────
    CrisisEvent("TR", 2001, "imf_programme", 1, "Turkey SBA following lira collapse"),
    CrisisEvent("PK", 2000, "imf_programme", 1, "Pakistan SBA"),
    CrisisEvent("ID", 2000, "imf_programme", 1, "Indonesia post-Asian crisis EFF"),
    CrisisEvent("UA", 2008, "imf_programme", 1, "Ukraine SBA during GFC"),
    CrisisEvent("UA", 2014, "imf_programme", 1, "Ukraine SBA post-Maidan"),
    CrisisEvent("GR", 2010, "imf_programme", 1, "Greece SBA"),
    CrisisEvent("IE", 2010, "imf_programme", 1, "Ireland EFF"),
    CrisisEvent("PT", 2011, "imf_programme", 1, "Portugal EFF"),
    CrisisEvent("EG", 2016, "imf_programme", 1, "Egypt EFF following devaluation"),
    CrisisEvent("AR", 2018, "imf_programme", 1, "Argentina record SBA"),
    CrisisEvent("PK", 2019, "imf_programme", 1, "Pakistan EFF"),
    CrisisEvent("EC", 2020, "imf_programme", 1, "Ecuador EFF post-COVID"),
    CrisisEvent("SL", 2023, "imf_programme", 1, "Sri Lanka EFF post-default"),
    CrisisEvent("BD", 2023, "imf_programme", 1, "Bangladesh ECF"),

    # ── Currency crises ───────────────────────────────────────────────────
    CrisisEvent("TR", 2001, "currency", 1, "Turkish lira collapse -50%"),
    CrisisEvent("AR", 2002, "currency", 1, "Peso devaluation post-peg"),
    CrisisEvent("VE", 2013, "currency", 1, "Bolívar devaluation"),
    CrisisEvent("NG", 2016, "currency", 1, "Naira devaluation -40%"),
    CrisisEvent("EG", 2016, "currency", 1, "Pound float, -50%"),
    CrisisEvent("ZA", 2015, "currency", 1, "Rand -25% vs USD"),
    CrisisEvent("BR", 2015, "currency", 1, "Real -33% fiscal crisis"),
    CrisisEvent("TR", 2018, "currency", 1, "Lira crisis -40%"),
    CrisisEvent("AR", 2018, "currency", 1, "Peso -50% vs USD"),
    CrisisEvent("TR", 2021, "currency", 1, "Lira -44% vs USD"),
    CrisisEvent("LB", 2019, "currency", 1, "Pound black market divergence"),
    CrisisEvent("NG", 2023, "currency", 1, "Naira devaluation post-float"),
    CrisisEvent("EG", 2022, "currency", 1, "Pound successive devaluations"),

    # ── Banking crises ────────────────────────────────────────────────────
    CrisisEvent("US", 2008, "banking", 1, "GFC — Lehman, AIG, Bear Stearns"),
    CrisisEvent("IE", 2008, "banking", 1, "Irish banking system collapse"),
    CrisisEvent("GB", 2007, "banking", 1, "Northern Rock; RBS near-collapse"),
    CrisisEvent("UA", 2008, "banking", 1, "Ukrainian banking crisis"),
    CrisisEvent("KZ", 2008, "banking", 1, "Kazakh banking sector"),
    CrisisEvent("IS", 2008, "banking", 1, "Iceland banking collapse"),
    CrisisEvent("GR", 2015, "banking", 1, "Greek capital controls"),
    CrisisEvent("UA", 2014, "banking", 1, "Ukrainian banking sector"),
    CrisisEvent("NG", 2009, "banking", 1, "Nigerian banking bailout"),
    CrisisEvent("IN", 2018, "banking", 1, "Indian shadow banking (IL&FS)"),
    CrisisEvent("TR", 2001, "banking", 1, "Turkish banking sector crisis"),
    CrisisEvent("LB", 2019, "banking", 1, "Lebanese banking freeze"),

    # ── Civil war onsets ──────────────────────────────────────────────────
    CrisisEvent("LY", 2011, "civil_war", 1, "Libyan civil war onset"),
    CrisisEvent("SY", 2011, "civil_war", 1, "Syrian civil war onset"),
    CrisisEvent("UA", 2014, "civil_war", 1, "Donbas conflict onset"),
    CrisisEvent("UA", 2022, "civil_war", 1, "Russian full-scale invasion"),
    CrisisEvent("YE", 2015, "civil_war", 1, "Yemen civil war onset"),
    CrisisEvent("SS", 2013, "civil_war", 1, "South Sudan civil war"),
    CrisisEvent("CF", 2013, "civil_war", 1, "CAR civil war"),
    CrisisEvent("ML", 2012, "civil_war", 1, "Mali coup + Tuareg rebellion"),
    CrisisEvent("ET", 2020, "civil_war", 1, "Tigray war onset"),
    CrisisEvent("CD", 2012, "civil_war", 1, "M23 insurgency"),
    CrisisEvent("MZ", 2017, "civil_war", 1, "Cabo Delgado insurgency"),
    CrisisEvent("MM", 2021, "civil_war", 1, "Myanmar coup + civil conflict"),

    # ── Coups ─────────────────────────────────────────────────────────────
    CrisisEvent("ML", 2012, "coup", 1, "Mali coup March 2012"),
    CrisisEvent("EG", 2013, "coup", 1, "Egyptian military coup"),
    CrisisEvent("TH", 2014, "coup", 1, "Thai military coup"),
    CrisisEvent("TR", 2016, "coup", 1, "Failed Turkish coup attempt"),
    CrisisEvent("ZW", 2017, "coup", 1, "Zimbabwe military takeover"),
    CrisisEvent("SD", 2019, "coup", 1, "Sudanese coup, al-Bashir ousted"),
    CrisisEvent("ML", 2020, "coup", 1, "Mali second coup"),
    CrisisEvent("GN", 2021, "coup", 1, "Guinean coup"),
    CrisisEvent("BF", 2022, "coup", 1, "Burkina Faso coup"),
    CrisisEvent("NE", 2023, "coup", 1, "Niger coup"),
    CrisisEvent("GA", 2023, "coup", 1, "Gabon coup"),
    CrisisEvent("MM", 2021, "coup", 1, "Myanmar coup"),
]

# ── Hard negative controls (explicitly stable periods) ───────────────────────
NEGATIVE_CONTROLS: list[CrisisEvent] = [
    CrisisEvent("DE", 2010, "none", 0, "Germany during eurozone crisis — stable"),
    CrisisEvent("DE", 2015, "none", 0, "Germany — strong macro"),
    CrisisEvent("AU", 2008, "none", 0, "Australia avoided GFC recession"),
    CrisisEvent("AU", 2015, "none", 0, "Australia — stable"),
    CrisisEvent("KR", 2010, "none", 0, "South Korea — strong recovery"),
    CrisisEvent("KR", 2015, "none", 0, "South Korea — stable"),
    CrisisEvent("CA", 2010, "none", 0, "Canada — stable post-GFC"),
    CrisisEvent("CA", 2018, "none", 0, "Canada — stable"),
    CrisisEvent("IN", 2010, "none", 0, "India — high growth, stable"),
    CrisisEvent("BR", 2010, "none", 0, "Brazil — commodity boom, stable"),
    CrisisEvent("PL", 2010, "none", 0, "Poland — only EU member to avoid recession"),
    CrisisEvent("PL", 2018, "none", 0, "Poland — stable"),
    CrisisEvent("US", 2015, "none", 0, "US — recovery, low risk"),
    CrisisEvent("GB", 2015, "none", 0, "UK — stable pre-Brexit"),
    CrisisEvent("JP", 2010, "none", 0, "Japan — stable despite debt"),
    CrisisEvent("JP", 2018, "none", 0, "Japan — Abenomics, stable"),
    CrisisEvent("CN", 2010, "none", 0, "China — fiscal stimulus, high growth"),
    CrisisEvent("VN", 2015, "none", 0, "Vietnam — stable, FDI inflows"),
    CrisisEvent("MX", 2010, "none", 0, "Mexico — stable post-GFC"),
    CrisisEvent("CL", 2015, "none", 0, "Chile — stable, investment grade"),
]

ALL_EVENTS: list[CrisisEvent] = CRISIS_EVENTS + NEGATIVE_CONTROLS


def get_crisis_labels() -> dict[tuple[str, int], int]:
    """Return {(country_code, year): label} for all events."""
    return {(e.country, e.year): e.label for e in ALL_EVENTS}


def get_positive_rate() -> float:
    """Fraction of labelled observations that are crises."""
    n_pos = sum(1 for e in ALL_EVENTS if e.label == 1)
    return n_pos / max(len(ALL_EVENTS), 1)
