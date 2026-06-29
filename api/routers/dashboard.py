"""
Dashboard â€” Mac OS System 6/7 / HyperCard aesthetic.
Routes:
  GET /                  â€” landing page
  GET /dashboard         â€” risk heatmap
  GET /dashboard/{code}  â€” country detail
  GET /methodology       â€” methodology & calibration (HTML)
  GET /api               â€” API reference (HTML)
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from api.dependencies import get_db
from api.models.database import CountryScore, CentralBankStatement

log = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

_COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "DE": "Germany", "FR": "France",
    "JP": "Japan", "CN": "China", "BR": "Brazil", "IN": "India", "RU": "Russia",
    "ZA": "South Africa", "MX": "Mexico", "AR": "Argentina", "NG": "Nigeria",
    "TR": "Turkey", "UA": "Ukraine", "KE": "Kenya", "EG": "Egypt", "ID": "Indonesia",
    "KR": "South Korea", "AU": "Australia", "CA": "Canada", "IT": "Italy",
    "ES": "Spain", "PL": "Poland", "VE": "Venezuela", "CO": "Colombia",
    "CL": "Chile", "PE": "Peru", "GH": "Ghana", "ET": "Ethiopia", "SA": "Saudi Arabia",
    "GR": "Greece", "NL": "Netherlands", "HU": "Hungary", "CH": "Switzerland",
    "MA": "Morocco", "MY": "Malaysia", "LK": "Sri Lanka", "LB": "Lebanon",
    "PK": "Pakistan", "BD": "Bangladesh", "VN": "Vietnam", "PH": "Philippines",
    "TH": "Thailand",
}


def _risk_label(v):
    if v is None: return "N/A"
    if v < 20:    return "VERY LOW"
    if v < 40:    return "LOW"
    if v < 60:    return "MODERATE"
    if v < 75:    return "HIGH"
    if v < 90:    return "VERY HIGH"
    return "CRITICAL"


def _risk_dc(v):
    """CSS dither class â€” density encodes risk level."""
    if v is None or v < 20: return "dvl"
    if v < 40: return "dlo"
    if v < 60: return "dmd"
    if v < 75: return "dhi"
    return "dvh"


def _fmt(v):
    return f"{v:.1f}" if v is not None else "â€”"


# â”€â”€ Geography (approx centroids) + region grouping for the ASCII terminal â”€â”€â”€â”€â”€
GEO: dict[str, tuple[float, float, str]] = {
    "US": (38, -97, "N. America"),  "CA": (56, -106, "N. America"), "MX": (23, -102, "N. America"),
    "BR": (-10, -55, "S. America"), "AR": (-34, -64, "S. America"), "CO": (4, -72, "S. America"),
    "CL": (-30, -71, "S. America"), "PE": (-10, -76, "S. America"), "VE": (8, -66, "S. America"),
    "DE": (51, 10, "Europe"),       "GB": (54, -2, "Europe"),       "FR": (46, 2, "Europe"),
    "IT": (42, 12, "Europe"),       "ES": (40, -4, "Europe"),       "GR": (39, 22, "Europe"),
    "NL": (52, 5, "Europe"),        "HU": (47, 19, "Europe"),       "CH": (47, 8, "Europe"),
    "PL": (52, 19, "Europe"),       "UA": (49, 32, "Europe"),       "RU": (61, 90, "Europe"),
    "TR": (39, 35, "MENA"),         "SA": (24, 45, "MENA"),         "EG": (26, 30, "MENA"),
    "MA": (32, -6, "MENA"),         "LB": (34, 36, "MENA"),
    "ZA": (-30, 25, "Sub-Saharan"), "NG": (9, 8, "Sub-Saharan"),    "KE": (0, 38, "Sub-Saharan"),
    "ET": (9, 40, "Sub-Saharan"),   "GH": (8, -1, "Sub-Saharan"),
    "CN": (35, 105, "Asia-Pacific"),"JP": (36, 138, "Asia-Pacific"),"KR": (37, 128, "Asia-Pacific"),
    "IN": (22, 79, "Asia-Pacific"), "ID": (-2, 118, "Asia-Pacific"),"PK": (30, 70, "Asia-Pacific"),
    "BD": (24, 90, "Asia-Pacific"), "VN": (16, 108, "Asia-Pacific"),"PH": (13, 122, "Asia-Pacific"),
    "TH": (15, 100, "Asia-Pacific"),"MY": (4, 102, "Asia-Pacific"), "LK": (7, 81, "Asia-Pacific"),
    "AU": (-25, 133, "Asia-Pacific"),
}

_REGION_ORDER = ["N. America", "S. America", "Europe", "MENA", "Sub-Saharan", "Asia-Pacific"]


def _band_cls(v) -> str:
    """Terminal colour class by risk band."""
    if v is None or v < 20: return "b0"
    if v < 40: return "b1"
    if v < 60: return "b2"
    if v < 75: return "b3"
    return "b4"


def _ascii_bar(v, width: int = 22) -> str:
    val = 0.0 if v is None else max(0.0, min(100.0, float(v)))
    fill = int(round(val / 100 * width))
    return "â–ˆ" * fill + "â–‘" * (width - fill)


def _latest_per_country(rows: list) -> list:
    seen: dict = {}
    for r in rows:
        if r.country_code not in seen:
            seen[r.country_code] = r
    return sorted(seen.values(), key=lambda r: r.composite, reverse=True)


def _detect_movers(rows: list, days: int = 7) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    by_country: dict = {}
    for r in rows:
        by_country.setdefault(r.country_code, []).append(r)
    movers = []
    for code, scores in by_country.items():
        recent = [s for s in scores if s.computed_at and s.computed_at.replace(tzinfo=timezone.utc) >= cutoff]
        old = [s for s in scores if not recent or s.computed_at < recent[-1].computed_at]
        if not recent or not old:
            continue
        latest = max(recent, key=lambda s: s.computed_at)
        earliest = min(old, key=lambda s: s.computed_at)
        delta = latest.composite - earliest.composite
        if abs(delta) >= 5:
            movers.append((code, round(delta, 1), "up" if delta > 0 else "down"))
    movers.sort(key=lambda m: -abs(m[1]))
    return movers[:5]


# â”€â”€ CSS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_STYLE = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}

body{
  font-family:-apple-system,"Segoe UI",Geneva,Verdana,Arial,sans-serif;
  font-size:12px;line-height:1.35;
  background:#808080;
  color:#000;
  min-height:100vh;
}

/* â”€â”€ Dither fills (density = risk level) â”€â”€ */
.dvl{background:#fff}
.dlo{background:#fff;background-image:radial-gradient(#000 1px,transparent 0);background-size:4px 4px}
.dmd{background:conic-gradient(#000 25%,#fff 0 50%,#000 50% 75%,#fff 75%);background-size:4px 4px}
.dhi{background:#000;background-image:radial-gradient(#fff 1.2px,transparent 0);background-size:4px 4px}
.dvh{background:#000}

/* â”€â”€ Titlebar pinstripe â”€â”€ */
.stripe{background:repeating-linear-gradient(to bottom,#000 0,#000 1px,#fff 1px,#fff 2px)}

/* â”€â”€ Menu bar â”€â”€ */
.menubar{
  position:sticky;top:0;z-index:200;
  background:#fff;border-bottom:1px solid #000;
  height:20px;display:flex;align-items:center;
  padding:0 6px;font-size:12px;font-weight:bold;user-select:none;
}
.apple{font-size:14px;margin-right:10px;cursor:default}
.mi{padding:0 10px;height:20px;display:flex;align-items:center;cursor:default;white-space:nowrap}
.mi:hover{background:#000;color:#fff}
.mi-r{margin-left:auto;font-weight:normal;font-size:10px;color:#555;cursor:default}

/* â”€â”€ Desktop â”€â”€ */
.desktop{
  padding:14px;display:flex;flex-direction:column;
  align-items:center;min-height:calc(100vh - 20px);
}

/* â”€â”€ Window â”€â”€ */
.window{
  background:#fff;border:1px solid #000;
  box-shadow:2px 2px 0 #000;
  width:100%;max-width:1160px;
  display:flex;flex-direction:column;
}

/* â”€â”€ Title bar â”€â”€ */
.titlebar{
  flex:none;height:19px;border-bottom:1px solid #000;
  display:flex;align-items:center;padding:0 3px;gap:3px;
  background:repeating-linear-gradient(to bottom,#000 0,#000 1px,#fff 1px,#fff 2px);
  cursor:default;user-select:none;
}
.closebox{
  width:13px;height:13px;border:1px solid #000;background:#fff;
  flex:none;cursor:pointer;
}
.closebox:hover{background:#000}
.titletext{
  flex:1;text-align:center;background:#fff;padding:0 6px;
  font-size:12px;font-weight:bold;line-height:13px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.zoombox{
  width:13px;height:13px;border:1px solid #000;background:#fff;
  flex:none;display:flex;align-items:center;justify-content:center;
  font-size:8px;font-weight:bold;
}

/* â”€â”€ Status bar â”€â”€ */
.statbar{
  flex:none;background:#fff;border-bottom:1px solid #000;
  padding:3px 8px;display:flex;justify-content:space-between;
  font-size:11px;
}
.ldot{
  display:inline-block;width:6px;height:6px;border-radius:50%;
  background:#000;vertical-align:middle;margin-right:4px;
  animation:bl 2s infinite;
}
@keyframes bl{0%,100%{opacity:1}50%{opacity:.1}}

/* â”€â”€ Legend â”€â”€ */
.legend{
  flex:none;display:flex;gap:14px;flex-wrap:wrap;
  padding:4px 8px;border-bottom:1px solid #000;
  background:#e8e8e8;font-size:10px;
}
.lg{display:flex;align-items:center;gap:4px}
.lsw{display:inline-block;width:12px;height:8px;border:1px solid #000;flex:none}

/* â”€â”€ Alert â”€â”€ */
.alert{
  flex:none;border-bottom:1px solid #000;padding:4px 8px;
  font-size:11px;font-weight:bold;
  background:conic-gradient(#000 25%,#fff 0 50%,#000 50% 75%,#fff 75%);
  background-size:4px 4px;
}

/* â”€â”€ Table â”€â”€ */
.tbl-wrap{flex:1;overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:820px}

thead th{
  background:repeating-linear-gradient(to bottom,#fff 0,#fff 1px,#000 1px,#000 2px);
  border-bottom:2px solid #000;border-right:1px solid #555;
  padding:3px 8px;font-size:11px;font-weight:bold;
  text-align:left;white-space:nowrap;cursor:pointer;user-select:none;
}
thead th:last-child{border-right:none}
thead th:hover{background:#000;color:#fff;background-image:none}

tbody tr{border-bottom:1px solid #d0d0d0;cursor:default}
tbody tr:hover,tbody tr:hover td{background:#000;color:#fff}
tbody tr:hover .cn,tbody tr:hover .subval,tbody tr:hover .ci-s{color:#bbb}
tbody tr:hover .risk-track{border-color:#fff}
tbody tr:hover .chip{border-color:#555;color:#bbb;background:#000}
tbody tr:hover a{color:#fff}
tbody tr:hover .conf-fill{background:#fff}
tbody tr:hover .conf-track{border-color:#fff}

td{padding:3px 8px;border-right:1px solid #e0e0e0;font-size:11px;vertical-align:middle}
td:last-child{border-right:none}

.cc{font-weight:bold;font-size:12px}
.cn{font-size:10px;color:#555;margin-top:1px}
a{color:#000;text-decoration:none}
a:hover{text-decoration:underline}

/* Score cell */
.score-n{font-size:14px;font-weight:bold}
.ci-s{display:block;font-size:9px;color:#666;margin-top:1px}

/* Level badge */
.lvlb{display:inline-block;border:1px solid #000;padding:1px 5px;font-size:10px;font-weight:bold;white-space:nowrap}
.lvlb.cr{background:#000;color:#fff}
.lvlb.vh{background:repeating-linear-gradient(45deg,#000,#000 2px,#fff 2px,#fff 4px)}

/* Sub-score bar */
.subbar{display:flex;align-items:center;gap:5px}
.risk-track{display:inline-block;width:50px;height:8px;border:1px solid #000;background:#fff;flex:none;position:relative}
.risk-fill{position:absolute;left:0;top:0;bottom:0}
.subval{font-size:10px;color:#555;width:24px}

/* Confidence */
.conf-wrap{display:flex;align-items:center;gap:4px}
.conf-track{display:inline-block;width:38px;height:6px;border:1px solid #555;background:#fff;position:relative;vertical-align:middle}
.conf-fill{position:absolute;left:0;top:0;bottom:0;background:#000}

/* Chips */
.chips{display:flex;flex-wrap:wrap;gap:2px;max-width:200px}
.chip{border:1px solid #000;padding:0 4px;font-size:9px;background:#fff;white-space:nowrap}

/* â”€â”€ Footer strip â”€â”€ */
.winfooter{
  flex:none;border-top:1px solid #aaa;background:#e8e8e8;
  padding:3px 8px;font-size:10px;color:#555;
  display:flex;justify-content:space-between;
}

/* â”€â”€ Empty state â”€â”€ */
.empty{text-align:center;padding:40px;font-size:12px;color:#555}
.empty code{border:1px solid #aaa;padding:0 4px;background:#f8f8f8;font-family:Monaco,monospace;font-size:10px}

/* â”€â”€ Tab bar (HyperCard) â”€â”€ */
.tabbar{
  flex:none;border-top:2px solid #000;background:#808080;
  display:flex;gap:2px;padding:4px 6px 0;flex-wrap:wrap;
}
.tab{
  border:1px solid #000;border-bottom:none;background:#fff;
  padding:3px 12px;font-size:11px;font-weight:bold;
  text-decoration:none;color:#000;display:inline-block;white-space:nowrap;
}
.tab:hover,.tab.on{background:#000;color:#fff}
.tab-gap{flex:1}
.tab.site{background:#1f5f3a;color:#fff;border-color:#000}
.tab.site:hover{background:#000;color:#fff}

/* â”€â”€ Detail page â”€â”€ */
.d-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));border-bottom:1px solid #000}
.d-panel{border-right:1px solid #aaa;border-bottom:1px solid #aaa;padding:10px}
.d-ptitle{font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:.04em;
  border-bottom:1px solid #ccc;margin-bottom:8px;padding-bottom:3px;color:#333}
.big-score{font-size:38px;font-weight:bold;line-height:1;font-variant-numeric:tabular-nums}
.d-row{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #eee;font-size:11px}
.d-row:last-child{border-bottom:none}
.d-label{color:#555}
.d-val{font-weight:bold}
.chart-panel{padding:10px}
.chart-title{font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:.04em;color:#333;margin-bottom:8px}

/* â”€â”€ Comparison / map viz cards â”€â”€ */
.vrow{display:flex;flex-wrap:wrap}
.vcard{flex:1;min-width:300px;border-right:1px solid #000;border-bottom:1px solid #000;padding:12px}
.vcard:last-child{border-right:none}
.vh2{font-size:11px;font-weight:bold;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;color:#222}
.vsub{font-size:10px;color:#666;margin-bottom:8px;line-height:1.45}
.preset{display:inline-block;border:1px solid #000;background:#fff;padding:2px 8px;font-size:10px;margin:0 4px 4px 0;text-decoration:none;color:#000}
.preset:hover{background:#000;color:#fff;text-decoration:none}
.preset.on{background:#000;color:#fff}
.clegend{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 4px}
.cl{display:inline-flex;align-items:center;gap:5px;font-size:10px}
.csw{width:12px;height:12px;border:1px solid #000;display:inline-block;flex:none}
.ctbl{width:100%;border-collapse:collapse;min-width:auto;font-size:11px}
.ctbl th{background:#e8e8e8;border-bottom:2px solid #000;padding:3px 6px;text-align:left;font-size:10px;cursor:default}
.ctbl td{padding:3px 6px;border-bottom:1px solid #ddd}
.heat{width:100%;border-collapse:collapse;min-width:auto;font-size:11px}
.heat th{background:#e8e8e8;border-bottom:2px solid #000;padding:3px 6px;font-size:10px;cursor:default}
.heat td{padding:3px 6px;border-bottom:1px solid #fff;border-right:1px solid #fff}
svg.sparkline{display:block;width:100%}
.dl-bar{border-top:1px solid #aaa;background:#e8e8e8;padding:4px 8px;display:flex;gap:14px;flex-wrap:wrap}
.dl-bar a{font-size:11px;color:#000}

/* â”€â”€ Shared content sections â”€â”€ */
.m-sect{border-bottom:1px solid #ccc}
.m-sect:last-child{border-bottom:none}
.m-sect-hdr{
  font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:.08em;
  padding:5px 8px;background:#e8e8e8;border-bottom:1px solid #aaa;color:#333;
  display:flex;justify-content:space-between;align-items:center;
}
.m-sect-body{padding:10px 12px}
.m-tbl{width:100%;border-collapse:collapse;font-size:11px}
.m-tbl th{
  background:repeating-linear-gradient(to bottom,#fff 0,#fff 1px,#000 1px,#000 2px);
  border-bottom:2px solid #000;border-right:1px solid #555;
  padding:4px 10px;font-size:10px;font-weight:bold;text-align:left;white-space:nowrap;
}
.m-tbl th:last-child{border-right:none}
.m-tbl td{padding:4px 10px;border-bottom:1px solid #e8e8e8;border-right:1px solid #e8e8e8;vertical-align:top}
.m-tbl td:last-child{border-right:none}
.m-tbl tbody tr:hover{background:#f0f0f0}
.m-tbl tbody tr:last-child td{border-bottom:none}
.mono{font-family:Monaco,"Courier New",monospace;font-size:10px}
.badge{display:inline-block;border:1px solid #000;padding:1px 6px;font-size:9px;font-weight:bold;white-space:nowrap}
.badge.get{background:#e8f0ff;border-color:#336}
.badge.post{background:#e8ffe8;border-color:#363}
.badge.del{background:#ffe8e8;border-color:#633}
.infobox{border:1px solid #aaa;background:#f8f8f8;padding:8px 10px;font-size:11px;line-height:1.6;margin:6px 0}
.infobox.warn{background:#fffbe8;border-color:#cc9900}
.pill-band{display:inline-block;border:1px solid #000;padding:1px 6px;font-size:10px;font-weight:bold;margin-right:4px;font-family:Monaco,monospace}
.doc-pre{
  background:#000;color:#c8d0d8;font-family:Monaco,"Courier New",monospace;
  font-size:10px;line-height:1.6;padding:10px;overflow:auto;margin:6px 0;
}
.doc-pre .k{color:#7fdbca}.doc-pre .v{color:#f5a97f}.doc-pre .s{color:#aedea7}.doc-pre .g{color:#556}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:0}
.two-col>*{border-right:1px solid #ccc}
.two-col>*:last-child{border-right:none}
.param-name{font-family:Monaco,"Courier New",monospace;font-size:10px;font-weight:bold;color:#333}
.param-type{font-size:10px;color:#666;font-style:italic}
.wt-bar{display:inline-block;height:8px;background:#000;vertical-align:middle;margin-left:6px}
.risk-band-row{display:flex;align-items:center;padding:5px 10px;border-bottom:1px solid #eee;font-size:11px}
.risk-band-row:last-child{border-bottom:none}
.risk-band-row:hover{background:#f0f0f0}
.band-swatch{width:18px;height:10px;border:1px solid #000;flex:none;margin-right:8px}
.band-range{font-family:Monaco,monospace;font-size:10px;width:60px;flex:none;margin-right:10px}
.band-label{font-weight:bold;width:80px;flex:none}
.band-desc{color:#555;font-size:11px}
.scrollable{overflow-y:auto;max-height:480px}

/* â”€â”€ Landing page â”€â”€ */
.hero{display:grid;grid-template-columns:1fr 1fr;gap:0;border-bottom:1px solid #000}
.hero-l{padding:20px;border-right:1px solid #000}
.hero-h1{font-size:22px;font-weight:bold;line-height:1.2;margin-bottom:6px}
.hero-rule{border:none;border-top:1px solid #000;margin:8px 0}
.cbx-row{font-size:12px;margin:8px 0;display:flex;align-items:center;gap:5px}
.cbx{display:inline-block;width:11px;height:11px;border:1px solid #000;background:#fff;flex:none}
.intro{font-size:11px;color:#333;line-height:1.65;margin:10px 0 16px}
.mac-btn{
  display:inline-block;border:1px solid #000;
  padding:4px 14px;font-size:12px;font-weight:bold;
  text-decoration:none;color:#000;background:#fff;
  box-shadow:2px 2px 0 #000;margin:0 4px 4px 0;
}
.mac-btn:hover{background:#000;color:#fff;box-shadow:none;text-decoration:none}
.mac-btn.def{outline:3px solid #000;outline-offset:2px}
.hero-r{background:#000;padding:0;display:flex;flex-direction:column}
.code-win{
  background:#000;color:#c8d0d8;
  font-family:"Monaco","Courier New",monospace;font-size:11px;
  padding:16px;line-height:1.6;overflow:auto;flex:1;
}
.code-win .k{color:#7fdbca}.code-win .v{color:#f5a97f}
.code-win .s{color:#aedea7}.code-win .g{color:#556}

/* Feature grid */
.feat-hdr{
  font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:.1em;
  padding:5px 8px;border-bottom:1px solid #000;border-top:1px solid #000;
  background:#e8e8e8;color:#333;
}
.feat-grid{display:grid;grid-template-columns:repeat(3,1fr)}
.fc{padding:12px;border-right:1px solid #000;border-bottom:1px solid #000;background:#fff}
.fc:nth-child(3n){border-right:none}
.fc:nth-last-child(-n+3){border-bottom:none}
.fc-h{font-size:11px;font-weight:bold;margin-bottom:5px}
.fc-h::before{content:"â–¡ "}
.fc:hover .fc-h::before{content:"â–  "}
.fc:hover{background:#f8f8f8}
.fc-p{font-size:11px;color:#444;line-height:1.5}

@media(max-width:760px){
  .hero{grid-template-columns:1fr}
  .hero-r{min-height:180px}
  .feat-grid{grid-template-columns:1fr 1fr}
  .fc:nth-child(3n){border-right:1px solid #000}
  .fc:nth-child(2n){border-right:none}
}
@media(max-width:480px){
  .feat-grid{grid-template-columns:1fr}.fc{border-right:none}
  .tab{padding:3px 8px;font-size:10px}
}
"""


def _head(title: str) -> str:
    return (
        f'<!DOCTYPE html><html lang="en"><head>'
        f'<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title>'
        f'<style>{_STYLE}</style></head>'
    )


def _menubar(items: list[str], right: str = "VisibleHand v0.3") -> str:
    mis = "".join(f'<span class="mi">{i}</span>' for i in items)
    return f'<div class="menubar"><span class="apple">&#x2318;</span>{mis}<span class="mi-r">{right}</span></div>'


def _titlebar(title: str, close_href: str = "/") -> str:
    return (
        f'<div class="titlebar">'
        f'<div class="closebox" onclick="location=\'{close_href}\'"></div>'
        f'<div class="titletext">{title}</div>'
        f'<div class="zoombox">&#x25B8;</div>'
        f'</div>'
    )


SITE_URL = "https://visiblehand.xyz"


def _tabbar(tabs: list[tuple[str, str]], active: str = "") -> str:
    out = '<div class="tabbar">'
    has_gap = any(not href for _, href in tabs)
    for i, (label, href) in enumerate(tabs):
        cls = "tab on" if label == active else "tab"
        if href:
            out += f'<a class="{cls}" href="{href}">{label}</a>'
        else:
            out += f'<span class="tab-gap"></span>'
    # Always pin a link back to the consumer website on the far right.
    ml = "" if has_gap else ' style="margin-left:auto"'
    out += (f'<a class="tab site" href="{SITE_URL}" target="_blank" rel="noopener"{ml}>'
            f'&#x2190;&nbsp;visiblehand.xyz</a>')
    out += "</div>"
    return out


def _row_html(r) -> str:
    label = _risk_label(r.composite)
    dc = _risk_dc(r.composite)
    name = _COUNTRY_NAMES.get(r.country_code, r.country_code)

    badge_cls = "lvlb cr" if r.composite >= 90 else ("lvlb vh" if r.composite >= 75 else "lvlb")

    drivers = []
    if r.top_drivers:
        try:
            drivers = json.loads(r.top_drivers)
        except (json.JSONDecodeError, TypeError):
            pass
    chips = "".join(f'<span class="chip">{d.replace("_"," ")}</span>' for d in drivers[:3])
    if not chips:
        chips = '<span class="chip" style="opacity:.4">â€”</span>'

    def bar(v):
        dclass = _risk_dc(v)
        w = max(0, min(100, int(v))) if v is not None else 0
        return (f'<div class="subbar">'
                f'<div class="risk-track"><div class="risk-fill {dclass}" style="width:{w}%"></div></div>'
                f'<span class="subval">{_fmt(v)}</span></div>')

    ci_str = ""
    if r.ci_low is not None and r.ci_high is not None:
        ci_str = f'<span class="ci-s">[{r.ci_low:.0f}â€“{r.ci_high:.0f}]</span>'

    date_str = r.computed_at.date().isoformat() if r.computed_at else "â€”"
    conf_pct = int((r.confidence or 0) * 100)

    return f"""<tr>
  <td data-sort="{r.country_code}">
    <a href="/dashboard/{r.country_code}">
      <div class="cc">{r.country_code}</div><div class="cn">{name}</div>
    </a>
  </td>
  <td data-sort="{r.composite}">
    <span class="score-n">{r.composite:.1f}</span>{ci_str}
  </td>
  <td data-sort="{r.composite}"><span class="{badge_cls}">{label}</span></td>
  <td data-sort="{r.economic or 0}">{bar(r.economic)}</td>
  <td data-sort="{r.political or 0}">{bar(r.political)}</td>
  <td data-sort="{r.nlp_sentiment or 0}">{bar(r.nlp_sentiment)}</td>
  <td data-sort="{r.governance or 0}">{bar(r.governance)}</td>
  <td>
    <div class="conf-wrap">
      <div class="conf-track"><div class="conf-fill" style="width:{conf_pct}%"></div></div>
      <span style="font-size:10px;color:#555">{conf_pct}%</span>
    </div>
  </td>
  <td><div class="chips">{chips}</div></td>
  <td data-sort="{date_str}">
    <a href="/dashboard/{r.country_code}">{date_str}&nbsp;&#x25B8;</a>
  </td>
</tr>"""


def _build_dashboard(rows: list, history_rows: list | None = None) -> str:
    latest = _latest_per_country(rows)
    n = len(latest)
    avg = sum(r.composite for r in latest) / n if n else 0
    highest = latest[0] if latest else None

    movers = _detect_movers(history_rows if history_rows is not None else rows)
    alert_html = ""
    if movers:
        parts = []
        for code, delta, direction in movers:
            sym = "&#x25B2;" if direction == "up" else "&#x25BC;"
            parts.append(f"{code}&nbsp;{sym}&nbsp;{abs(delta):.1f}")
        alert_html = f'<div class="alert">&#x26A0;&nbsp; Movers (7d):&nbsp;&nbsp;{"&nbsp;&nbsp;&#183;&nbsp;&nbsp;".join(parts)}</div>'

    if not latest:
        body = ('<tr><td colspan="10"><div class="empty">'
                'No scores yet â€” seed: <code>python -m scripts.seed_demo_data</code>'
                '&nbsp;&nbsp;then call:&nbsp;&nbsp;<code>/risk/compare?countries=US,BR,AR</code>'
                '</div></td></tr>')
        stat_text = "No data"
    else:
        body = "".join(_row_html(r) for r in latest)
        hl = f"{highest.country_code} {highest.composite:.0f}" if highest else "â€”"
        stat_text = f"{n} items&nbsp;&nbsp;&#183;&nbsp;&nbsp;avg risk {avg:.1f}&nbsp;&nbsp;&#183;&nbsp;&nbsp;highest&nbsp;{hl}"

    _TABS = [
        ("Browse", "/"), ("Dashboard", "/dashboard"),
        ("Compare", "/compare"), ("Map", "/map"), ("Validation", "/validation"),
        ("API", "/api"), ("Methodology", "/methodology"),
        ("", ""), ("Exit", "/"),
    ]

    return _head("VisibleHand â€” Risk Monitor") + f"""
<body>
{_menubar(["File","Edit","View","Sort"])}
<div class="desktop">
<div class="window">
{_titlebar("VisibleHand Risk Monitor â€” Live", "/")}
<div class="statbar">
  <span><span class="ldot"></span>{stat_text}</span>
  <span style="color:#555">auto-refresh 2 min</span>
</div>
{alert_html}
<div class="legend">
  <span style="font-weight:bold">Risk fill:</span>
  <span class="lg"><span class="lsw dvl"></span>Very Low (&lt;20)</span>
  <span class="lg"><span class="lsw dlo"></span>Low (20â€“39)</span>
  <span class="lg"><span class="lsw dmd"></span>Moderate (40â€“59)</span>
  <span class="lg"><span class="lsw dhi"></span>High (60â€“74)</span>
  <span class="lg"><span class="lsw dvh"></span>Very High / Critical (75+)</span>
</div>
<div class="tbl-wrap">
<table id="t">
<thead><tr>
  <th onclick="sT(0,1)">Country</th>
  <th onclick="sT(1)">Score</th>
  <th onclick="sT(2,1)">Level</th>
  <th onclick="sT(3)">Economic</th>
  <th onclick="sT(4)">Political</th>
  <th onclick="sT(5)">NLP</th>
  <th onclick="sT(6)">Governance</th>
  <th onclick="sT(7)">Confidence</th>
  <th>Drivers</th>
  <th onclick="sT(9,1)">Updated</th>
</tr></thead>
<tbody>{body}</tbody>
</table>
</div>
<div class="winfooter">
  <span>Sources: World Bank Â· IMF Â· BIS Â· GDELT/ACLED Â· V-Dem Â· WJP Â· TI Â· Freedom House Â· NLP</span>
  <a href="/methodology">Methodology</a>
</div>
{_tabbar([("Browse","/"),("Dashboard","/dashboard"),("World","/world"),("Terminal","/terminal"),("API","/api"),("",""),("Exit","/")], active="Dashboard")}
</div>
</div>
<script>
function sT(col,txt){{
  var tb=document.querySelector('#t tbody'),rows=[...tb.rows];
  var dir=tb.dataset.d==='a'?-1:1;tb.dataset.d=dir===1?'a':'d';
  rows.sort(function(a,b){{
    var x=a.cells[col]&&a.cells[col].dataset.sort,y=b.cells[col]&&b.cells[col].dataset.sort;
    if(!txt){{return(parseFloat(x||0)-parseFloat(y||0))*dir;}}
    return(x||'').localeCompare(y||'')*dir;
  }});
  rows.forEach(function(r){{tb.appendChild(r);}});
}}
</script>
<meta http-equiv="refresh" content="120">
</body></html>"""


def _build_detail(code: str, rows: list, stmt) -> str:
    if not rows:
        return _head(f"{code} â€” VisibleHand") + f"""
<body>
{_menubar(["File","Edit","Go"])}
<div class="desktop"><div class="window">
{_titlebar(f"VisibleHand â€” {code} â€” No Data", "/dashboard")}
<div style="padding:24px;font-size:12px">
  <a href="/dashboard" style="color:#000">&#x25C2; Back to Dashboard</a><br><br>
  No scores for {code} yet. Call <code>/risk/{code}</code> to compute the first score.
</div>
{_tabbar([("Browse","/"),("Dashboard","/dashboard"),("Terminal","/terminal"),("API","/api"),("Methodology","/methodology"),("",""),("Exit","/")], active="Browse")}
</div></div></body></html>"""

    latest = rows[0]
    name = _COUNTRY_NAMES.get(code, code)
    label = _risk_label(latest.composite)
    dc = _risk_dc(latest.composite)

    history = list(reversed(rows[:30]))
    if len(history) > 1:
        vals = [r.composite for r in history]
        vmin, vmax = min(vals), max(vals)
        rng = max(vmax - vmin, 1.0)
        W, H = 700, 80
        pts = []
        for i, v in enumerate(vals):
            x = i * W / max(len(vals) - 1, 1)
            y = H - (v - vmin) / rng * (H - 6) - 3
            pts.append(f"{x:.1f},{y:.1f}")
        area = f"0,{H} " + " ".join(pts) + f" {W},{H}"
        sparkline = (
            f'<svg class="sparkline" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
            f'<polygon points="{area}" fill="#000" opacity=".12"/>'
            f'<polyline points="{" ".join(pts)}" stroke="#000" stroke-width="1.5" fill="none"/>'
            f'</svg>'
        )
    else:
        sparkline = '<p style="font-size:11px;color:#555">Need 2+ scores for chart.</p>'

    drivers = []
    if latest.top_drivers:
        try:
            drivers = json.loads(latest.top_drivers)
        except Exception:
            pass
    chips = "".join(f'<span class="chip">{d.replace("_"," ")}</span>' for d in drivers)
    if not chips:
        chips = '<span class="chip" style="opacity:.4">none</span>'

    ci_str = ""
    if latest.ci_low is not None and latest.ci_high is not None:
        ci_str = f'<span style="font-size:10px;color:#555"> [{latest.ci_low:.1f}â€“{latest.ci_high:.1f}]</span>'

    forecast_html = ""
    if latest.forecast_6m:
        try:
            f6 = json.loads(latest.forecast_6m)
            f12 = json.loads(latest.forecast_12m) if latest.forecast_12m else None
            forecast_html = '<div class="d-panel"><div class="d-ptitle">Forecast (extrapolation)</div>'
            forecast_html += f'<div class="d-row"><span class="d-label">6 months</span><span class="d-val">{f6["composite"]:.1f} [{f6["ci_low"]:.0f}â€“{f6["ci_high"]:.0f}]</span></div>'
            if f12:
                forecast_html += f'<div class="d-row"><span class="d-label">12 months</span><span class="d-val">{f12["composite"]:.1f} [{f12["ci_low"]:.0f}â€“{f12["ci_high"]:.0f}]</span></div>'
            forecast_html += '<p style="font-size:10px;color:#888;margin-top:6px">Theil-Sen extrapolation â€” not a prediction.</p></div>'
        except Exception:
            pass

    stmt_html = ""
    if stmt:
        s = stmt.sentiment_score or 50
        s_label = "HAWKISH" if s >= 65 else ("NEUTRAL" if s >= 40 else "DOVISH")
        stmt_html = (f'<div class="d-panel"><div class="d-ptitle">Central Bank Signal ({stmt.bank_name})</div>'
                     f'<div class="d-row"><span class="d-label">Sentiment</span><span class="d-val">{s:.0f}/100 Â· {s_label}</span></div>'
                     f'<div class="d-row"><span class="d-label">Date</span><span class="d-val">{stmt.statement_date or "â€”"}</span></div>'
                     f'<p style="margin-top:8px;font-size:10px;color:#555;line-height:1.55;font-style:italic">'
                     f'&ldquo;{(stmt.raw_text or "")[:240]}&hellip;&rdquo;</p></div>')

    date_str = latest.computed_at.date().isoformat() if latest.computed_at else "â€”"

    return _head(f"{code} Risk â€” VisibleHand") + f"""
<body>
{_menubar(["File","Edit","Go"])}
<div class="desktop"><div class="window">
{_titlebar(f"VisibleHand â€” {name} ({code}) â€” Country Risk Detail", "/dashboard")}
<div class="statbar">
  <span><a href="/dashboard" style="color:#000">&#x25C2; All countries</a>&nbsp;&nbsp;&#183;&nbsp;&nbsp;{name}&nbsp;({code})</span>
  <span style="color:#555">{date_str}&nbsp;&nbsp;&#183;&nbsp;&nbsp;confidence {int((latest.confidence or 0)*100)}%</span>
</div>
<div class="d-grid">
  <div class="d-panel">
    <div class="d-ptitle">Composite Risk</div>
    <div>
      <span class="big-score">{latest.composite:.1f}</span>{ci_str}
    </div>
    <div style="margin-top:6px">
      <span class="lvlb {'cr' if latest.composite>=90 else ('vh' if latest.composite>=75 else '')}">{label}</span>
    </div>
    <div style="margin-top:10px">
      <div class="risk-track" style="width:100%;height:14px;display:block">
        <div class="risk-fill {dc}" style="width:{min(100,int(latest.composite))}%"></div>
      </div>
    </div>
    <p style="font-size:10px;color:#777;margin-top:8px">{latest.methodology or ""}</p>
  </div>
  <div class="d-panel">
    <div class="d-ptitle">Sub-Scores</div>
    <div class="d-row"><span class="d-label">Economic</span><span class="d-val">{_fmt(latest.economic)} / 100</span></div>
    <div class="d-row"><span class="d-label">Political</span><span class="d-val">{_fmt(latest.political)} / 100</span></div>
    <div class="d-row"><span class="d-label">NLP (central bank)</span><span class="d-val">{_fmt(latest.nlp_sentiment)} / 100</span></div>
    <div class="d-row"><span class="d-label">Governance</span><span class="d-val">{_fmt(latest.governance)} / 100</span></div>
  </div>
  <div class="d-panel">
    <div class="d-ptitle">Top Risk Drivers</div>
    <div class="chips" style="max-width:none;gap:4px">{chips}</div>
  </div>
  {forecast_html}
  {stmt_html}
</div>
<div class="chart-panel">
  <div class="chart-title">Score History ({len(history)} readings)</div>
  {sparkline}
</div>
<div class="dl-bar">
  <a href="/risk/{code}">Full JSON &#x25B8;</a>
  <a href="/risk/{code}/history">History &#x25B8;</a>
  <a href="/risk/{code}/drivers">Drivers &#x25B8;</a>
  <a href="/risk/{code}/aspects">NLP Aspects &#x25B8;</a>
  <a href="/governance/{code}">Governance &#x25B8;</a>
  <a href="/worldstate/{code}"><b>World-State &#x25B8;</b></a>
</div>
{_tabbar([("Browse","/"),("Dashboard","/dashboard"),("Country",""),("World-State",f"/worldstate/{code}"),("Terminal","/terminal"),("API","/api"),("",""),("Exit","/")], active="Country")}
</div></div></body></html>"""


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(db: Session = Depends(get_db)) -> HTMLResponse:
    from sqlalchemy import func
    # Latest snapshot per country â€” robust no matter how many total snapshots
    # have accumulated (a plain limit() can silently drop countries).
    sub = (
        db.query(
            CountryScore.country_code.label("cc"),
            func.max(CountryScore.computed_at).label("mx"),
        )
        .group_by(CountryScore.country_code)
        .subquery()
    )
    latest_rows = (
        db.query(CountryScore)
        .join(sub, (CountryScore.country_code == sub.c.cc)
                   & (CountryScore.computed_at == sub.c.mx))
        .all()
    )
    # Recent window (7 days) drives the movers ticker.
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    history_rows = (
        db.query(CountryScore)
        .filter(CountryScore.computed_at >= cutoff)
        .order_by(CountryScore.computed_at.desc())
        .limit(4000).all()
    )
    return HTMLResponse(_build_dashboard(latest_rows, history_rows))


@router.get("/dashboard/{country_code}", response_class=HTMLResponse, include_in_schema=False)
async def country_detail(country_code: str, db: Session = Depends(get_db)) -> HTMLResponse:
    code = country_code.upper()
    rows = (
        db.query(CountryScore)
        .filter(CountryScore.country_code == code)
        .order_by(CountryScore.computed_at.desc())
        .limit(60).all()
    )
    stmt = (
        db.query(CentralBankStatement)
        .filter(CentralBankStatement.country_code == code)
        .order_by(CentralBankStatement.fetched_at.desc())
        .first()
    )
    return HTMLResponse(_build_detail(code, rows, stmt))


# â”€â”€ VH-WSM World-State page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# â”€â”€ Data-viz helpers (vintage palette, inline SVG) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_VIZ_PALETTE = ["#5d7c4f", "#8f9a45", "#cf9f24", "#c2702a", "#a8322f"]  # vlow..vhigh
_HAZARD_ORDER = ["sovereign_default", "currency_crisis", "imf_programme",
                 "banking_crisis", "civil_conflict", "coup",
                 "sanctions_shock", "political_instability"]
_HAZARD_ABBR = {"sovereign_default": "DEFAULT", "currency_crisis": "FX",
                "imf_programme": "IMF", "banking_crisis": "BANK",
                "civil_conflict": "WAR", "coup": "COUP",
                "sanctions_shock": "SANC", "political_instability": "POLIT"}


def _risk_color(v) -> str:
    if v is None:
        return "#9a9a9a"
    if v < 20: return _VIZ_PALETTE[0]
    if v < 40: return _VIZ_PALETTE[1]
    if v < 60: return _VIZ_PALETTE[2]
    if v < 75: return _VIZ_PALETTE[3]
    return _VIZ_PALETTE[4]


def _svg_radar(items: list[tuple[str, float]], size: int = 300) -> str:
    """Spider chart. items = [(label, frac 0..1)]."""
    import math
    cx, cy, R = size / 2, size / 2, size * 0.30
    n = max(1, len(items))
    ang = lambda i: -math.pi / 2 + 2 * math.pi * i / n
    rings = ""
    for rr in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{cx+math.cos(ang(i))*R*rr:.1f},{cy+math.sin(ang(i))*R*rr:.1f}"
                       for i in range(n))
        rings += f'<polygon points="{pts}" fill="none" stroke="#d2d2cf" stroke-width="0.7"/>'
    axes = labels = dots = ""
    for i, (lab, frac) in enumerate(items):
        a = ang(i)
        axes += (f'<line x1="{cx}" y1="{cy}" x2="{cx+math.cos(a)*R:.1f}" '
                 f'y2="{cy+math.sin(a)*R:.1f}" stroke="#e0e0dc" stroke-width="0.7"/>')
        lx, ly = cx + math.cos(a) * (R + 16), cy + math.sin(a) * (R + 16) + 3
        anchor = "middle"
        if math.cos(a) > 0.3: anchor = "start"
        elif math.cos(a) < -0.3: anchor = "end"
        labels += (f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="8" text-anchor="{anchor}" '
                   f'font-family="monospace" fill="#444">{lab}</text>')
        f = max(0.0, min(1.0, frac))
        dots += (f'<circle cx="{cx+math.cos(a)*R*f:.1f}" cy="{cy+math.sin(a)*R*f:.1f}" '
                 f'r="2" fill="#111"/>')
    poly = " ".join(
        f"{cx+math.cos(ang(i))*R*max(0,min(1,frac)):.1f},"
        f"{cy+math.sin(ang(i))*R*max(0,min(1,frac)):.1f}"
        for i, (lab, frac) in enumerate(items))
    return (f'<svg viewBox="0 0 {size} {size}" width="100%" style="max-width:300px">'
            f'{rings}{axes}'
            f'<polygon points="{poly}" fill="rgba(168,50,47,0.18)" '
            f'stroke="#a8322f" stroke-width="1.5"/>{dots}{labels}</svg>')


def _svg_gauge(score: float, ci=None, conformal=None) -> str:
    """0-100 number line with risk bands, CI whiskers, conformal shading, marker."""
    W, x0, x1, y = 360, 16, 344, 38
    X = lambda v: x0 + (x1 - x0) * max(0.0, min(100.0, v)) / 100.0
    segs = [(0, 20, _VIZ_PALETTE[0]), (20, 40, _VIZ_PALETTE[1]), (40, 60, _VIZ_PALETTE[2]),
            (60, 75, _VIZ_PALETTE[3]), (75, 100, _VIZ_PALETTE[4])]
    bar = "".join(f'<rect x="{X(a):.1f}" y="{y-4}" width="{X(b)-X(a):.1f}" height="8" '
                  f'fill="{c}" opacity="0.6"/>' for a, b, c in segs)
    band = ""
    if conformal and conformal[0] is not None:
        band = (f'<rect x="{X(conformal[0]):.1f}" y="{y-12}" '
                f'width="{X(conformal[1])-X(conformal[0]):.1f}" height="24" '
                f'fill="#000" opacity="0.10"/>')
    ci_el = ""
    if ci and ci[0] is not None:
        ci_el = (f'<line x1="{X(ci[0]):.1f}" y1="{y-6}" x2="{X(ci[0]):.1f}" y2="{y+6}" stroke="#000"/>'
                 f'<line x1="{X(ci[1]):.1f}" y1="{y-6}" x2="{X(ci[1]):.1f}" y2="{y+6}" stroke="#000"/>'
                 f'<line x1="{X(ci[0]):.1f}" y1="{y}" x2="{X(ci[1]):.1f}" y2="{y}" '
                 f'stroke="#000" stroke-width="0.7" opacity="0.5"/>')
    mark = (f'<line x1="{X(score):.1f}" y1="{y-15}" x2="{X(score):.1f}" y2="{y+15}" '
            f'stroke="#000" stroke-width="2"/>'
            f'<circle cx="{X(score):.1f}" cy="{y}" r="4.5" fill="{_risk_color(score)}" stroke="#000"/>'
            f'<text x="{X(score):.1f}" y="{y-19}" font-size="11" font-weight="bold" '
            f'text-anchor="middle" font-family="monospace">{score:.1f}</text>')
    ticks = "".join(
        f'<line x1="{X(t):.1f}" y1="{y+6}" x2="{X(t):.1f}" y2="{y+9}" stroke="#aaa"/>'
        f'<text x="{X(t):.1f}" y="{y+19}" font-size="7" text-anchor="middle" '
        f'fill="#777" font-family="monospace">{t}</text>' for t in (0, 20, 40, 60, 75, 90, 100))
    return f'<svg viewBox="0 0 {W} 64" width="100%" style="max-width:440px">{band}{bar}{ci_el}{mark}{ticks}</svg>'


def _sim_meter(frac: float) -> str:
    w = max(0, min(100, int(round(frac * 100))))
    return (f'<div style="display:inline-block;width:90px;height:8px;background:#e6e6e2;'
            f'border:1px solid #000;vertical-align:middle">'
            f'<div style="width:{w}%;height:100%;background:#3a5a8c"></div></div>')


def _haz_bar(prob: float) -> str:
    pct = max(0, min(100, int(round((prob or 0) * 100))))
    col = _risk_color(pct)
    return (f'<div style="display:flex;align-items:center;gap:6px">'
            f'<div style="flex:1;height:11px;background:#e6e6e2;border:1px solid #000">'
            f'<div style="width:{pct}%;height:100%;background:{col}"></div></div>'
            f'<span class="mono" style="width:34px;text-align:right">{(prob or 0)*100:.0f}%</span></div>')


def _build_worldstate(code: str, st: dict) -> str:
    name = _COUNTRY_NAMES.get(code, code)
    bs = st["base_score"]; comp = bs.get("components", {})
    ws = st["world_state"]; meta = st["model_metadata"]
    unc = st["uncertainty"]
    haz = st.get("hazards_12m", {}) or {}
    cal = st.get("hazards_model", {}).get("calibration_status", "experimental")

    score = bs.get("score") or 0
    ci = bs.get("ci_95")
    cf = unc.get("conformal_90")
    gauge = _svg_gauge(score, ci=ci, conformal=cf)
    radar = _svg_radar([(_HAZARD_ABBR[t], haz.get(t) or 0.0) for t in _HAZARD_ORDER])

    # hazard bar list (sorted desc)
    haz_rows = ""
    for t, p in sorted(haz.items(), key=lambda kv: (kv[1] is None, -(kv[1] or 0))):
        haz_rows += (f'<tr><td class="mono" style="white-space:nowrap">{t.replace("_"," ").title()}</td>'
                     f'<td style="width:60%">{_haz_bar(p)}</td></tr>')

    # analogues with similarity meters
    an_rows = ""
    for a in st.get("nearest_analogues", []):
        out = a.get("outcome_12m")
        out_html = (f'<span class="badge del">{out}</span>' if out else '<span style="color:#999">â€”</span>')
        an_rows += (f'<tr><td>{a["rank"]}</td>'
                    f'<td class="mono"><a href="/worldstate/{a["country"]}">{a["country"]}</a></td>'
                    f'<td class="mono">{a["date"]}</td>'
                    f'<td>{_sim_meter(a["similarity"])} <span class="mono">{a["similarity"]:.2f}</span></td>'
                    f'<td>{out_html}</td></tr>')
    if not an_rows:
        an_rows = '<tr><td colspan="5" style="color:#666">No analogues (insufficient history)</td></tr>'

    # spillover bars
    sp = st.get("spillover", {}) or {}
    sp_rows = ""
    for kk, vv in sp.items():
        if isinstance(vv, bool):
            disp = ('<span class="badge del">YES</span>' if vv else '<span class="badge">no</span>')
        elif isinstance(vv, (int, float)):
            disp = f'<span class="d-val">{vv:.1f}</span>' if vv > 1.5 else f'<span class="d-val">{vv:.2f}</span>'
        else:
            disp = f'<span class="d-val">{vv}</span>'
        sp_rows += f'<div class="d-row"><span class="d-label">{kk.replace("_"," ")}</span>{disp}</div>'

    conf = bs.get("confidence")
    conf_txt = f"{conf:.2f}" if isinstance(conf, (int, float)) else "â€”"
    cf_txt = f"[{cf[0]:.1f}, {cf[1]:.1f}]" if cf else "â€”"
    cov = unc.get("empirical_coverage")
    abstain = unc.get("abstain")
    abstain_html = (
        f'<div class="infobox warn">&#9888; ABSTAIN â€” {"; ".join(unc.get("abstain_reasons", []))}</div>'
        if abstain else
        '<div class="infobox">Output is within confidence thresholds (no abstention).</div>'
    )

    def comp_cell(v):
        return f"{v:.1f}" if isinstance(v, (int, float)) else "â€”"

    return _head(f"World-State â€” {name}") + f"""
<body>
{_menubar(["File","Edit","Go"])}
<div class="desktop"><div class="window">
{_titlebar(f"VisibleHand World-State â€” {name}", "/dashboard")}
<div class="statbar">
  <span><span class="ldot"></span>{meta.get('model_version')} &#183; cutoff {meta.get('data_cutoff')} &#183;
  cluster <b>{ws.get('cluster') or 'n/a'}</b> &#183; data-quality {meta.get('data_quality_score')}</span>
  <a href="/state/{code}" style="font-size:10px">raw JSON &#x25B8;</a>
</div>
<div class="scrollable">

<div class="m-sect"><div class="m-sect-hdr">Composite Risk &amp; Uncertainty</div><div class="m-sect-body">
  <div class="two-col">
    <div style="padding:4px 14px 4px 4px">
      <div style="font-size:40px;font-weight:bold;line-height:1;color:{_risk_color(score)}">{score:.1f}</div>
      <div style="font-size:12px;font-weight:bold;letter-spacing:.06em">{bs.get('risk_band')}</div>
      <div style="margin-top:8px">{gauge}</div>
      <div style="font-size:10px;color:#666;margin-top:2px">
        bands &middot; black whiskers = 95% CI &middot; grey band = 90% conformal</div>
    </div>
    <div style="padding:4px">
      <div class="d-row"><span class="d-label">Confidence</span><span class="d-val">{conf_txt}</span></div>
      <div class="d-row"><span class="d-label">Conformal 90%</span><span class="d-val">{cf_txt}</span></div>
      <div class="d-row"><span class="d-label">Coverage</span><span class="d-val">{cov if cov is not None else 'â€”'}</span></div>
      <div class="d-row"><span class="d-label">State cluster</span><span class="d-val">{ws.get('cluster') or 'n/a'} ({(ws.get('cluster_confidence') or 0):.2f})</span></div>
      <div style="margin-top:6px">{abstain_html}</div>
    </div>
  </div>
</div></div>

<div class="m-sect"><div class="m-sect-hdr">Sub-scores</div><div class="m-sect-body">
  <table class="m-tbl"><tbody>
    <tr><td class="mono" style="width:120px">Economic</td><td>{_haz_bar((comp.get('economic') or 0)/100)}</td></tr>
    <tr><td class="mono">Political</td><td>{_haz_bar((comp.get('political') or 0)/100)}</td></tr>
    <tr><td class="mono">NLP sentiment</td><td>{_haz_bar((comp.get('nlp') or 0)/100)}</td></tr>
    <tr><td class="mono">Governance</td><td>{_haz_bar((comp.get('governance') or 0)/100)}</td></tr>
  </tbody></table>
</div></div>

<div class="m-sect"><div class="m-sect-hdr">12-Month Crisis Hazards
  <span style="font-weight:normal;text-transform:none">&nbsp;calibration: {cal}</span></div>
  <div class="m-sect-body">
  <div class="two-col">
    <div style="text-align:center;padding:6px">{radar}
      <div style="font-size:10px;color:#666">probability radar (0â€“100%)</div></div>
    <div style="padding:6px"><table class="m-tbl"><tbody>{haz_rows}</tbody></table></div>
  </div>
  <p style="font-size:10px;color:#888;margin-top:6px">Experimental (heuristic-served) â€” see
  <a href="/model/leaderboard">/model/leaderboard</a> &amp; BENCHMARK_vh_wsm_0.1.md.</p>
  </div></div>

<div class="m-sect"><div class="m-sect-hdr">Nearest Historical Analogues</div>
  <div class="m-sect-body"><table class="m-tbl">
  <thead><tr><th>#</th><th>Country</th><th>As of</th><th>Similarity</th><th>Outcome 12m</th></tr></thead>
  <tbody>{an_rows}</tbody></table>
  <p style="font-size:10px;color:#888;margin-top:6px">Cosine similarity over state embeddings;
  future dates &amp; recent same-country states are excluded.</p></div></div>

<div class="m-sect"><div class="m-sect-hdr">Spillover Pressure</div>
  <div class="m-sect-body">{sp_rows}
  <p style="font-size:10px;color:#888;margin-top:4px"><a href="/world">See full contagion map &#x25B8;</a></p>
  </div></div>

<div class="m-sect"><div class="m-sect-hdr">Model Provenance</div><div class="m-sect-body">
  <div class="d-row"><span class="d-label">model</span><span class="d-val mono">{meta.get('model_version')}</span></div>
  <div class="d-row"><span class="d-label">features</span><span class="d-val mono">{meta.get('feature_version')}</span></div>
  <div class="d-row"><span class="d-label">embedding</span><span class="d-val mono">{meta.get('embedding_version')}</span></div>
  <div class="d-row"><span class="d-label">base score</span><span class="d-val mono">{meta.get('base_score_version')}</span></div>
</div></div>

</div>
<div class="winfooter"><span>VH-WSM v0.1 &#183; experimental modelling layer</span>
  <a href="/dashboard/{code}">Base detail &#x25B8;</a></div>
{_tabbar([("Browse","/"),("Dashboard","/dashboard"),("World","/world"),("Country",""),("API","/api"),("",""),("Exit","/")], active="Country")}
</div></div></body></html>"""


@router.get("/worldstate/{country_code}", response_class=HTMLResponse, include_in_schema=False)
async def worldstate_page(country_code: str, db: Session = Depends(get_db)) -> HTMLResponse:
    from core.worldstate import service as wsm_service
    code = country_code.upper()
    st = wsm_service.build_state(db, code)
    if st is None:
        return HTMLResponse(
            _head("World-State â€” n/a") +
            f'<body><div class="desktop"><div class="window">'
            f'{_titlebar("VisibleHand World-State", "/dashboard")}'
            f'<div style="padding:20px">No world-state data for {code}. '
            f'Run <code>python scripts/materialize_worldstate.py --date today --all</code>.'
            f'</div></div></div></body></html>',
            status_code=404,
        )
    return HTMLResponse(_build_worldstate(code, st))


# â”€â”€ World overview: state-space map + clusters + contagion network â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_CLUSTER_PALETTE = ["#3a5a8c", "#8c5a3a", "#4f7c5d", "#8c3a6a", "#7c6a3a", "#5a5a8c",
                    "#6a8c3a", "#8c3a3a"]


def _svg_scatter(points: list[dict], w: int = 660, h: int = 460) -> str:
    """PCA state-space scatter. points: [{code,x,y,score}]."""
    if not points:
        return '<div style="padding:20px;color:#666">No embeddings yet.</div>'
    xs = [p["x"] for p in points]; ys = [p["y"] for p in points]
    minx, maxx = min(xs), max(xs); miny, maxy = min(ys), max(ys)
    pad = 46
    X = lambda v: pad + (w - 2 * pad) * ((v - minx) / (maxx - minx) if maxx > minx else 0.5)
    Y = lambda v: (h - pad) - (h - 2 * pad) * ((v - miny) / (maxy - miny) if maxy > miny else 0.5)
    grid = (f'<rect x="{pad}" y="{pad}" width="{w-2*pad}" height="{h-2*pad}" '
            f'fill="#fcfcfa" stroke="#ddd"/>')
    dots = ""
    for p in points:
        x, y = X(p["x"]), Y(p["y"]); col = _risk_color(p["score"])
        r = 4 + (p["score"] or 0) / 100 * 4.5
        dots += (f'<a href="/worldstate/{p["code"]}">'
                 f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{col}" '
                 f'stroke="#111" stroke-width="0.6" opacity="0.85"><title>{p["code"]} '
                 f'{p["score"]:.0f}</title></circle>'
                 f'<text x="{x:.1f}" y="{y-r-1:.1f}" font-size="7.5" text-anchor="middle" '
                 f'font-family="monospace" fill="#222">{p["code"]}</text></a>')
    lbl = (f'<text x="{w-pad}" y="{h-pad+16}" font-size="8.5" text-anchor="end" '
           f'fill="#888" font-family="monospace">PC1 &#8594;</text>'
           f'<text x="{pad}" y="{pad-8}" font-size="8.5" fill="#888" '
           f'font-family="monospace">&#8593; PC2</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%">{grid}{dots}{lbl}</svg>'


def _svg_network(nodes: list[dict], edges: list[tuple], size: int = 540) -> str:
    """Circular contagion network. nodes ordered; edges = [(a,b,weight)]."""
    import math
    if not nodes:
        return '<div style="padding:20px;color:#666">No data.</div>'
    cx = cy = size / 2; R = size / 2 - 34
    n = len(nodes); pos = {}
    for i, nd in enumerate(nodes):
        a = -math.pi / 2 + 2 * math.pi * i / n
        pos[nd["code"]] = (cx + math.cos(a) * R, cy + math.sin(a) * R)
    el = ""
    for a_, b_, wgt in edges:
        if a_ in pos and b_ in pos:
            x1, y1 = pos[a_]; x2, y2 = pos[b_]
            el += (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                   f'stroke="#6a6a6a" stroke-width="{0.3+wgt*1.4:.2f}" '
                   f'opacity="{0.08+wgt*0.32:.2f}"/>')
    nd_el = ""
    for nd in nodes:
        x, y = pos[nd["code"]]
        nd_el += (f'<a href="/worldstate/{nd["code"]}">'
                  f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6.5" fill="{_risk_color(nd["score"])}" '
                  f'stroke="#111" stroke-width="0.6"><title>{nd["code"]} {nd["score"]:.0f}</title></circle>'
                  f'<text x="{x:.1f}" y="{y+2.4:.1f}" font-size="5.6" text-anchor="middle" '
                  f'font-family="monospace" fill="#fff">{nd["code"]}</text></a>')
    return (f'<svg viewBox="0 0 {size} {size}" width="100%" style="max-width:540px">'
            f'{el}{nd_el}</svg>')


def _risk_legend() -> str:
    labels = [("&lt;20", 0), ("20â€“39", 1), ("40â€“59", 2), ("60â€“74", 3), ("75+", 4)]
    items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:10px">'
        f'<span style="width:11px;height:11px;background:{_VIZ_PALETTE[i]};'
        f'border:1px solid #000;display:inline-block"></span>'
        f'<span style="font-size:10px">{lab}</span></span>' for lab, i in labels)
    return f'<div style="margin-top:6px">{items}</div>'


# ── Comparison + risk-modeling visualisations ───────────────────────────────

_SERIES_PALETTE = ["#a8322f", "#2f5f8c", "#5d7c4f", "#9a5a1f",
                   "#6a4a8c", "#1f7c7c", "#8c2f6a", "#444444"]
_SUB_DIMS = [("economic", "ECON"), ("political", "POL"),
             ("nlp_sentiment", "NLP"), ("governance", "GOV")]


def _svg_radar_multi(axes_labels: list[str], series: list[tuple], size: int = 340) -> str:
    """Overlaid spider chart. series = [(name, [frac0..1 per axis], color)]."""
    import math
    cx, cy, R = size / 2, size / 2, size * 0.32
    n = max(1, len(axes_labels))
    ang = lambda i: -math.pi / 2 + 2 * math.pi * i / n
    rings = ""
    for rr in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{cx+math.cos(ang(i))*R*rr:.1f},{cy+math.sin(ang(i))*R*rr:.1f}"
                       for i in range(n))
        rings += f'<polygon points="{pts}" fill="none" stroke="#d6d6d2" stroke-width="0.7"/>'
    axesel = labels = ""
    for i, lab in enumerate(axes_labels):
        a = ang(i)
        axesel += (f'<line x1="{cx}" y1="{cy}" x2="{cx+math.cos(a)*R:.1f}" '
                   f'y2="{cy+math.sin(a)*R:.1f}" stroke="#e2e2de" stroke-width="0.7"/>')
        lx, ly = cx + math.cos(a) * (R + 18), cy + math.sin(a) * (R + 18) + 3
        anchor = "middle"
        if math.cos(a) > 0.3: anchor = "start"
        elif math.cos(a) < -0.3: anchor = "end"
        labels += (f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="8.5" text-anchor="{anchor}" '
                   f'font-family="monospace" fill="#444">{lab}</text>')
    polys = ""
    for name, fracs, color in series:
        pts = " ".join(
            f"{cx+math.cos(ang(i))*R*max(0,min(1,fracs[i])):.1f},"
            f"{cy+math.sin(ang(i))*R*max(0,min(1,fracs[i])):.1f}" for i in range(n))
        polys += (f'<polygon points="{pts}" fill="{color}" fill-opacity="0.10" '
                  f'stroke="{color}" stroke-width="1.6"/>')
        for i in range(n):
            f = max(0, min(1, fracs[i]))
            polys += (f'<circle cx="{cx+math.cos(ang(i))*R*f:.1f}" '
                      f'cy="{cy+math.sin(ang(i))*R*f:.1f}" r="1.8" fill="{color}"/>')
    return (f'<svg viewBox="0 0 {size} {size}" width="100%" style="max-width:360px">'
            f'{rings}{axesel}{polys}{labels}</svg>')


def _svg_grouped_bars(countries: list[str], colors: list[str],
                      values: dict, w: int = 560, h: int = 300) -> str:
    """Grouped vertical bars: one group per sub-dimension, one bar per country."""
    pad_l, pad_b, pad_t, pad_r = 30, 26, 12, 8
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    ng = len(_SUB_DIMS)
    nc = max(1, len(countries))
    group_w = plot_w / ng
    bar_w = min(20.0, (group_w - 12) / nc)
    out = (f'<rect x="{pad_l}" y="{pad_t}" width="{plot_w}" height="{plot_h}" '
           f'fill="#fcfcfa" stroke="#ddd"/>')
    for gy in (0, 25, 50, 75, 100):
        yy = pad_t + plot_h - (gy / 100) * plot_h
        out += (f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{pad_l+plot_w}" y2="{yy:.1f}" '
                f'stroke="#eee" stroke-width="0.7"/>'
                f'<text x="{pad_l-4}" y="{yy+3:.1f}" font-size="7.5" text-anchor="end" '
                f'font-family="monospace" fill="#999">{gy}</text>')
    for gi, (dk, dl) in enumerate(_SUB_DIMS):
        gx0 = pad_l + gi * group_w
        out += (f'<text x="{gx0+group_w/2:.1f}" y="{pad_t+plot_h+15:.1f}" font-size="8.5" '
                f'text-anchor="middle" font-family="monospace" fill="#444">{dl}</text>')
        for ci, code in enumerate(countries):
            v = values.get(code, {}).get(dk)
            v = 0 if v is None else v
            bh = (max(0, min(100, v)) / 100) * plot_h
            bx = gx0 + (group_w - nc * bar_w) / 2 + ci * bar_w
            by = pad_t + plot_h - bh
            out += (f'<rect x="{bx:.1f}" y="{by:.1f}" width="{max(2,bar_w-2):.1f}" '
                    f'height="{bh:.1f}" fill="{colors[ci]}" stroke="#111" stroke-width="0.4">'
                    f'<title>{code} {dl}: {v:.0f}</title></rect>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%">{out}</svg>'


def _svg_quadrant(points: list[dict], w: int = 620, h: int = 540) -> str:
    """Economic (x) vs political (y) risk map. points=[{code,ex,py,score}]."""
    pad = 52
    X = lambda v: pad + (w - 2 * pad) * max(0, min(100, v)) / 100
    Y = lambda v: (h - pad) - (h - 2 * pad) * max(0, min(100, v)) / 100
    out = (f'<rect x="{pad}" y="{pad}" width="{w-2*pad}" height="{h-2*pad}" '
           f'fill="#fcfcfa" stroke="#ccc"/>')
    mx, my = X(50), Y(50)
    out += (f'<line x1="{mx:.1f}" y1="{pad}" x2="{mx:.1f}" y2="{h-pad}" '
            f'stroke="#bbb" stroke-dasharray="3 3"/>'
            f'<line x1="{pad}" y1="{my:.1f}" x2="{w-pad}" y2="{my:.1f}" '
            f'stroke="#bbb" stroke-dasharray="3 3"/>')
    for t, xx, yy in [("RESILIENT", X(25), Y(20)), ("MACRO-FRAGILE", X(75), Y(20)),
                      ("POLITICALLY FRAGILE", X(25), Y(80)), ("TWIN-RISK", X(75), Y(80))]:
        out += (f'<text x="{xx:.1f}" y="{yy:.1f}" font-size="9.5" text-anchor="middle" '
                f'font-family="monospace" fill="#c4c4be" font-weight="bold">{t}</text>')
    for t in (0, 25, 50, 75, 100):
        out += (f'<text x="{X(t):.1f}" y="{h-pad+15:.1f}" font-size="7.5" text-anchor="middle" '
                f'font-family="monospace" fill="#999">{t}</text>'
                f'<text x="{pad-8:.1f}" y="{Y(t)+3:.1f}" font-size="7.5" text-anchor="end" '
                f'font-family="monospace" fill="#999">{t}</text>')
    out += (f'<text x="{w/2:.1f}" y="{h-12:.1f}" font-size="9" text-anchor="middle" '
            f'font-family="monospace" fill="#555">ECONOMIC RISK &#8594;</text>'
            f'<text x="14" y="{h/2:.1f}" font-size="9" text-anchor="middle" '
            f'font-family="monospace" fill="#555" '
            f'transform="rotate(-90 14 {h/2:.1f})">POLITICAL RISK &#8594;</text>')
    dots = ""
    for p in sorted(points, key=lambda d: -(d["score"] or 0)):
        x, y = X(p["ex"]), Y(p["py"])
        r = 4 + (p["score"] or 0) / 100 * 6
        dots += (f'<a href="/worldstate/{p["code"]}">'
                 f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{_risk_color(p["score"])}" '
                 f'stroke="#111" stroke-width="0.6" opacity="0.85"><title>{p["code"]} '
                 f'comp {p["score"]:.0f} &#183; econ {p["ex"]:.0f} &#183; pol {p["py"]:.0f}</title></circle>'
                 f'<text x="{x:.1f}" y="{y-r-1.5:.1f}" font-size="7.5" text-anchor="middle" '
                 f'font-family="monospace" fill="#222">{p["code"]}</text></a>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%">{out}{dots}</svg>'


def _minibar(v, color="#111", width=46) -> str:
    if v is None:
        return '<span style="color:#999">&#8212;</span>'
    w = max(0, min(100, v))
    return (f'<span style="display:inline-flex;align-items:center;gap:5px">'
            f'<span style="width:{width}px;height:8px;border:1px solid #000;background:#fff;'
            f'position:relative;display:inline-block">'
            f'<span style="position:absolute;left:0;top:0;bottom:0;width:{w:.0f}%;'
            f'background:{color}"></span></span>'
            f'<span style="font-size:10px;width:22px;color:#555">{v:.0f}</span></span>')


def _heat_cell(v) -> str:
    if v is None:
        return '<td style="background:#eee;color:#999;text-align:center">&#8212;</td>'
    col = _risk_color(v)
    fg = "#fff" if v >= 60 else "#111"
    return (f'<td style="background:{col};color:{fg};text-align:center;'
            f'font-weight:bold">{v:.0f}</td>')


def _heatmap_table(rows: list) -> str:
    head = ('<tr><th>Country</th><th style="text-align:center">Comp</th>'
            '<th style="text-align:center">Econ</th><th style="text-align:center">Pol</th>'
            '<th style="text-align:center">NLP</th><th style="text-align:center">Gov</th></tr>')
    body = ""
    for r in rows:
        name = _COUNTRY_NAMES.get(r.country_code, r.country_code)
        body += (f'<tr><td style="background:#fff"><a href="/worldstate/{r.country_code}">'
                 f'<b>{r.country_code}</b> <span style="color:#777">{name}</span></a></td>'
                 + _heat_cell(r.composite) + _heat_cell(r.economic) + _heat_cell(r.political)
                 + _heat_cell(r.nlp_sentiment) + _heat_cell(r.governance) + '</tr>')
    return f'<table class="heat">{head}{body}</table>'


_COMPARE_PRESETS = [
    ("BRICS", "BR,RU,IN,CN,ZA"),
    ("Latin America", "BR,AR,MX,CO,PE"),
    ("Advanced", "US,DE,GB,FR,JP"),
    ("Frontier", "NG,PK,EG,GH,LK"),
]


def _build_compare(selected: list, latest: list) -> str:
    codes = [r.country_code for r in selected]
    colors = [_SERIES_PALETTE[i % len(_SERIES_PALETTE)] for i in range(len(selected))]
    values = {r.country_code: {dk: getattr(r, dk) for dk, _ in _SUB_DIMS} for r in selected}

    series = [(r.country_code,
               [((getattr(r, dk) or 0) / 100.0) for dk, _ in _SUB_DIMS],
               colors[i]) for i, r in enumerate(selected)]
    radar = _svg_radar_multi(["ECON", "POL", "NLP", "GOV"], series)
    bars = _svg_grouped_bars(codes, colors, values)

    clegend = "".join(
        f'<span class="cl"><span class="csw" style="background:{colors[i]}"></span>'
        f'{r.country_code} <span style="color:#777">'
        f'{_COUNTRY_NAMES.get(r.country_code, r.country_code)}</span></span>'
        for i, r in enumerate(selected))

    presets = "".join(
        f'<a class="preset" href="/compare?countries={q}">{name}</a>'
        for name, q in _COMPARE_PRESETS)

    comps = sorted([r.composite for r in selected])
    spread = (comps[-1] - comps[0]) if comps else 0

    trows = ""
    for r in sorted(selected, key=lambda x: -x.composite):
        lvl = _risk_label(r.composite)
        trows += (f'<tr><td><b>{r.country_code}</b> <span style="color:#777">'
                  f'{_COUNTRY_NAMES.get(r.country_code, r.country_code)}</span></td>'
                  f'<td><b style="color:{_risk_color(r.composite)}">{r.composite:.1f}</b> '
                  f'<span style="font-size:9px;color:#777">{lvl}</span></td>'
                  f'<td>{_minibar(r.economic, _SERIES_PALETTE[0])}</td>'
                  f'<td>{_minibar(r.political, _SERIES_PALETTE[1])}</td>'
                  f'<td>{_minibar(r.nlp_sentiment, _SERIES_PALETTE[2])}</td>'
                  f'<td>{_minibar(r.governance, _SERIES_PALETTE[3])}</td>'
                  f'<td>{int((r.confidence or 0)*100)}%</td></tr>')

    return _head("VisibleHand — Compare") + f"""
<body>
{_menubar(["File","Edit","View"])}
<div class="desktop">
<div class="window">
{_titlebar("VisibleHand — Country Comparison", "/")}
<div class="statbar">
  <span><span class="ldot"></span>{len(selected)} countries &#183; composite spread {spread:.1f} pts</span>
  <span style="color:#555">sub-scores 0–100</span>
</div>
<div class="vsub" style="padding:8px 12px 0">
  <b>Compare:</b>&nbsp; {presets}
  <span style="color:#999">&#183; or call <code>/compare?countries=US,BR,AR</code></span>
</div>
<div class="clegend" style="padding:0 12px">{clegend}</div>
<div class="vrow">
  <div class="vcard">
    <div class="vh2">Sub-score profile (radar)</div>
    <div class="vsub">Each axis is a sub-scorer; further out = higher risk. Overlaid per country.</div>
    {radar}
  </div>
  <div class="vcard">
    <div class="vh2">Sub-score comparison (grouped)</div>
    <div class="vsub">Side-by-side magnitude on each component.</div>
    {bars}
  </div>
</div>
<div class="vcard" style="border-right:none">
  <div class="vh2">Ranked detail</div>
  <table class="ctbl">
    <thead><tr><th>Country</th><th>Composite</th><th>Economic</th><th>Political</th>
      <th>NLP</th><th>Governance</th><th>Conf.</th></tr></thead>
    <tbody>{trows}</tbody>
  </table>
</div>
{_tabbar([("Browse","/"),("Dashboard","/dashboard"),("Compare",""),("Map","/map"),("Studio","/studio"),("Validation","/validation"),("API","/api"),("",""),("Exit","/")], active="Compare")}
</div></div></body></html>"""


def _build_map(latest: list) -> str:
    points = [{"code": r.country_code, "ex": (r.economic or 0),
               "py": (r.political or 0), "score": r.composite} for r in latest]
    quad = _svg_quadrant(points)
    heat = _heatmap_table(sorted(latest, key=lambda r: -r.composite))
    n = len(latest)
    avg = sum(r.composite for r in latest) / n if n else 0

    return _head("VisibleHand — Risk Map") + f"""
<body>
{_menubar(["File","Edit","View"])}
<div class="desktop">
<div class="window">
{_titlebar("VisibleHand — Risk Map & Model", "/")}
<div class="statbar">
  <span><span class="ldot"></span>{n} countries &#183; mean composite {avg:.1f}</span>
  <span style="color:#555">economic &#215; political risk plane</span>
</div>
{_risk_legend()}
<div class="vrow">
  <div class="vcard" style="flex:1.3">
    <div class="vh2">Risk plane — economic &#215; political</div>
    <div class="vsub">Bubble size = composite. Quadrants split at the mid-line: <b>twin-risk</b>
      (top-right) carries both macro and political stress; <b>resilient</b> (bottom-left) carries
      neither. Click a bubble for the full country model.</div>
    {quad}
  </div>
  <div class="vcard">
    <div class="vh2">Sub-score heatmap</div>
    <div class="vsub">Every country &#215; every sub-scorer. Darker = higher risk.</div>
    {heat}
  </div>
</div>
{_tabbar([("Browse","/"),("Dashboard","/dashboard"),("Compare","/compare"),("Map",""),("Studio","/studio"),("Validation","/validation"),("API","/api"),("",""),("Exit","/")], active="Map")}
</div></div></body></html>"""


# ── Studio: interactive data analysis & manipulation (vanilla JS, no libs) ───

_STUDIO_CSS = """
.studio-ctrls{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;
  padding:10px 12px;background:#e7e4d6;border-bottom:2px solid #000}
.sgrp{display:flex;flex-direction:column;gap:3px}
.sgrp .gl{font:bold 9px Geneva,Verdana,sans-serif;letter-spacing:.06em;
  text-transform:uppercase;color:#444}
.wgt{display:flex;align-items:center;gap:6px}
.wgt input[type=range]{-webkit-appearance:none;appearance:none;width:108px;height:6px;
  background:#bdb89f;border:1px solid #000;outline:none}
.wgt input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
  width:11px;height:16px;background:#1f5f3a;border:1px solid #000;cursor:ew-resize}
.wgt input[type=range]::-moz-range-thumb{width:11px;height:16px;background:#1f5f3a;
  border:1px solid #000;cursor:ew-resize}
.wgt .wv{font:bold 11px "Cascadia Mono",Consolas,monospace;min-width:34px;text-align:right}
.studio-sel,.studio-in{font:11px Geneva,Verdana,sans-serif;border:1px solid #000;
  background:#fff;padding:2px 4px}
.studio-in{width:120px}
.sbtn{font:bold 10px Geneva,Verdana,sans-serif;background:#dcd8c8;border:1px solid #000;
  box-shadow:1px 1px 0 #000;padding:3px 9px;cursor:pointer}
.sbtn:active{box-shadow:0 0 0 #000;transform:translate(1px,1px)}
.sbtn.go{background:#1f5f3a;color:#fff}
.stbl{width:100%;border-collapse:collapse;font:11px Geneva,Verdana,sans-serif}
.stbl th{background:#cfcab6;border:1px solid #000;padding:3px 6px;text-align:right;
  cursor:pointer;white-space:nowrap;position:sticky;top:0}
.stbl th.l,.stbl td.l{text-align:left}
.stbl th.on::after{content:" \\25BE";font-size:8px}
.stbl th.on.asc::after{content:" \\25B4"}
.stbl td{border:1px solid #cabfa0;padding:2px 6px;text-align:right}
.stbl tr:nth-child(even) td{background:#f4f1e6}
.stbl .dn{color:#1f5f3a}.stbl .up{color:#a8322f}
.scwrap{position:relative}
#scTip{position:absolute;display:none;background:#000;color:#fff;font:10px monospace;
  padding:2px 5px;pointer-events:none;white-space:nowrap;z-index:5}
.toast{position:fixed;left:50%;bottom:38px;transform:translateX(-50%);background:#1f5f3a;
  color:#fff;font:bold 11px Geneva,sans-serif;padding:7px 16px;border:2px solid #000;
  box-shadow:2px 2px 0 #000;opacity:0;transition:opacity .2s;z-index:99}
.toast.show{opacity:1}
.tbl-scroll{max-height:300px;overflow:auto;border:1px solid #000}
.urlbox{font:10px "Cascadia Mono",Consolas,monospace;background:#f4f1e6;border:1px solid #999;
  padding:4px 6px;margin-top:6px;word-break:break-all;color:#333}
.srcrow{display:flex;flex-wrap:wrap;gap:18px;padding:8px 12px;background:#efece0;
  border-bottom:1px solid #000;align-items:flex-start}
.srcgrp{display:flex;flex-direction:column;gap:3px}
.srctog{font:11px Geneva,Verdana,sans-serif;cursor:pointer;user-select:none}
.srctog.off{opacity:.4;text-decoration:line-through}
.srcchips{display:flex;flex-wrap:wrap;gap:3px;max-width:230px}
.srcchip{font:9px Geneva,Verdana,sans-serif;background:#fff;border:1px solid #b6b094;
  padding:1px 5px;color:#555}
.corr-c{font:9px Geneva,Verdana,sans-serif}
.note-i{font:10px Geneva,Verdana,sans-serif;color:#666;padding:0 12px 8px}
.lab-hd{font:bold 12px Geneva,Verdana,sans-serif;background:#1f5f3a;color:#fff;
  padding:6px 12px;border-top:2px solid #000;border-bottom:1px solid #000;
  letter-spacing:.04em;text-transform:uppercase}
.shockrow{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;padding:9px 12px;
  background:#eef0e6;border-bottom:1px solid #000}
.shk .wv{color:#1f5f3a}
.bandshift{font:10px "Cascadia Mono",Consolas,monospace}
.focus-sel{font:11px Geneva,Verdana,sans-serif;border:1px solid #000;background:#fff;padding:2px 4px}
.solve{font:11px Geneva,Verdana,sans-serif;line-height:1.7;background:#f4f1e6;
  border:1px solid #cabfa0;padding:8px 10px;margin-top:6px}
.solve b{font-family:"Cascadia Mono",Consolas,monospace}
"""

_STUDIO_AXES = [("comp", "Composite (re-blended)"), ("c", "Composite (published)"),
                ("e", "Economic"), ("p", "Political"), ("n", "NLP"),
                ("g", "Governance"), ("conf", "Confidence")]


# Which real data sources feed each sub-scorer (for the source-selection panel).
# Toggling a family includes/excludes it from the live re-blend; the chips show
# provenance at the source level (finer per-source recompute is the /studio live
# endpoint path, B-tier).
_STUDIO_SOURCES = [
    ("e", "Economic", ["World Bank WDI", "IMF WEO", "BIS", "ILO", "IMF FSI", "FRED"]),
    ("p", "Political", ["ACLED", "GDELT", "REIGN"]),
    ("n", "NLP", ["Central-bank comms"]),
    ("g", "Governance", ["WGI", "V-Dem", "WJP", "TI CPI", "Freedom House"]),
]


def _build_studio(latest: list) -> str:
    data = [{
        "code": r.country_code,
        "name": _COUNTRY_NAMES.get(r.country_code, r.country_code),
        "c": round(r.composite, 1) if r.composite is not None else None,
        "e": round(r.economic, 1) if r.economic is not None else None,
        "p": round(r.political, 1) if r.political is not None else None,
        "n": round(r.nlp_sentiment, 1) if r.nlp_sentiment is not None else None,
        "g": round(r.governance, 1) if r.governance is not None else None,
        "conf": round((r.confidence or 0), 3),
        "cl": round(r.ci_low, 1) if getattr(r, "ci_low", None) is not None else None,
        "ch": round(r.ci_high, 1) if getattr(r, "ci_high", None) is not None else None,
    } for r in latest]
    data_json = json.dumps(data)

    src_html = ""
    for key, label, srcs in _STUDIO_SOURCES:
        chips = "".join(f'<span class="srcchip">{s}</span>' for s in srcs)
        src_html += (
            f'<div class="srcgrp"><label class="srctog">'
            f'<input type="checkbox" class="srcck" data-fam="{key}" checked> '
            f'<b>{label}</b></label><div class="srcchips">{chips}</div></div>'
        )

    focus_opts = "".join(
        f'<option value="{d["code"]}">{d["code"]} — {d["name"]}</option>' for d in data)

    opts = "".join(f'<option value="{k}">{lbl}</option>' for k, lbl in _STUDIO_AXES)
    xopts = opts.replace('value="e"', 'value="e" selected')
    yopts = opts.replace('value="p"', 'value="p" selected')

    head = _head("VisibleHand — Studio")
    shell = f"""<body>
{_menubar(["File","Edit","View","Data"])}
<div class="desktop">
<div class="window">
{_titlebar("VisibleHand — Data Studio", "/")}
<div class="statbar">
  <span><span class="ldot"></span>{len(data)} countries &#183; drag weights to re-blend the composite live</span>
  <span style="color:#555">linear re-blend of published sub-scores</span>
</div>
<div class="studio-ctrls">
  <div class="sgrp"><span class="gl">Economic <span id="we_v" class="wv">45</span></span>
    <span class="wgt"><input type="range" id="we" min="0" max="100" value="45"></span></div>
  <div class="sgrp"><span class="gl">Political <span id="wp_v" class="wv">25</span></span>
    <span class="wgt"><input type="range" id="wp" min="0" max="100" value="25"></span></div>
  <div class="sgrp"><span class="gl">NLP <span id="wn_v" class="wv">20</span></span>
    <span class="wgt"><input type="range" id="wn" min="0" max="100" value="20"></span></div>
  <div class="sgrp"><span class="gl">Governance <span id="wg_v" class="wv">10</span></span>
    <span class="wgt"><input type="range" id="wg" min="0" max="100" value="10"></span></div>
  <div class="sgrp"><span class="gl">Preset</span>
    <span style="display:flex;gap:4px">
      <button class="sbtn" data-preset="45,25,20,10">Default</button>
      <button class="sbtn" data-preset="25,25,25,25">Equal</button>
      <button class="sbtn" data-preset="70,10,10,10">Macro</button>
      <button class="sbtn" data-preset="10,55,15,20">Political</button>
    </span></div>
  <div class="sgrp"><span class="gl">X axis</span>
    <select class="studio-sel" id="xax">{xopts}</select></div>
  <div class="sgrp"><span class="gl">Y axis</span>
    <select class="studio-sel" id="yax">{yopts}</select></div>
  <div class="sgrp"><span class="gl">Filter</span>
    <input class="studio-in" id="flt" placeholder="code or name"></div>
  <div class="sgrp"><span class="gl">Band</span>
    <select class="studio-sel" id="bnd">
      <option value="">All</option><option value="0">Low &lt;20</option>
      <option value="1">Watch 20–40</option><option value="2">Elevated 40–60</option>
      <option value="3">High 60–75</option><option value="4">Severe 75+</option></select></div>
  <div class="sgrp"><span class="gl">Export</span>
    <span style="display:flex;gap:4px">
      <button class="sbtn go" id="csv">CSV</button>
      <button class="sbtn" id="jsonx">JSON</button>
      <button class="sbtn" id="pyx">Python</button>
      <button class="sbtn" id="apiurl">API weights</button></span></div>
</div>
<div class="srcrow">
  <div class="sgrp" style="margin-right:6px"><span class="gl">Data sources</span>
    <span style="font:10px Geneva,sans-serif;color:#555">toggle a family in/out of the blend</span></div>
  {src_html}
</div>
<div class="vrow">
  <div class="vcard" style="flex:1.25">
    <div class="vh2">Scatter — <span id="xlbl">Economic</span> &#215; <span id="ylbl">Political</span></div>
    <div class="vsub">Bubble size &amp; colour = re-blended composite. Move the weight sliders and
      watch every country re-rank. Hover a point for the country.</div>
    <div class="scwrap"><div id="scatter"></div><div id="scTip"></div></div>
  </div>
  <div class="vcard">
    <div class="vh2">Distribution — re-blended composite</div>
    <div class="vsub">10 bins, 0–100. Updates live with the weights.</div>
    <div id="hist"></div>
    <div class="urlbox" id="urlout">/risk/&lt;code&gt;?economic_weight=0.45&amp;political_weight=0.25&amp;nlp_weight=0.20&amp;governance_weight=0.10</div>
  </div>
</div>
<div class="vrow">
  <div class="vcard">
    <div class="vh2">Correlation matrix</div>
    <div class="vsub">Pearson r across sub-scores &amp; confidence over the live cross-section.
      Red = positive, blue = negative.</div>
    <div id="corr"></div>
  </div>
  <div class="vcard" style="flex:1.25">
    <div class="vh2">Scatter fit &amp; movers</div>
    <div class="vsub">OLS fit on the scatter axes, plus the biggest re-blend movers vs the
      published composite.</div>
    <div id="stats" class="corr-c"></div>
  </div>
</div>
<div class="vcard" style="border-right:none">
  <div class="vh2">Ranked table <span style="font-weight:normal;color:#888;font-size:10px">— click a header to sort, CI from Monte-Carlo</span></div>
  <div class="tbl-scroll"><table class="stbl" id="tbl">
    <thead><tr>
      <th class="l" data-k="code">Country</th>
      <th data-k="comp">Composite</th>
      <th data-k="ci">95% CI</th>
      <th data-k="delta">&#916; vs pub.</th>
      <th data-k="e">Econ</th><th data-k="p">Pol</th>
      <th data-k="n">NLP</th><th data-k="g">Gov</th>
      <th data-k="conf">Conf</th>
    </tr></thead><tbody id="tbody"></tbody>
  </table></div>
</div>
<div class="lab-hd">Scenario Lab — stress-test the world</div>
<div class="shockrow">
  <div class="sgrp shk"><span class="gl">&#916; Economic <span id="se_v" class="wv">0</span></span>
    <span class="wgt"><input type="range" id="se" min="-30" max="30" value="0"></span></div>
  <div class="sgrp shk"><span class="gl">&#916; Political <span id="sp_v" class="wv">0</span></span>
    <span class="wgt"><input type="range" id="sp" min="-30" max="30" value="0"></span></div>
  <div class="sgrp shk"><span class="gl">&#916; NLP <span id="sn_v" class="wv">0</span></span>
    <span class="wgt"><input type="range" id="sn" min="-30" max="30" value="0"></span></div>
  <div class="sgrp shk"><span class="gl">&#916; Governance <span id="sg_v" class="wv">0</span></span>
    <span class="wgt"><input type="range" id="sg" min="-30" max="30" value="0"></span></div>
  <div class="sgrp"><span class="gl">Stress preset</span>
    <span style="display:flex;gap:4px;flex-wrap:wrap">
      <button class="sbtn" data-shock="18,8,6,0">2008 GFC</button>
      <button class="sbtn" data-shock="15,5,0,2">Commodity crash</button>
      <button class="sbtn" data-shock="3,22,6,9">Political contagion</button>
      <button class="sbtn" data-shock="-12,-9,-5,-5">Broad recovery</button>
      <button class="sbtn go" data-shock="0,0,0,0">Reset</button>
    </span></div>
</div>
<div class="vrow">
  <div class="vcard" style="flex:1.2">
    <div class="vh2">Scenario impact — who moves, and across which band</div>
    <div class="vsub">Applies the shock to every country's sub-scores, re-blends, and ranks
      by absolute change. Arrow shows a risk-band crossing.</div>
    <div class="tbl-scroll" style="max-height:260px"><table class="stbl" id="scntbl">
      <thead><tr><th class="l">Country</th><th>Base</th><th>Scenario</th>
        <th>&#916;</th><th class="l">Band shift</th></tr></thead>
      <tbody id="scnbody"></tbody></table></div>
  </div>
  <div class="vcard">
    <div class="vh2">Driver sensitivity &amp; inverse solver</div>
    <div class="vsub">Pick a country: the tornado shows how a &#177;10-pt move in each driver
      shifts its composite; the solver finds the smallest single-driver change to
      leave its current band.</div>
    <div class="sgrp" style="margin:4px 0 8px"><span class="gl">Focus country</span>
      <select class="focus-sel" id="focus">{focus_opts}</select></div>
    <div id="tornado"></div>
    <div class="solve" id="solve"></div>
  </div>
</div>
<div class="lab-hd">Live backtest — validate against 2000–2023 crises</div>
<div class="shockrow">
  <div class="sgrp"><span class="gl">Score source</span>
    <select class="focus-sel" id="btsrc">
      <option value="heuristic">Heuristic bridge</option>
      <option value="live">Live point-in-time panel (C7)</option></select></div>
  <div class="sgrp"><span class="gl">Bootstrap</span>
    <select class="focus-sel" id="btboot">
      <option value="500">500</option><option value="1000" selected>1000</option>
      <option value="2000">2000</option></select></div>
  <div class="sgrp"><span class="gl">&nbsp;</span>
    <button class="sbtn go" id="runbt">Run backtest &#9654;</button></div>
  <div class="sgrp" style="flex:1;min-width:160px"><span class="gl">Status</span>
    <span id="btstatus" style="font:11px Geneva,sans-serif;color:#555">idle</span></div>
</div>
<div class="vcard" style="border-right:none"><div id="btresults">
  <div class="vsub">Runs the rigorous evaluation harness — bootstrap CIs, no-skill baselines,
    walk-forward calibration, Brier decomposition — against the crisis dataset.
    <b>Live</b> reconstructs point-in-time composites where the DB has coverage and reports
    that coverage honestly.</div>
</div></div>
{_tabbar([("Browse","/"),("Dashboard","/dashboard"),("Compare","/compare"),("Map","/map"),("Studio",""),("Validation","/validation"),("API","/api"),("",""),("Exit","/")], active="Studio")}
</div></div>
<div class="toast" id="toast"></div>
"""
    data_script = f'<script>window.VH_DATA={data_json};</script>'
    return head + "<style>" + _STUDIO_CSS + "</style>" + shell + data_script + _STUDIO_JS + "</body></html>"


_STUDIO_JS = r"""<script>(function(){
  var DATA = window.VH_DATA || [];
  var W = {e:45,p:25,n:20,g:10};
  var ACTIVE = {e:true,p:true,n:true,g:true};
  var PAL = ["#5d7c4f","#8f9a45","#cf9f24","#c2702a","#a8322f"];
  var AXL = {comp:"Composite",c:"Composite (pub)",e:"Economic",p:"Political",n:"NLP",g:"Governance",conf:"Confidence"};
  var sortKey="comp", sortAsc=false;
  var $ = function(id){return document.getElementById(id);};

  function band(v){ if(v==null)return 0; if(v<20)return 0; if(v<40)return 1; if(v<60)return 2; if(v<75)return 3; return 4; }
  function color(v){ return v==null?"#9a9a9a":PAL[band(v)]; }
  function fmt(v){ return (v==null)?"—":(+v).toFixed(1); }

  function reblend(d){
    var num=0, den=0, m={e:d.e,p:d.p,n:d.n,g:d.g};
    for(var k in m){ if(ACTIVE[k] && m[k]!=null){ num += W[k]*m[k]; den += W[k]; } }
    return den>0 ? num/den : null;
  }
  function axval(d,key){
    if(key==="comp") return d.comp;
    if(key==="conf") return d.conf==null?null:d.conf*100;
    return d[key];
  }
  function norm(){
    var t=0,o={e:0,p:0,n:0,g:0},k;
    for(k in o){ if(ACTIVE[k]) t+=W[k]; } t=t||1;
    for(k in o){ o[k]=ACTIVE[k]?W[k]/t:0; }
    return o;
  }

  function compute(){ return DATA.map(function(d){ var o={}; for(var k in d)o[k]=d[k]; o.comp=reblend(d); o.delta=(o.comp!=null&&d.c!=null)?(o.comp-d.c):null; return o; }); }

  // ---- Stats helpers ----
  function ols(pts){
    var n=pts.length; if(n<3) return null;
    var sx=0,sy=0,sxx=0,sxy=0;
    pts.forEach(function(p){ sx+=p[0]; sy+=p[1]; sxx+=p[0]*p[0]; sxy+=p[0]*p[1]; });
    var den=n*sxx-sx*sx; if(Math.abs(den)<1e-9) return null;
    var b=(n*sxy-sx*sy)/den, a=(sy-b*sx)/n;
    var my=sy/n, ssTot=0, ssRes=0;
    pts.forEach(function(p){ var yh=a+b*p[0]; ssRes+=(p[1]-yh)*(p[1]-yh); ssTot+=(p[1]-my)*(p[1]-my); });
    var r2=ssTot>0?1-ssRes/ssTot:0;
    return {a:a,b:b,r2:r2,n:n};
  }
  function pearson(xs,ys){
    var n=0,sx=0,sy=0,sxx=0,syy=0,sxy=0;
    for(var i=0;i<xs.length;i++){ if(xs[i]==null||ys[i]==null)continue;
      n++; sx+=xs[i]; sy+=ys[i]; sxx+=xs[i]*xs[i]; syy+=ys[i]*ys[i]; sxy+=xs[i]*ys[i]; }
    if(n<3) return null;
    var num=n*sxy-sx*sy, den=Math.sqrt((n*sxx-sx*sx)*(n*syy-sy*sy));
    return den>0?num/den:null;
  }
  function corrColor(r){
    if(r==null) return "#eee";
    var a=Math.abs(r);
    if(r>=0) return "rgba(168,50,47,"+(0.12+0.78*a).toFixed(2)+")";
    return "rgba(47,80,120,"+(0.12+0.78*a).toFixed(2)+")";
  }

  // ---- Correlation matrix ----
  function drawCorr(rows){
    var keys=[["comp","Comp"],["e","Econ"],["p","Pol"],["n","NLP"],["g","Gov"],["conf","Conf"]];
    var cols=keys.map(function(k){ return rows.map(function(d){ return axval(d,k[0]); }); });
    var w=300,h=300,pad=42,cell=(w-pad)/keys.length;
    var s='<svg viewBox="0 0 '+w+' '+h+'" width="100%" xmlns="http://www.w3.org/2000/svg" class="corr-c">';
    for(var i=0;i<keys.length;i++){
      for(var j=0;j<keys.length;j++){
        var r=(i===j)?1:pearson(cols[i],cols[j]);
        var x=pad+j*cell, y=pad+i*cell;
        s+='<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+cell.toFixed(1)+'" height="'+cell.toFixed(1)+'" fill="'+corrColor(r)+'" stroke="#fff"/>';
        s+='<text x="'+(x+cell/2).toFixed(1)+'" y="'+(y+cell/2+3).toFixed(1)+'" text-anchor="middle" fill="#222" font-size="9">'+(r==null?"—":r.toFixed(2))+'</text>';
      }
      s+='<text x="'+(pad-5)+'" y="'+(pad+i*cell+cell/2+3).toFixed(1)+'" text-anchor="end" fill="#444" font-size="9">'+keys[i][1]+'</text>';
      s+='<text x="'+(pad+i*cell+cell/2).toFixed(1)+'" y="'+(pad-6)+'" text-anchor="middle" fill="#444" font-size="9">'+keys[i][1]+'</text>';
    }
    s+='</svg>'; $("corr").innerHTML=s;
  }

  // ---- Stats / movers readout ----
  function drawStats(rows, fit){
    var xk=$("xax").value, yk=$("yax").value;
    var html='<div style="margin-bottom:8px"><b>OLS</b> '+AXL[yk]+' = ';
    if(fit){ html+='<span class="mono">'+fit.a.toFixed(1)+' + '+fit.b.toFixed(3)+'&#183;'+AXL[xk]
      +'</span> &#183; R&#178; <b>'+fit.r2.toFixed(3)+'</b> &#183; n='+fit.n; }
    else { html+='<span style="color:#999">insufficient points</span>'; }
    html+='</div>';
    var moved=rows.filter(function(d){return d.delta!=null;})
      .sort(function(a,b){return Math.abs(b.delta)-Math.abs(a.delta);}).slice(0,6);
    html+='<div><b>Biggest movers</b> vs published composite</div><div style="margin-top:4px">';
    moved.forEach(function(d){
      var up=d.delta>=0, col=up?"#a8322f":"#1f5f3a";
      html+='<div style="display:flex;gap:8px;align-items:center;margin:2px 0">'
        +'<span class="mono" style="width:30px"><b>'+d.code+'</b></span>'
        +'<span style="flex:1;height:9px;background:#fff;border:1px solid #000;position:relative">'
        +'<span style="position:absolute;'+(up?"left:50%":"right:50%")+';top:0;bottom:0;width:'
        +Math.min(50,Math.abs(d.delta)*2.2).toFixed(1)+'%;background:'+col+'"></span></span>'
        +'<span class="mono" style="width:46px;text-align:right;color:'+col+'">'+(up?"+":"")+d.delta.toFixed(1)+'</span></div>';
    });
    html+='</div>'; $("stats").innerHTML=html;
  }

  // ---- Scatter (inline SVG) ----
  function drawScatter(rows){
    var w=560,h=420,pad=44, xk=$("xax").value, yk=$("yax").value;
    $("xlbl").textContent=AXL[xk]; $("ylbl").textContent=AXL[yk];
    var X=function(v){return pad+(w-2*pad)*(v/100);};
    var Y=function(v){return (h-pad)-(h-2*pad)*(v/100);};
    var s='<svg viewBox="0 0 '+w+' '+h+'" width="100%" xmlns="http://www.w3.org/2000/svg" style="font:10px Geneva,sans-serif">';
    s+='<rect x="'+pad+'" y="'+pad+'" width="'+(w-2*pad)+'" height="'+(h-2*pad)+'" fill="#fbfaf4" stroke="#000"/>';
    for(var t=0;t<=100;t+=20){
      s+='<line x1="'+X(t)+'" y1="'+pad+'" x2="'+X(t)+'" y2="'+(h-pad)+'" stroke="#e3decd"/>';
      s+='<line x1="'+pad+'" y1="'+Y(t)+'" x2="'+(w-pad)+'" y2="'+Y(t)+'" stroke="#e3decd"/>';
      s+='<text x="'+X(t)+'" y="'+(h-pad+14)+'" text-anchor="middle" fill="#777">'+t+'</text>';
      s+='<text x="'+(pad-8)+'" y="'+(Y(t)+3)+'" text-anchor="end" fill="#777">'+t+'</text>';
    }
    s+='<text x="'+(w/2)+'" y="'+(h-8)+'" text-anchor="middle" fill="#333" font-weight="bold">'+AXL[xk]+'</text>';
    s+='<text x="14" y="'+(h/2)+'" text-anchor="middle" fill="#333" font-weight="bold" transform="rotate(-90 14 '+(h/2)+')">'+AXL[yk]+'</text>';
    var pts=[];
    rows.forEach(function(d){
      var xv=axval(d,xk), yv=axval(d,yk); if(xv==null||yv==null)return;
      pts.push([xv,yv]);
      var r=5+(d.comp||0)/100*7;
      s+='<circle cx="'+X(xv).toFixed(1)+'" cy="'+Y(yv).toFixed(1)+'" r="'+r.toFixed(1)+'" fill="'+color(d.comp)+'" fill-opacity="0.78" stroke="#000" stroke-width="0.6" data-c="'+d.code+'" data-x="'+xv.toFixed(1)+'" data-y="'+yv.toFixed(1)+'" data-comp="'+fmt(d.comp)+'"/>';
      s+='<text x="'+X(xv).toFixed(1)+'" y="'+(Y(yv)-r-2).toFixed(1)+'" text-anchor="middle" fill="#222" font-size="8">'+d.code+'</text>';
    });
    var fit=ols(pts);
    if(fit){
      // clip the regression segment to the [0,100] y-range, preserving slope
      var x1=0,x2=100,y1=fit.a+fit.b*x1,y2=fit.a+fit.b*x2;
      if(Math.abs(fit.b)>1e-9){
        if(y1<0){x1=(0-fit.a)/fit.b;y1=0;} if(y1>100){x1=(100-fit.a)/fit.b;y1=100;}
        if(y2<0){x2=(0-fit.a)/fit.b;y2=0;} if(y2>100){x2=(100-fit.a)/fit.b;y2=100;}
      }
      x1=Math.max(0,Math.min(100,x1)); x2=Math.max(0,Math.min(100,x2));
      s+='<line x1="'+X(x1).toFixed(1)+'" y1="'+Y(y1).toFixed(1)+'" x2="'+X(x2).toFixed(1)+'" y2="'+Y(y2).toFixed(1)+'" stroke="#1f5f3a" stroke-width="1.6" stroke-dasharray="5 3"/>';
    }
    s+='</svg>';
    $("scatter").innerHTML=s;
    var tip=$("scTip"), box=$("scatter");
    Array.prototype.forEach.call(box.querySelectorAll("circle"),function(c){
      c.addEventListener("mousemove",function(e){
        var rb=box.getBoundingClientRect();
        tip.style.display="block";
        tip.style.left=(e.clientX-rb.left+10)+"px"; tip.style.top=(e.clientY-rb.top+8)+"px";
        tip.textContent=c.getAttribute("data-c")+"  "+AXL[$("xax").value]+":"+c.getAttribute("data-x")+"  "+AXL[$("yax").value]+":"+c.getAttribute("data-y")+"  comp:"+c.getAttribute("data-comp");
      });
      c.addEventListener("mouseleave",function(){tip.style.display="none";});
    });
    return fit;
  }

  // ---- Histogram ----
  function drawHist(rows){
    var w=400,h=300,pad=34, bins=new Array(10).fill(0);
    rows.forEach(function(d){ if(d.comp!=null){ var b=Math.min(9,Math.floor(d.comp/10)); bins[b]++; } });
    var mx=Math.max.apply(null,bins)||1, bw=(w-2*pad)/10;
    var s='<svg viewBox="0 0 '+w+' '+h+'" width="100%" xmlns="http://www.w3.org/2000/svg" style="font:9px Geneva,sans-serif">';
    s+='<line x1="'+pad+'" y1="'+(h-pad)+'" x2="'+(w-pad)+'" y2="'+(h-pad)+'" stroke="#000"/>';
    bins.forEach(function(cnt,i){
      var bh=(h-2*pad)*(cnt/mx), x=pad+i*bw, y=(h-pad)-bh;
      s+='<rect x="'+(x+1).toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+(bw-2).toFixed(1)+'" height="'+bh.toFixed(1)+'" fill="'+PAL[Math.min(4,Math.floor(i/2))]+'" stroke="#000" stroke-width="0.5"/>';
      if(cnt)s+='<text x="'+(x+bw/2).toFixed(1)+'" y="'+(y-3).toFixed(1)+'" text-anchor="middle" fill="#333">'+cnt+'</text>';
      s+='<text x="'+(x+bw/2).toFixed(1)+'" y="'+(h-pad+12)+'" text-anchor="middle" fill="#888">'+(i*10)+'</text>';
    });
    s+='</svg>'; $("hist").innerHTML=s;
  }

  // ---- Table ----
  function passFilter(d){
    var q=$("flt").value.trim().toLowerCase();
    if(q && d.code.toLowerCase().indexOf(q)<0 && d.name.toLowerCase().indexOf(q)<0) return false;
    var bsel=$("bnd").value;
    if(bsel!=="" && String(band(d.comp))!==bsel) return false;
    return true;
  }
  function drawTable(rows){
    var view=rows.filter(passFilter);
    view.sort(function(a,b){
      var av=(sortKey==="code")?a.code:(a[sortKey]==null?-1:a[sortKey]);
      var bv=(sortKey==="code")?b.code:(b[sortKey]==null?-1:b[sortKey]);
      if(av<bv)return sortAsc?-1:1; if(av>bv)return sortAsc?1:-1; return 0;
    });
    var html="";
    view.forEach(function(d){
      var dc=d.delta==null?"":(d.delta>=0?"up":"dn");
      var ds=d.delta==null?"—":((d.delta>=0?"+":"")+d.delta.toFixed(1));
      var ci=(d.cl==null||d.ch==null)?"—":(d.cl.toFixed(0)+"–"+d.ch.toFixed(0));
      html+='<tr><td class="l"><b>'+d.code+'</b> <span style="color:#888">'+d.name+'</span></td>'
        +'<td style="color:'+color(d.comp)+';font-weight:bold">'+fmt(d.comp)+'</td>'
        +'<td class="mono" style="font-size:10px;color:#777">'+ci+'</td>'
        +'<td class="'+dc+'">'+ds+'</td>'
        +'<td>'+fmt(d.e)+'</td><td>'+fmt(d.p)+'</td><td>'+fmt(d.n)+'</td><td>'+fmt(d.g)+'</td>'
        +'<td>'+(d.conf==null?"—":(d.conf*100).toFixed(0)+"%")+'</td></tr>';
    });
    $("tbody").innerHTML=html;
    Array.prototype.forEach.call(document.querySelectorAll("#tbl th"),function(th){
      th.className=th.className.replace(/\s*on\s*/," ").replace(/\s*asc\s*/," ");
      if(th.getAttribute("data-k")===sortKey){ th.className+=" on"+(sortAsc?" asc":""); }
    });
  }

  function apiURL(){
    var n=norm();
    return "/risk/<code>?economic_weight="+n.e.toFixed(2)+"&political_weight="+n.p.toFixed(2)
      +"&nlp_weight="+n.n.toFixed(2)+"&governance_weight="+n.g.toFixed(2);
  }

  // ---- Scenario Lab ----
  var SHOCK={e:0,p:0,n:0,g:0};
  var BANDS=["Low","Watch","Elevated","High","Severe"];
  var BAND_LO=[0,20,40,60,75];
  function clamp01(v){ return Math.max(0,Math.min(100,v)); }
  function reblendShocked(d){
    var num=0,den=0,m={e:d.e,p:d.p,n:d.n,g:d.g},k;
    for(k in m){ if(ACTIVE[k]&&m[k]!=null){ num+=W[k]*clamp01(m[k]+SHOCK[k]); den+=W[k]; } }
    return den>0?num/den:null;
  }
  function reblendWith(d,key,val){
    var num=0,den=0,m={e:d.e,p:d.p,n:d.n,g:d.g},k;
    for(k in m){ if(ACTIVE[k]&&m[k]!=null){ var v=(k===key)?val:m[k]; num+=W[k]*clamp01(v); den+=W[k]; } }
    return den>0?num/den:null;
  }

  function drawScenario(){
    var rows=DATA.map(function(d){
      var base=reblend(d), scn=reblendShocked(d);
      return {code:d.code,name:d.name,base:base,scn:scn,
        delta:(base!=null&&scn!=null)?scn-base:null};
    }).filter(function(r){return r.delta!=null;});
    rows.sort(function(a,b){return Math.abs(b.delta)-Math.abs(a.delta);});
    var html="";
    rows.forEach(function(r){
      var b0=band(r.base), b1=band(r.scn);
      var shift=(b0===b1)?'<span style="color:#999">—</span>':
        '<span class="bandshift" style="color:'+(b1>b0?"#a8322f":"#1f5f3a")+'">'
        +BANDS[b0]+(b1>b0?" &#8593; ":" &#8595; ")+BANDS[b1]+'</span>';
      var dc=r.delta>=0?"up":"dn", ds=(r.delta>=0?"+":"")+r.delta.toFixed(1);
      html+='<tr><td class="l"><b>'+r.code+'</b> <span style="color:#888">'+r.name+'</span></td>'
        +'<td>'+r.base.toFixed(1)+'</td>'
        +'<td style="color:'+color(r.scn)+';font-weight:bold">'+r.scn.toFixed(1)+'</td>'
        +'<td class="'+dc+'">'+ds+'</td><td class="l">'+shift+'</td></tr>';
    });
    $("scnbody").innerHTML=html;
  }

  function drawTornado(code){
    var d=DATA.filter(function(x){return x.code===code;})[0];
    if(!d){ $("tornado").innerHTML=""; return; }
    var base=reblend(d); if(base==null){ $("tornado").innerHTML='<div class="vsub">No active drivers.</div>'; return; }
    var drv=[["e","Economic"],["p","Political"],["n","NLP"],["g","Governance"]];
    var bars=drv.map(function(dr){
      var k=dr[0];
      if(d[k]==null||!ACTIVE[k]) return {label:dr[1],up:0,dn:0,na:true};
      return {label:dr[1],up:reblendWith(d,k,d[k]+10)-base,dn:reblendWith(d,k,d[k]-10)-base,na:false};
    });
    var mAbs=1; bars.forEach(function(b){ mAbs=Math.max(mAbs,Math.abs(b.up),Math.abs(b.dn)); });
    var w=300,rowh=26,h=bars.length*rowh+22,midx=w/2,half=midx-80;
    var s='<svg viewBox="0 0 '+w+' '+h+'" width="100%" style="font:10px Geneva,sans-serif">';
    s+='<line x1="'+midx+'" y1="6" x2="'+midx+'" y2="'+(h-16)+'" stroke="#000"/>';
    bars.forEach(function(b,i){
      var y=10+i*rowh;
      if(!b.na){
        var wu=(b.up/mAbs)*half, wd=(b.dn/mAbs)*half;
        s+='<rect x="'+Math.min(midx,midx+wu).toFixed(1)+'" y="'+y+'" width="'+Math.abs(wu).toFixed(1)+'" height="9" fill="#a8322f" stroke="#000" stroke-width="0.5"><title>+10 &#8594; '+(b.up>=0?"+":"")+b.up.toFixed(1)+'</title></rect>';
        s+='<rect x="'+Math.min(midx,midx+wd).toFixed(1)+'" y="'+(y+10)+'" width="'+Math.abs(wd).toFixed(1)+'" height="9" fill="#1f5f3a" stroke="#000" stroke-width="0.5"><title>-10 &#8594; '+(b.dn>=0?"+":"")+b.dn.toFixed(1)+'</title></rect>';
      } else {
        s+='<text x="'+(midx+4)+'" y="'+(y+12)+'" fill="#aaa" font-size="9">inactive</text>';
      }
      s+='<text x="4" y="'+(y+13)+'" fill="#333">'+b.label+'</text>';
    });
    s+='<text x="'+(midx+3)+'" y="'+(h-4)+'" fill="#a8322f" font-size="8">+10 pt driver &#8594;</text>';
    s+='<text x="'+(midx-3)+'" y="'+(h-4)+'" text-anchor="end" fill="#1f5f3a" font-size="8">&#8592; -10 pt driver</text>';
    s+='</svg>'; $("tornado").innerHTML=s;
  }

  function inverseSolve(code){
    var d=DATA.filter(function(x){return x.code===code;})[0];
    var el=$("solve"); if(!d){ el.innerHTML=""; return; }
    var base=reblend(d); if(base==null){ el.innerHTML="No active drivers."; return; }
    var cb=band(base);
    if(cb===0){ el.innerHTML='<b>'+code+'</b> is already in the lowest band ('+BANDS[0]+', '+base.toFixed(1)+'). No reduction needed.'; return; }
    var thresh=BAND_LO[cb];
    var html='<b>'+code+'</b> sits at <b>'+base.toFixed(1)+'</b> ('+BANDS[cb]+'). Smallest single-driver cut to drop below '+thresh+' ('+BANDS[cb-1]+'):<br>';
    var drv=[["e","Economic"],["p","Political"],["n","NLP"],["g","Governance"]], any=false;
    drv.forEach(function(dr){
      var k=dr[0]; if(d[k]==null||!ACTIVE[k]) return;
      var found=null;
      for(var x=1;x<=60;x++){ var c=reblendWith(d,k,d[k]-x); if(c!=null&&c<thresh){ found=x; break; } }
      if(found!=null){ any=true; html+='&#8226; cut <b>'+dr[1]+'</b> by &#8805; <b>'+found+'</b> pts (&#8594; '+(d[k]-found).toFixed(0)+')<br>'; }
      else { html+='&#8226; '+dr[1]+' alone: <span style="color:#999">can’t reach the band</span><br>'; }
    });
    if(!any) html+='<span style="color:#999">No single driver suffices — needs a combined move.</span>';
    el.innerHTML=html;
  }

  function renderLab(){
    drawScenario();
    var f=$("focus")?$("focus").value:null;
    if(f){ drawTornado(f); inverseSolve(f); }
  }

  function render(){
    var rows=compute();
    var fit=drawScatter(rows); drawHist(rows); drawCorr(rows); drawTable(rows);
    drawStats(rows, fit); renderLab();
    $("urlout").textContent=apiURL();
  }

  function toast(msg){ var t=$("toast"); t.textContent=msg; t.className="toast show"; setTimeout(function(){t.className="toast";},1600); }

  function bindSlider(id,key){
    var el=$(id); el.addEventListener("input",function(){ W[key]=+el.value; $(id+"_v").textContent=el.value; render(); });
  }
  bindSlider("we","e"); bindSlider("wp","p"); bindSlider("wn","n"); bindSlider("wg","g");

  Array.prototype.forEach.call(document.querySelectorAll("[data-preset]"),function(b){
    b.addEventListener("click",function(){
      var p=b.getAttribute("data-preset").split(",").map(Number);
      W.e=p[0];W.p=p[1];W.n=p[2];W.g=p[3];
      $("we").value=p[0];$("wp").value=p[1];$("wn").value=p[2];$("wg").value=p[3];
      $("we_v").textContent=p[0];$("wp_v").textContent=p[1];$("wn_v").textContent=p[2];$("wg_v").textContent=p[3];
      render();
    });
  });
  $("xax").addEventListener("change",render);
  $("yax").addEventListener("change",render);
  $("flt").addEventListener("input",render);
  $("bnd").addEventListener("change",render);
  Array.prototype.forEach.call(document.querySelectorAll("#tbl th"),function(th){
    th.addEventListener("click",function(){
      var k=th.getAttribute("data-k");
      if(sortKey===k){ sortAsc=!sortAsc; } else { sortKey=k; sortAsc=(k==="code"); }
      drawTable(compute());
    });
  });
  $("csv").addEventListener("click",function(){
    var rows=compute().filter(passFilter);
    var lines=["code,name,composite_reblended,composite_published,delta,economic,political,nlp,governance,confidence"];
    rows.forEach(function(d){
      lines.push([d.code,'"'+d.name+'"',fmt(d.comp),fmt(d.c),(d.delta==null?"":d.delta.toFixed(1)),
        fmt(d.e),fmt(d.p),fmt(d.n),fmt(d.g),(d.conf==null?"":d.conf)].join(","));
    });
    var blob=new Blob([lines.join("\n")],{type:"text/csv"});
    var a=document.createElement("a"); a.href=URL.createObjectURL(blob);
    a.download="visiblehand_studio.csv"; document.body.appendChild(a); a.click(); a.remove();
    toast("Exported "+rows.length+" rows");
  });
  $("apiurl").addEventListener("click",function(){
    var url=apiURL();
    if(navigator.clipboard){ navigator.clipboard.writeText(url).then(function(){toast("API weights copied");},function(){toast(url);}); }
    else { toast(url); }
  });

  // scenario shock sliders
  function bindShock(id,key){
    var el=$(id); el.addEventListener("input",function(){ SHOCK[key]=+el.value; $(id+"_v").textContent=(el.value>0?"+":"")+el.value; drawScenario(); });
  }
  bindShock("se","e"); bindShock("sp","p"); bindShock("sn","n"); bindShock("sg","g");
  Array.prototype.forEach.call(document.querySelectorAll("[data-shock]"),function(b){
    b.addEventListener("click",function(){
      var p=b.getAttribute("data-shock").split(",").map(Number);
      SHOCK.e=p[0];SHOCK.p=p[1];SHOCK.n=p[2];SHOCK.g=p[3];
      $("se").value=p[0];$("sp").value=p[1];$("sn").value=p[2];$("sg").value=p[3];
      $("se_v").textContent=(p[0]>0?"+":"")+p[0];$("sp_v").textContent=(p[1]>0?"+":"")+p[1];
      $("sn_v").textContent=(p[2]>0?"+":"")+p[2];$("sg_v").textContent=(p[3]>0?"+":"")+p[3];
      drawScenario();
    });
  });
  if($("focus")) $("focus").addEventListener("change",function(){ var f=$("focus").value; drawTornado(f); inverseSolve(f); });

  // live backtest (calls the evaluation harness endpoint)
  function btKpi(label,val){
    return '<div style="flex:1;min-width:88px;border:1px solid #000;padding:6px 8px;background:#fff">'
      +'<div style="font-size:15px;font-weight:bold;font-family:monospace">'+val+'</div>'
      +'<div style="font-size:8px;letter-spacing:.05em;color:#666;text-transform:uppercase">'+label+'</div></div>';
  }
  function fmtCI(o){
    if(!o) return "—";
    return (o.ci_low!=null) ? o.point.toFixed(3)+' ['+o.ci_low.toFixed(3)+', '+o.ci_high.toFixed(3)+']'
                            : (o.point!=null?o.point.toFixed(3):"—");
  }
  function runBacktest(){
    var src=$("btsrc").value, nb=$("btboot").value;
    $("btstatus").textContent="running…"; $("runbt").disabled=true;
    fetch("/calibration/evaluation?source="+src+"&n_boot="+nb)
      .then(function(r){ return r.json(); })
      .then(function(j){
        $("runbt").disabled=false;
        if(j.status==="error"){ $("btstatus").textContent="error: "+j.message; return; }
        $("btstatus").textContent="done · "+(j.score_source||src);
        var bd=j.brier_decomposition||{}, h='';
        h+='<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">';
        h+=btKpi("AUC", fmtCI(j.auc));
        h+=btKpi("Avg precision", fmtCI(j.average_precision));
        h+=btKpi("Base rate", (j.base_rate!=null?j.base_rate.toFixed(3):"—"));
        h+=btKpi("Brier", (bd.brier!=null?bd.brier:"—"));
        h+=btKpi("Skill", (bd.skill_score!=null?bd.skill_score:"—"));
        h+='</div>';
        if(j.baselines){
          h+='<div class="corr-c"><b>vs no-skill:</b> random AUC '+j.baselines.random.point.toFixed(3)
            +' · crisis-type prior '+j.baselines.crisis_type_prior.point.toFixed(3)+'</div>';
        }
        var t=j.temporal_cv;
        if(t && t.available){
          h+='<div class="corr-c" style="margin-top:4px"><b>Walk-forward OOS:</b> n='+t.n_oos
            +' over '+t.n_folds+' folds · AUC '+fmtCI(t.oos_auc)+' · Brier '+t.oos_brier.brier+'</div>';
        }
        if(j.panel_coverage){
          var c=j.panel_coverage;
          h+='<div class="corr-c" style="margin-top:4px"><b>Panel coverage:</b> '+c.live+'/'+c.n_events
            +' events scored live ('+Math.round(c.coverage_rate*100)+'%), '+c.insufficient+' heuristic fallback</div>';
        }
        $("btresults").innerHTML=h;
      })
      .catch(function(e){ $("runbt").disabled=false; $("btstatus").textContent="fetch failed: "+e; });
  }
  if($("runbt")) $("runbt").addEventListener("click", runBacktest);

  // source-family toggles
  Array.prototype.forEach.call(document.querySelectorAll(".srcck"),function(ck){
    ck.addEventListener("change",function(){
      ACTIVE[ck.getAttribute("data-fam")]=ck.checked;
      var lab=ck.closest(".srctog"); if(lab){ lab.className="srctog"+(ck.checked?"":" off"); }
      render();
    });
  });

  function download(name,text,mime){
    var blob=new Blob([text],{type:mime||"text/plain"});
    var a=document.createElement("a"); a.href=URL.createObjectURL(blob);
    a.download=name; document.body.appendChild(a); a.click(); a.remove();
  }
  $("jsonx").addEventListener("click",function(){
    var rows=compute().filter(passFilter).map(function(d){
      return {code:d.code,name:d.name,composite_reblended:d.comp,composite_published:d.c,
        delta:d.delta,economic:d.e,political:d.p,nlp:d.n,governance:d.g,
        confidence:d.conf,ci_low:d.cl,ci_high:d.ch};
    });
    var payload={weights:norm(),active_sources:ACTIVE,generated:new Date().toISOString(),rows:rows};
    download("visiblehand_studio.json",JSON.stringify(payload,null,2),"application/json");
    toast("Exported "+rows.length+" rows (JSON)");
  });
  $("pyx").addEventListener("click",function(){
    var n=norm();
    var codes=compute().filter(passFilter).map(function(d){return d.code;});
    var py=[
      "import requests",
      "",
      "# Auto-generated by VisibleHand Data Studio",
      "BASE = \"https://api.visiblehand.xyz\"",
      "WEIGHTS = {",
      "    \"economic_weight\": "+n.e.toFixed(3)+",",
      "    \"political_weight\": "+n.p.toFixed(3)+",",
      "    \"nlp_weight\": "+n.n.toFixed(3)+",",
      "    \"governance_weight\": "+n.g.toFixed(3)+",",
      "}",
      "CODES = "+JSON.stringify(codes),
      "",
      "rows = []",
      "for code in CODES:",
      "    r = requests.get(f\"{BASE}/risk/{code}\", params=WEIGHTS, timeout=30)",
      "    r.raise_for_status()",
      "    rows.append(r.json())",
      "",
      "for row in sorted(rows, key=lambda x: -x[\"composite\"]):",
      "    print(f'{row[\"country_code\"]:<4} {row[\"composite\"]:6.1f}')"
    ].join("\n");
    download("visiblehand_query.py",py,"text/x-python");
    toast("Python snippet exported");
  });

  render();
})();</script>"""


# ── Calibration / validation visuals (inline SVG, no JS libs) ────────────────

def _svg_roc(roc_curve: list[dict], auc: float, w: int = 360, h: int = 360) -> str:
    pad = 42
    X = lambda v: pad + (w - 2 * pad) * v
    Y = lambda v: (h - pad) - (h - 2 * pad) * v
    out = (f'<rect x="{pad}" y="{pad}" width="{w-2*pad}" height="{h-2*pad}" '
           f'fill="#fcfcfa" stroke="#ddd"/>')
    out += (f'<line x1="{X(0):.1f}" y1="{Y(0):.1f}" x2="{X(1):.1f}" y2="{Y(1):.1f}" '
            f'stroke="#bbb" stroke-dasharray="3 3"/>')
    if roc_curve:
        pts = " ".join(f"{X(p['fpr']):.1f},{Y(p['tpr']):.1f}" for p in roc_curve)
        out += (f'<polyline points="{pts}" fill="none" stroke="#a8322f" stroke-width="1.8"/>')
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        out += (f'<text x="{X(t):.1f}" y="{h-pad+14:.1f}" font-size="7.5" text-anchor="middle" '
                f'font-family="monospace" fill="#999">{t:g}</text>'
                f'<text x="{pad-6:.1f}" y="{Y(t)+3:.1f}" font-size="7.5" text-anchor="end" '
                f'font-family="monospace" fill="#999">{t:g}</text>')
    out += (f'<text x="{w/2:.1f}" y="{h-8:.1f}" font-size="9" text-anchor="middle" '
            f'font-family="monospace" fill="#555">false positive rate &#8594;</text>'
            f'<text x="12" y="{h/2:.1f}" font-size="9" text-anchor="middle" '
            f'font-family="monospace" fill="#555" '
            f'transform="rotate(-90 12 {h/2:.1f})">true positive rate &#8594;</text>'
            f'<text x="{X(0.52):.1f}" y="{Y(0.22):.1f}" font-size="12" font-family="monospace" '
            f'fill="#a8322f" font-weight="bold">AUC {auc:.2f}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:380px">{out}</svg>'


def _svg_histogram(values: list[float], w: int = 560, h: int = 300, bins: int = 10) -> str:
    pad_l, pad_b, pad_t, pad_r = 30, 30, 16, 10
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, int(max(0, min(100, v)) / 100 * bins))
        counts[idx] += 1
    mx = max(counts) or 1
    out = (f'<rect x="{pad_l}" y="{pad_t}" width="{plot_w}" height="{plot_h}" '
           f'fill="#fcfcfa" stroke="#ddd"/>')
    bw = plot_w / bins
    for i, c in enumerate(counts):
        bh = (c / mx) * plot_h
        bx = pad_l + i * bw
        by = pad_t + plot_h - bh
        lo, hi = int(i * 100 / bins), int((i + 1) * 100 / bins)
        out += (f'<rect x="{bx+1:.1f}" y="{by:.1f}" width="{bw-2:.1f}" height="{bh:.1f}" '
                f'fill="{_risk_color((lo+hi)/2)}" stroke="#111" stroke-width="0.4">'
                f'<title>{lo}-{hi}: {c}</title></rect>')
        if c:
            out += (f'<text x="{bx+bw/2:.1f}" y="{by-3:.1f}" font-size="8" text-anchor="middle" '
                    f'font-family="monospace" fill="#444">{c}</text>')
    for t in (0, 25, 50, 75, 100):
        out += (f'<text x="{pad_l+(t/100)*plot_w:.1f}" y="{pad_t+plot_h+14:.1f}" font-size="7.5" '
                f'text-anchor="middle" font-family="monospace" fill="#999">{t}</text>')
    out += (f'<text x="{pad_l+plot_w/2:.1f}" y="{h-2:.1f}" font-size="8.5" text-anchor="middle" '
            f'font-family="monospace" fill="#666">composite risk score &#8594;</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%">{out}</svg>'


def _svg_reliability(curve: list[dict], w: int = 360, h: int = 360) -> str:
    """Reliability diagram: mean predicted (x) vs observed frequency (y), bubble = count."""
    pad = 42
    X = lambda v: pad + (w - 2 * pad) * v
    Y = lambda v: (h - pad) - (h - 2 * pad) * v
    out = (f'<rect x="{pad}" y="{pad}" width="{w-2*pad}" height="{h-2*pad}" '
           f'fill="#fcfcfa" stroke="#ddd"/>')
    # perfect-calibration diagonal
    out += (f'<line x1="{X(0):.1f}" y1="{Y(0):.1f}" x2="{X(1):.1f}" y2="{Y(1):.1f}" '
            f'stroke="#bbb" stroke-dasharray="3 3"/>')
    if curve:
        mx = max((p["count"] for p in curve), default=1) or 1
        pts = " ".join(f"{X(p['mean_predicted']):.1f},{Y(p['observed_frequency']):.1f}" for p in curve)
        out += f'<polyline points="{pts}" fill="none" stroke="#1f5f3a" stroke-width="1.6"/>'
        for p in curve:
            r = 2.5 + 5 * (p["count"] / mx) ** 0.5
            out += (f'<circle cx="{X(p["mean_predicted"]):.1f}" cy="{Y(p["observed_frequency"]):.1f}" '
                    f'r="{r:.1f}" fill="#1f5f3a" fill-opacity="0.7" stroke="#000" stroke-width="0.5">'
                    f'<title>pred {p["mean_predicted"]:.2f} / obs {p["observed_frequency"]:.2f} '
                    f'(n={p["count"]})</title></circle>')
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        out += (f'<text x="{X(t):.1f}" y="{h-pad+14:.1f}" font-size="7.5" text-anchor="middle" '
                f'font-family="monospace" fill="#999">{t:g}</text>'
                f'<text x="{pad-6:.1f}" y="{Y(t)+3:.1f}" font-size="7.5" text-anchor="end" '
                f'font-family="monospace" fill="#999">{t:g}</text>')
    out += (f'<text x="{w/2:.1f}" y="{h-8:.1f}" font-size="9" text-anchor="middle" '
            f'font-family="monospace" fill="#555">mean predicted probability &#8594;</text>'
            f'<text x="12" y="{h/2:.1f}" font-size="9" text-anchor="middle" '
            f'font-family="monospace" fill="#555" '
            f'transform="rotate(-90 12 {h/2:.1f})">observed frequency &#8594;</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:380px">{out}</svg>'


def _ci_bar(point: float, lo, hi, label: str, ref: float = 0.5) -> str:
    """Horizontal metric bar with a bootstrap CI whisker and a no-skill reference tick."""
    X = lambda v: max(0.0, min(1.0, v)) * 100
    whisker = ""
    if lo is not None and hi is not None:
        whisker = (f'<span style="position:absolute;left:{X(lo):.1f}%;width:{max(0.5,X(hi)-X(lo)):.1f}%;'
                   f'top:50%;height:0;border-top:2px solid #000;opacity:.55"></span>'
                   f'<span style="position:absolute;left:{X(lo):.1f}%;top:30%;height:40%;'
                   f'border-left:1px solid #000"></span>'
                   f'<span style="position:absolute;left:{X(hi):.1f}%;top:30%;height:40%;'
                   f'border-left:1px solid #000"></span>')
    return (f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0;font-size:11px">'
            f'<span style="width:150px" class="mono">{label}</span>'
            f'<span style="flex:1;height:14px;border:1px solid #000;background:#fff;position:relative">'
            f'<span style="position:absolute;left:0;top:0;bottom:0;width:{X(point):.1f}%;'
            f'background:{_risk_color(point*100)}"></span>'
            f'<span style="position:absolute;left:{X(ref):.1f}%;top:-2px;bottom:-2px;'
            f'border-left:1px dashed #777"></span>{whisker}</span>'
            f'<span class="mono" style="width:42px;text-align:right">{point:.3f}</span></div>')


def _build_validation(bt, scores: list, ev=None, hz=None) -> str:
    roc = _svg_roc(bt.roc_curve, bt.auc)
    dist = _svg_histogram([s.composite for s in scores])
    kpis = [("ROC-AUC", f"{bt.auc:.2f}"), ("Brier", f"{bt.brier_score:.3f}"),
            ("PR-AUC", f"{bt.pr_auc:.2f}"), ("Events", str(bt.n_events)),
            ("Crises", str(bt.n_crises))]
    kpi_html = "".join(
        f'<div style="flex:1;min-width:90px;border:1px solid #000;padding:8px 10px;background:#fff">'
        f'<div style="font-size:20px;font-weight:bold;font-family:monospace">{v}</div>'
        f'<div style="font-size:9px;letter-spacing:.08em;color:#666;text-transform:uppercase">{k}</div>'
        f'</div>' for k, v in kpis)

    bytype = ""
    for ctype, auc in sorted(bt.by_crisis_type.items(), key=lambda kv: -kv[1]):
        w = int(max(0, min(1, auc)) * 100)
        bytype += (f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0;font-size:11px">'
                   f'<span style="width:120px" class="mono">{ctype.replace("_"," ")}</span>'
                   f'<span style="flex:1;height:10px;border:1px solid #000;background:#fff;position:relative">'
                   f'<span style="position:absolute;left:0;top:0;bottom:0;width:{w}%;background:{_risk_color(auc*100)}"></span></span>'
                   f'<span class="mono" style="width:36px;text-align:right">{auc:.2f}</span></div>')

    eval_section = ""
    if ev is not None:
        auc, ap = ev.auc, ev.average_precision
        bd = ev.brier_decomposition
        bl = ev.baselines
        tcv = ev.temporal_cv
        bars = _ci_bar(auc["point"], auc.get("ci_low"), auc.get("ci_high"), "Model AUC")
        bars += _ci_bar(ap["point"], ap.get("ci_low"), ap.get("ci_high"),
                        f"Model AP (base {ev.base_rate:.2f})", ref=ev.base_rate)
        bars += _ci_bar(bl["crisis_type_prior"]["point"], bl["crisis_type_prior"].get("ci_low"),
                        bl["crisis_type_prior"].get("ci_high"), "Baseline: type prior")
        bars += _ci_bar(bl["random"]["point"], bl["random"].get("ci_low"),
                        bl["random"].get("ci_high"), "Baseline: random")

        rel_svg = ""
        oos_line = ""
        if tcv.get("available"):
            rel_svg = _svg_reliability(tcv.get("reliability_curve", []))
            oa = tcv["oos_auc"]
            oos_line = (f'Walk-forward out-of-sample (n={tcv["n_oos"]}, {tcv["n_folds"]} folds): '
                        f'AUC <b>{oa["point"]:.3f}</b> '
                        f'[{oa.get("ci_low")}, {oa.get("ci_high")}], '
                        f'Brier <b>{tcv["oos_brier"]["brier"]}</b>.')
        else:
            rel_svg = '<div class="vsub">Temporal CV unavailable for this dataset slice.</div>'

        decomp = (
            f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">' +
            "".join(
                f'<div style="flex:1;min-width:74px;border:1px solid #000;padding:6px 8px;background:#fff">'
                f'<div style="font-size:15px;font-weight:bold;font-family:monospace">{bd[k] if bd[k] is not None else "—"}</div>'
                f'<div style="font-size:8px;letter-spacing:.05em;color:#666;text-transform:uppercase">{lbl}</div></div>'
                for k, lbl in [("reliability", "reliability&#8595;"), ("resolution", "resolution&#8593;"),
                               ("uncertainty", "uncertainty"), ("skill_score", "skill&#8593;")]
            ) + '</div>')

        eval_section = f"""
<div class="vrow">
  <div class="vcard">
    <div class="vh2">Rigorous metrics — bootstrap CIs &amp; no-skill floors</div>
    <div class="vsub">Stratified 2000-replicate bootstrap. Dashed tick = no-skill
      reference. A model bar whose CI clears the baseline is real skill, not noise.</div>
    {bars}
    <div class="vh2" style="margin-top:12px">Brier decomposition (Murphy 1973)</div>
    <div class="vsub">BS = reliability &#8722; resolution + uncertainty. Lower reliability =
      better calibration; higher resolution = better discrimination.</div>
    {decomp}
  </div>
  <div class="vcard">
    <div class="vh2">Reliability diagram — walk-forward calibration</div>
    <div class="vsub">Logistic calibration fit on prior years only, evaluated on held-out
      years (no look-ahead). On the diagonal = well-calibrated.</div>
    {rel_svg}
    <div class="vsub" style="margin-top:8px">{oos_line}</div>
  </div>
</div>
<div class="note-i" style="padding:6px 12px 0"><b>Score source:</b> {ev.score_source}</div>"""

    hz_section = ""
    if hz is not None and hz.get("status") == "available":
        cov = hz.get("coverage", {})
        ranked = hz.get("feature_ranking", [])
        mx = max((abs(r["coef_std"]) for r in ranked), default=1) or 1
        bars = ""
        for r in ranked:
            w = int(max(0, min(1, abs(r["coef_std"]) / mx)) * 100)
            bars += (f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0;font-size:11px">'
                     f'<span style="width:96px" class="mono">{r["feature"]}</span>'
                     f'<span style="flex:1;height:11px;border:1px solid #000;background:#fff;position:relative">'
                     f'<span style="position:absolute;left:0;top:0;bottom:0;width:{w}%;background:{_risk_color(70)}"></span></span>'
                     f'<span class="mono" style="width:48px;text-align:right">{r["coef_std"]:.3f}</span></div>')
        auc = hz.get("in_sample_auc", {})
        hz_section = f"""
<div class="vrow">
  <div class="vcard">
    <div class="vh2">Discrete-time hazard model — trained early-warning probability</div>
    <div class="vsub">Monotone (coefficient &#8805; 0), L2-regularised logistic hazard on the C7
      point-in-time panel: P(crisis within 12 months) from the four sub-scores.
      Bars = standardised per-1-SD effect on the log-odds.</div>
    {bars}
    <div class="vsub" style="margin-top:8px">n_train <b>{hz.get('n_train')}</b> ·
      class balance <b>{hz.get('class_balance')}</b> · in-sample AUC
      <b>{auc.get('point')}</b> [{auc.get('ci_low')}, {auc.get('ci_high')}] ·
      panel coverage {cov.get('live')}/{cov.get('n_events')}.</div>
  </div>
  <div class="vcard">
    <div class="vh2">How to read it</div>
    <div class="vsub">Coefficients are constrained non-negative so a worse sub-score can never
      <i>lower</i> predicted crisis risk — a sign error that would wreck credibility. With a
      small panel, the in-sample AUC overstates real skill; the walk-forward CV above is the
      honest out-of-sample read. The default composite is unchanged — this is an opt-in
      probability served at <span class="mono">/calibration/hazard-model</span>.</div>
  </div>
</div>"""
    elif hz is not None:
        hz_section = (f'<div class="note-i" style="padding:8px 12px"><b>Hazard model:</b> '
                      f'{hz.get("note", "insufficient panel coverage to train yet.")}</div>')

    return _head("VisibleHand — Validation") + f"""
<body>
{_menubar(["File","Edit","View"])}
<div class="desktop">
<div class="window">
{_titlebar("VisibleHand — Calibration & Validation", "/")}
<div class="statbar">
  <span><span class="ldot"></span>{bt.n_events} labelled events &#183; {bt.n_crises} crises</span>
  <span style="color:#555">2000–2023 backtest</span>
</div>
<div style="display:flex;gap:8px;flex-wrap:wrap;padding:10px 12px;border-bottom:1px solid #000">{kpi_html}</div>
{eval_section}
{hz_section}
<div class="vrow">
  <div class="vcard">
    <div class="vh2">ROC curve — does an elevated score precede a crisis?</div>
    <div class="vsub">Threshold sweep over composite scores 12 months before each labelled
      stress event. The diagonal is chance; bowed toward the top-left is skill.</div>
    {roc}
  </div>
  <div class="vcard">
    <div class="vh2">Live score distribution</div>
    <div class="vsub">How today's {len(scores)} scored countries spread across the 0–100 scale.</div>
    {dist}
    <div class="vh2" style="margin-top:14px">AUC by crisis type</div>
    {bytype or '<div class="vsub">Not enough labels per type.</div>'}
  </div>
</div>
<div style="padding:10px 12px;border-top:1px solid #000;font-size:11px;color:#555;line-height:1.6">
  <b>Honest note.</b> {bt.note} A heuristic stands in where live per-year DB scores
  are unavailable, so AUC here is illustrative of the framework, not a published
  result — the full historical study (Reinhart–Rogoff defaults, IMF restructurings,
  UCDP conflicts) is the path to a citable figure. Methodology: <a href="/methodology">/methodology</a>.
</div>
{_tabbar([("Browse","/"),("Dashboard","/dashboard"),("Compare","/compare"),("Map","/map"),("Studio","/studio"),("Validation",""),("API","/api"),("",""),("Exit","/")], active="Validation")}
</div></div></body></html>"""


def _build_world(points, clusters, regional, nodes, edges, as_of) -> str:
    scatter = _svg_scatter(points)
    network = _svg_network(nodes, edges)

    # cluster chips
    cl_html = ""
    for ci, (label, members) in enumerate(sorted(clusters.items())):
        col = _CLUSTER_PALETTE[ci % len(_CLUSTER_PALETTE)]
        chips = "".join(
            f'<a href="/worldstate/{m}" class="pill-band" style="border-color:{col};'
            f'color:{col}">{m}</a>' for m in sorted(members))
        cl_html += (f'<div style="margin-bottom:8px"><span style="font-weight:bold;font-size:11px">'
                    f'<span style="display:inline-block;width:10px;height:10px;background:{col};'
                    f'border:1px solid #000;margin-right:5px"></span>{label}</span> '
                    f'<span style="color:#888;font-size:10px">({len(members)})</span><br>{chips}</div>')

    # regional bars
    reg_html = ""
    for region, mean in sorted(regional.items(), key=lambda kv: -kv[1]):
        reg_html += (f'<div class="d-row"><span class="d-label">{region}</span>'
                     f'<span style="flex:1;margin:0 8px">{_haz_bar(mean/100)}</span>'
                     f'<span class="d-val">{mean:.1f}</span></div>')

    return _head("World Map â€” VisibleHand") + f"""
<body>
{_menubar(["File","Edit","View"])}
<div class="desktop"><div class="window">
{_titlebar("VisibleHand â€” Global State Map", "/")}
<div class="statbar">
  <span><span class="ldot"></span>{len(points)} country-states &#183; embedding vh-wsm-pca-0.1 &#183; {as_of}</span>
  <a href="/world/graph" style="font-size:10px">graph JSON &#x25B8;</a>
</div>
<div class="scrollable">

<div class="m-sect"><div class="m-sect-hdr">State-Space Map â€” PCA(2) of country embeddings</div>
  <div class="m-sect-body">
    <div class="infobox">Each point is a country's current <b>world state</b> projected to two
    dimensions. Neighbouring points are in similar political-economic states. Colour = risk band,
    size = composite score. Click a point to open its World-State.</div>
    {scatter}
    {_risk_legend()}
  </div></div>

<div class="m-sect"><div class="m-sect-hdr">State Clusters</div>
  <div class="m-sect-body">{cl_html}</div></div>

<div class="m-sect"><div class="m-sect-hdr">Regional Risk</div>
  <div class="m-sect-body">{reg_html}</div></div>

<div class="m-sect"><div class="m-sect-hdr">Contagion Network â€” strong trade links</div>
  <div class="m-sect-body" style="text-align:center">
    <div class="infobox" style="text-align:left">Nodes are countries (colour = risk), arranged by
    region; edges are major trade relationships through which shocks can propagate.</div>
    {network}
  </div></div>

</div>
<div class="winfooter"><span>VH-WSM v0.1 &#183; global state map</span>
  <a href="/model/leaderboard">Model leaderboard &#x25B8;</a></div>
{_tabbar([("Browse","/"),("Dashboard","/dashboard"),("Compare","/compare"),("Map","/map"),("World","/world"),("Terminal","/terminal"),("API","/api"),("",""),("Exit","/")], active="World")}
</div></div></body></html>"""


@router.get("/world", response_class=HTMLResponse, include_in_schema=False)
async def world_page(db: Session = Depends(get_db)) -> HTMLResponse:
    import json as _json
    from core.worldstate import registry as Rw
    from api.models.database import CountryStateFeature, CountryStateEmbedding

    feats = (db.query(CountryStateFeature)
             .filter(CountryStateFeature.model_version == Rw.FEATURE_VERSION)
             .order_by(CountryStateFeature.as_of_date.desc()).all())
    latest_feat: dict = {}
    for r in feats:
        latest_feat.setdefault(r.country_code, r)

    embs = (db.query(CountryStateEmbedding)
            .filter(CountryStateEmbedding.embedding_version == Rw.EMBEDDING_VERSION)
            .order_by(CountryStateEmbedding.as_of_date.desc()).all())
    latest_emb: dict = {}
    for r in embs:
        latest_emb.setdefault(r.country_code, r)

    if not latest_emb:
        return HTMLResponse(
            _head("World Map â€” n/a") +
            '<body><div class="desktop"><div class="window">' +
            _titlebar("VisibleHand â€” Global State Map", "/") +
            '<div style="padding:20px">No world-state embeddings yet. Run '
            '<code>python scripts/materialize_worldstate.py --date today --all</code> then '
            '<code>python scripts/build_analogue_index.py</code>.</div>'
            '</div></div></body></html>', status_code=404)

    points = []
    as_of = ""
    for code, e in latest_emb.items():
        try:
            vec = _json.loads(e.embedding)
        except Exception:
            continue
        if len(vec) < 2:
            continue
        f = latest_feat.get(code)
        score = float(f.visiblehand_score) if f else 50.0
        as_of = max(as_of, e.as_of_date)
        points.append({"code": code, "x": vec[0], "y": vec[1], "score": score,
                       "cluster": e.cluster_label})

    clusters: dict = {}
    for p in points:
        clusters.setdefault(p["cluster"] or "n/a", []).append(p["code"])

    regional: dict = {}
    counts: dict = {}
    for p in points:
        reg = Rw.REGION.get(p["code"], "Other")
        regional[reg] = regional.get(reg, 0.0) + p["score"]
        counts[reg] = counts.get(reg, 0) + 1
    regional = {k: regional[k] / counts[k] for k in regional}

    score_map = {p["code"]: p["score"] for p in points}
    nodes = sorted(points, key=lambda p: (_REGION_ORDER.index(Rw.REGION.get(p["code"], "Other"))
                                          if Rw.REGION.get(p["code"]) in _REGION_ORDER else 99,
                                          p["code"]))
    edges = []
    seen = set()
    for c in score_map:
        for p, wgt in Rw.TRADE_PARTNERS.get(c, {}).items():
            if p in score_map and wgt >= 0.3:
                key = tuple(sorted((c, p)))
                if key not in seen:
                    seen.add(key)
                    edges.append((key[0], key[1], wgt))

    return HTMLResponse(_build_world(points, clusters, regional, nodes, edges, as_of))


def _latest_scores(db: Session) -> list:
    """Latest CountryScore per country, ranked by composite (robust to snapshot count)."""
    from sqlalchemy import func
    sub = (db.query(CountryScore.country_code.label("cc"),
                    func.max(CountryScore.computed_at).label("mx"))
           .group_by(CountryScore.country_code).subquery())
    rows = (db.query(CountryScore)
            .join(sub, (CountryScore.country_code == sub.c.cc)
                       & (CountryScore.computed_at == sub.c.mx)).all())
    return sorted(rows, key=lambda r: r.composite, reverse=True)


@router.get("/compare", response_class=HTMLResponse, include_in_schema=False)
async def compare_page(countries: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
    latest = _latest_scores(db)
    by_code = {r.country_code: r for r in latest}
    codes = [c.strip().upper() for c in countries.split(",") if c.strip()]
    codes = [c for c in codes if c in by_code][:6]
    if not codes:
        default = ["US", "DE", "BR", "ZA", "TR", "AR"]
        codes = [c for c in default if c in by_code] or [r.country_code for r in latest[:6]]
    selected = [by_code[c] for c in codes]
    if not selected:
        return HTMLResponse(
            _head("Compare — n/a") +
            '<body><div class="desktop"><div class="window">' +
            _titlebar("VisibleHand — Country Comparison", "/") +
            '<div class="empty">No scores yet — seed the database first.</div>'
            '</div></div></body></html>', status_code=404)
    return HTMLResponse(_build_compare(selected, latest))


@router.get("/map", response_class=HTMLResponse, include_in_schema=False)
async def map_page(db: Session = Depends(get_db)) -> HTMLResponse:
    latest = _latest_scores(db)
    if not latest:
        return HTMLResponse(
            _head("Risk Map — n/a") +
            '<body><div class="desktop"><div class="window">' +
            _titlebar("VisibleHand — Risk Map", "/") +
            '<div class="empty">No scores yet — seed the database first.</div>'
            '</div></div></body></html>', status_code=404)
    return HTMLResponse(_build_map(latest))


@router.get("/studio", response_class=HTMLResponse, include_in_schema=False)
async def studio_page(db: Session = Depends(get_db)) -> HTMLResponse:
    latest = _latest_scores(db)
    if not latest:
        return HTMLResponse(
            _head("Studio — n/a") +
            '<body><div class="desktop"><div class="window">' +
            _titlebar("VisibleHand — Data Studio", "/") +
            '<div class="empty">No scores yet — seed the database first.</div>'
            '</div></div></body></html>', status_code=404)
    return HTMLResponse(_build_studio(latest))


@router.get("/validation", response_class=HTMLResponse, include_in_schema=False)
async def validation_page(db: Session = Depends(get_db)) -> HTMLResponse:
    from api.routers.calibration import _cached_backtest, _cached_evaluation
    bt = _cached_backtest()
    try:
        ev = _cached_evaluation(2000)
    except Exception:
        ev = None
    try:
        from core.calibration.hazard_model import train_from_panel
        hz = train_from_panel(db)
    except Exception:
        hz = None
    scores = _latest_scores(db)
    return HTMLResponse(_build_validation(bt, scores, ev=ev, hz=hz))


# â”€â”€ ASCII terminal: rotating 3D globe + ASCII charts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_TERMINAL_CSS = """
.crt{
  background:#000;color:#33ff66;
  font-family:"Cascadia Mono",Consolas,"DejaVu Sans Mono",Monaco,"Courier New",monospace;
  font-size:12px;line-height:1.15;padding:10px 12px 16px;position:relative;overflow:hidden;
}
.crt::after{
  content:"";position:absolute;inset:0;pointer-events:none;
  background:repeating-linear-gradient(to bottom,rgba(0,0,0,0) 0,rgba(0,0,0,0) 2px,rgba(0,0,0,0.25) 3px);
  mix-blend-mode:multiply;
}
.crt pre{margin:0;font:inherit;white-space:pre;text-shadow:0 0 4px currentColor}
.crt .head{color:#7dffa8;text-shadow:0 0 6px #33ff66}
.crt .dim{color:#1f7a40}
.crt .lbl{color:#8af0ff}
.crt .b0{color:#39ff8d}.crt .b1{color:#9dff3c}.crt .b2{color:#ffe24a}
.crt .b3{color:#ff9c2a}.crt .b4{color:#ff4d4d}
.crt .g{color:#176b35}
.crt .blink{animation:bl 1s steps(2) infinite}
@keyframes bl{50%{opacity:0}}
.crt .grid2{display:grid;grid-template-columns:auto 1fr;gap:6px 22px;align-items:start}
.crt .sec{margin-top:14px}
.crt .sec-t{color:#7dffa8;border-bottom:1px solid #176b35;padding-bottom:2px;margin-bottom:6px}
#globe{color:#33ff66;min-height:300px}
.crt a{color:#8af0ff;text-decoration:none}.crt a:hover{text-shadow:0 0 6px #8af0ff}
"""

_TERMINAL_JS = """
(function(){
  var mk = JSON.parse(document.getElementById('mk').textContent || '[]');
  var el = document.getElementById('globe');
  if(!el) return;
  var W=70, H=32, cx=W/2, cy=H/2, R=14;
  var theta=0.4;
  // graticule points
  var GR=[];
  for(var la=-80; la<=80; la+=20){ for(var lo=0; lo<360; lo+=7){ GR.push([la*Math.PI/180, lo*Math.PI/180]); } }
  for(var lo2=0; lo2<360; lo2+=20){ for(var la2=-86; la2<=86; la2+=5){ GR.push([la2*Math.PI/180, lo2*Math.PI/180]); } }
  function band(r){ if(r<20)return 'b0'; if(r<40)return 'b1'; if(r<60)return 'b2'; if(r<75)return 'b3'; return 'b4'; }
  function mchar(r){ if(r<40)return 'o'; if(r<60)return 'O'; if(r<75)return '#'; return '@'; }
  function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
  function frame(){
    var ch=[], col=[], zb=[];
    for(var y=0;y<H;y++){ ch.push(new Array(W).fill(' ')); col.push(new Array(W).fill('g')); zb.push(new Array(W).fill(-2)); }
    var i, p, x, yv, z, sx, sy;
    for(i=0;i<GR.length;i++){
      p=GR[i];
      x=Math.cos(p[0])*Math.sin(p[1]+theta); yv=Math.sin(p[0]); z=Math.cos(p[0])*Math.cos(p[1]+theta);
      if(z<0) continue;
      sx=Math.round(cx+x*R*2.0); sy=Math.round(cy-yv*R);
      if(sx<0||sx>=W||sy<0||sy>=H) continue;
      if(z>zb[sy][sx]){ zb[sy][sx]=z; ch[sy][sx]= z>0.55?':':'.'; col[sy][sx]='g'; }
    }
    for(i=0;i<mk.length;i++){
      var m=mk[i], la=m.lat*Math.PI/180, lo=m.lon*Math.PI/180;
      x=Math.cos(la)*Math.sin(lo+theta); yv=Math.sin(la); z=Math.cos(la)*Math.cos(lo+theta);
      if(z<0) continue;
      sx=Math.round(cx+x*R*2.0); sy=Math.round(cy-yv*R);
      if(sx<0||sx>=W||sy<0||sy>=H) continue;
      if(z+0.02>=zb[sy][sx]){ zb[sy][sx]=z+0.02; ch[sy][sx]=mchar(m.risk); col[sy][sx]=band(m.risk); }
    }
    var html='';
    for(var yy=0;yy<H;yy++){
      var run='', cur=null, line='';
      for(var xx=0;xx<W;xx++){
        var c=ch[yy][xx], cl=col[yy][xx];
        if(cl!==cur){ if(run!=='') line+='<span class="'+cur+'">'+esc(run)+'</span>'; run=c; cur=cl; }
        else run+=c;
      }
      if(run!=='') line+='<span class="'+cur+'">'+esc(run)+'</span>';
      html+=line+'\\n';
    }
    el.innerHTML=html;
    theta+=0.025;
    setTimeout(function(){ requestAnimationFrame(frame); }, 55);
  }
  frame();
})();
"""


def _terminal_page(latest: list) -> str:
    ranked = sorted(latest, key=lambda r: r.composite, reverse=True)

    # Markers for the rotating globe
    markers = []
    for r in ranked:
        g = GEO.get(r.country_code)
        if g:
            markers.append({"code": r.country_code, "lat": g[0], "lon": g[1],
                            "risk": round(r.composite, 1)})
    markers_json = json.dumps(markers)

    # ASCII horizontal bar chart (server-rendered)
    bar_lines = []
    for r in ranked:
        cls = _band_cls(r.composite)
        name = _COUNTRY_NAMES.get(r.country_code, r.country_code)[:14].ljust(14)
        bar = _ascii_bar(r.composite, 22)
        lvl = _risk_label(r.composite).ljust(9)
        bar_lines.append(
            f'<span class="dim">{r.country_code}</span> {name}'
            f'<span class="{cls}">{bar}</span> '
            f'<span class="{cls}">{r.composite:>5.1f}</span> '
            f'<span class="dim">{lvl}</span>'
        )
    bars = "\n".join(bar_lines) if bar_lines else "  (no scores â€” run the seed script)"

    # Risk-band histogram
    bands = [("VERY LOW", 0, 20, "b0"), ("LOW", 20, 40, "b1"), ("MODERATE", 40, 60, "b2"),
             ("HIGH", 60, 75, "b3"), ("VERY HIGH+", 75, 1000, "b4")]
    hist_lines = []
    for name, lo, hi, cls in bands:
        cnt = sum(1 for r in ranked if lo <= r.composite < hi)
        hist_lines.append(f'<span class="dim">{name.ljust(11)}</span>'
                          f'<span class="{cls}">{"â–ˆ" * cnt}</span> {cnt}')
    hist = "\n".join(hist_lines)

    # Regional averages
    reg_lines = []
    for region in _REGION_ORDER:
        members = [r for r in ranked if GEO.get(r.country_code, (0, 0, ""))[2] == region]
        if not members:
            continue
        avg = sum(r.composite for r in members) / len(members)
        cls = _band_cls(avg)
        bar = _ascii_bar(avg, 22)
        reg_lines.append(f'<span class="lbl">{region.ljust(13)}</span>'
                         f'<span class="{cls}">{bar}</span> '
                         f'<span class="{cls}">{avg:>5.1f}</span> '
                         f'<span class="dim">n={len(members)}</span>')
    regions = "\n".join(reg_lines)

    n = len(ranked)
    avg_all = sum(r.composite for r in ranked) / n if n else 0
    hi = ranked[0] if ranked else None
    hi_txt = f"{hi.country_code} {hi.composite:.1f}" if hi else "â€”"

    banner = (
        '<span class="head">'
        'â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n'
        'â•‘   VISIBLEHAND â–‘â–’â–“ GLOBAL RISK TERMINAL â–“â–’â–‘               v0.3     â•‘\n'
        'â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•'
        '</span>'
    )
    statline = (f'<span class="dim">$</span> risk --world  '
                f'<span class="lbl">countries</span>={n}  '
                f'<span class="lbl">avg</span>={avg_all:.1f}  '
                f'<span class="lbl">peak</span>={hi_txt}  '
                f'<span class="blink">â–ˆ</span>')

    return _head("Terminal â€” VisibleHand") + (
        "<body>"
        + _menubar(["File", "Edit", "View"])
        + '<div class="desktop"><div class="window">'
        + _titlebar("VisibleHand Terminal â€” global_risk.ascii", "/")
        + '<style>' + _TERMINAL_CSS + '</style>'
        + '<div class="crt">'
        + f'<pre>{banner}</pre>'
        + f'<pre class="sec">{statline}</pre>'
        + '<div class="sec"><div class="sec-t">// LIVE ROTATION â”€ front hemisphere Â· markers = scored countries</div>'
        + '<pre id="globe">initialising orbital scanâ€¦</pre>'
        + '<pre class="dim">  legend:  o low   O moderate   # high   @ critical      Â· graticule</pre></div>'
        + '<div class="sec"><div class="sec-t">// RISK LADDER â”€ all countries, descending</div>'
        + f'<pre>{bars}</pre></div>'
        + '<div class="grid2 sec">'
        + '<div><div class="sec-t">// DISTRIBUTION</div>' + f'<pre>{hist}</pre></div>'
        + '<div><div class="sec-t">// REGIONAL MEAN</div>' + f'<pre>{regions}</pre></div>'
        + '</div>'
        + '<pre class="sec dim">  data: World Bank Â· IMF Â· BIS Â· GDELT/ACLED Â· V-Dem Â· WJP Â· TI Â· FH Â· NLP'
        + '   Â·   <a href="/dashboard">[dashboard]</a> <a href="/world">[world]</a> <a href="/api">[api]</a> <a href="/methodology">[methodology]</a></pre>'
        + '</div>'  # /crt
        + f'<script type="application/json" id="mk">{markers_json}</script>'
        + '<script>' + _TERMINAL_JS + '</script>'
        + _tabbar([("Browse", "/"), ("Dashboard", "/dashboard"), ("World", "/world"),
                   ("Terminal", "/terminal"), ("API", "/api"), ("", ""), ("Exit", "/")],
                  active="Terminal")
        + '</div></div></body></html>'
    )


@router.get("/terminal", response_class=HTMLResponse, include_in_schema=False)
async def terminal(db: Session = Depends(get_db)) -> HTMLResponse:
    from sqlalchemy import func
    sub = (
        db.query(
            CountryScore.country_code.label("cc"),
            func.max(CountryScore.computed_at).label("mx"),
        )
        .group_by(CountryScore.country_code)
        .subquery()
    )
    latest_rows = (
        db.query(CountryScore)
        .join(sub, (CountryScore.country_code == sub.c.cc)
                   & (CountryScore.computed_at == sub.c.mx))
        .all()
    )
    return HTMLResponse(_terminal_page(latest_rows))


@router.get("/methodology", response_class=HTMLResponse, include_in_schema=False)
async def methodology_page() -> HTMLResponse:
    try:
        from core.scoring.composite import DEFAULT_WEIGHTS
        weights = DEFAULT_WEIGHTS
    except Exception:
        weights = {"economic": 0.45, "political": 0.25, "nlp_sentiment": 0.20, "governance": 0.10}

    try:
        from core.calibration.backtest import run_backtest
        bt = run_backtest()
        cal_rows = (
            f'<div class="d-row"><span class="d-label">ROC-AUC</span><span class="d-val">{bt.auc:.3f}</span></div>'
            f'<div class="d-row"><span class="d-label">Brier score</span><span class="d-val">{bt.brier_score:.3f}</span></div>'
            f'<div class="d-row"><span class="d-label">PR-AUC</span><span class="d-val">{bt.pr_auc:.3f}</span></div>'
            f'<div class="d-row"><span class="d-label">Events (n)</span><span class="d-val">{bt.n_events}</span></div>'
            f'<div class="d-row"><span class="d-label">Crises (n)</span><span class="d-val">{bt.n_crises}</span></div>'
        )
        bt_note = bt.note
    except Exception:
        cal_rows = '<div class="d-row"><span class="d-label">AUC</span><span class="d-val">unavailable â€” run /calibration/roc</span></div>'
        bt_note = "Backtest unavailable. Run /calibration/roc to trigger."

    def wrow(name, pct, sources):
        bar_w = int(pct * 100)
        return (f'<tr><td class="mono">{name}</td>'
                f'<td style="font-weight:bold">{pct*100:.0f}%'
                f'<span class="wt-bar" style="width:{bar_w}px"></span></td>'
                f'<td style="color:#555">{sources}</td></tr>')

    weight_rows = (
        wrow("economic",     weights.get("economic", 0.45),       "World Bank WDI Â· IMF WEO Â· BIS Â· ILO Â· IMF FSI") +
        wrow("political",    weights.get("political", 0.25),      "GDELT Â· ACLED") +
        wrow("nlp_sentiment",weights.get("nlp_sentiment", 0.20),  "Central-bank statements (FinBERT + lexicon)") +
        wrow("governance",   weights.get("governance", 0.10),     "V-Dem Â· WJP Â· TI CPI Â· Freedom House")
    )

    return HTMLResponse(_head("Methodology â€” VisibleHand") + f"""
<body>
{_menubar(["File","Edit","Go"])}
<div class="desktop"><div class="window">
{_titlebar("VisibleHand â€” Methodology v0.3", "/")}
<div class="statbar">
  <span>Scoring model v0.3.0 Â· Calibration preprint in preparation (SSRN Q4 2026)</span>
  <a href="/calibration/roc" style="font-size:10px">ROC data &#x25B8;</a>
</div>
<div class="scrollable">

<div class="m-sect">
  <div class="m-sect-hdr">Overview</div>
  <div class="m-sect-body">
    <div class="infobox">
      VisibleHand scores countries 0â€“100 by blending four sub-scorers. Each scorer is
      normalised against the country's own historical baseline using robust statistics
      (median/MAD), so scores reflect deviation from self â€” not rank among peers.
      A score of 50 means typical historical conditions for that country.
    </div>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">Component Weights</div>
  <div class="m-sect-body">
    <table class="m-tbl">
      <thead><tr><th>Component</th><th>Weight</th><th>Primary Sources</th></tr></thead>
      <tbody>{weight_rows}</tbody>
    </table>
    <p style="font-size:10px;color:#666;margin-top:6px">
      Weights derived from backtested AUC optimisation. Override via POST /risk/&#123;code&#125; with weight fields.
    </p>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">Economic Component</div>
  <div class="m-sect-body">
    <div class="infobox">
      10 macro indicators. Each is normalised to a 0â€“100 risk scale using
      robust median/MAD against own history, then combined with Theil-Sen
      trend weighting. Missing data is imputed conservatively.
    </div>
    <table class="m-tbl" style="margin-top:6px">
      <thead><tr><th>Indicator</th><th>Source</th><th>Direction</th></tr></thead>
      <tbody>
        <tr><td class="mono">gdp_growth</td><td>World Bank WDI</td><td>â†“ high growth = lower risk</td></tr>
        <tr><td class="mono">inflation</td><td>World Bank WDI Â· IMF</td><td>â†‘ high inflation = higher risk</td></tr>
        <tr><td class="mono">debt_to_gdp</td><td>IMF WEO</td><td>â†‘ high debt = higher risk</td></tr>
        <tr><td class="mono">fx_reserves</td><td>World Bank Â· IMF</td><td>â†“ low reserves = higher risk</td></tr>
        <tr><td class="mono">current_account</td><td>World Bank WDI</td><td>â†‘ large deficit = higher risk</td></tr>
        <tr><td class="mono">unemployment</td><td>ILO Â· World Bank</td><td>â†‘ high unemployment = higher risk</td></tr>
        <tr><td class="mono">bank_npl</td><td>IMF FSI</td><td>â†‘ high NPL = higher risk</td></tr>
        <tr><td class="mono">tax_revenue</td><td>World Bank WDI</td><td>â†“ low revenue = higher risk</td></tr>
        <tr><td class="mono">remittances</td><td>World Bank WDI</td><td>context-dependent</td></tr>
        <tr><td class="mono">credit_gap</td><td>BIS</td><td>â†‘ large gap = higher risk</td></tr>
      </tbody>
    </table>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">Political Component</div>
  <div class="m-sect-body">
    <div class="infobox">
      Hawkes process fitted per-country on GDELT/ACLED event feeds. The branching
      ratio Ï measures self-sustaining instability (Ï â†’ 1 = near-critical).
      A contagion network layer adds neighbor-country spillover. Events are typed
      (protest, conflict, coup, sanction, leadership change, election) and weighted by severity.
    </div>
    <div class="two-col" style="margin-top:6px">
      <div style="padding:8px">
        <div style="font-size:10px;font-weight:bold;margin-bottom:4px">Sources</div>
        <div class="infobox" style="margin:0">
          GDELT Global Database of Events (real-time)<br>
          ACLED Armed Conflict Location &amp; Event Data<br>
          Deduplicated by day/type, max-severity kept
        </div>
      </div>
      <div style="padding:8px">
        <div style="font-size:10px;font-weight:bold;margin-bottom:4px">Hawkes Parameters</div>
        <div class="infobox" style="margin:0">
          Î¼ (background rate): baseline event frequency<br>
          Î± (excitation): cross-event triggering<br>
          Î² (decay): excitation half-life (~7 days)<br>
          Fitted via Nelder-Mead MLE
        </div>
      </div>
    </div>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">NLP Component â€” Central-Bank Hawkishness</div>
  <div class="m-sect-body">
    <div class="infobox">
      Hybrid FinBERT ONNX + domain lexicon reads central-bank statements.
      Higher scores = more hawkish/stressed language = higher risk contribution.
    </div>
    <table class="m-tbl" style="margin-top:6px">
      <thead><tr><th>Aspect</th><th>What it captures</th></tr></thead>
      <tbody>
        <tr><td class="mono">monetary_policy</td><td>Rate language, tightening/easing signals</td></tr>
        <tr><td class="mono">fiscal_policy</td><td>Budget, deficit, sustainability mentions</td></tr>
        <tr><td class="mono">financial_stability</td><td>Banking stress, systemic risk language</td></tr>
        <tr><td class="mono">external_sector</td><td>Exchange rate, reserves, capital flows</td></tr>
        <tr><td class="mono">political_economy</td><td>Institutional risk, reform uncertainty</td></tr>
      </tbody>
    </table>
    <p style="font-size:10px;color:#666;margin-top:6px">
      Score 0â€“100: 0 = very dovish/stable, 100 = very hawkish/stressed.
      Statements from Fed, ECB, BoE, Banco Central, NBU, RBI, SARB, and others.
    </p>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">Governance Component</div>
  <div class="m-sect-body">
    <div class="infobox">
      Four institutional quality measures, cross-sectionally normalised then
      adjusted toward own-history baseline. Governance changes slowly â€”
      data typically updated annually.
    </div>
    <table class="m-tbl" style="margin-top:6px">
      <thead><tr><th>Source</th><th>Indicators used</th><th>Coverage</th></tr></thead>
      <tbody>
        <tr><td>V-Dem</td><td>Rule of law, corruption, judicial independence</td><td>1900â€“present</td></tr>
        <tr><td>WJP Rule of Law</td><td>Composite rule-of-law index</td><td>2012â€“present</td></tr>
        <tr><td>TI CPI</td><td>Corruption Perceptions Index</td><td>1995â€“present</td></tr>
        <tr><td>Freedom House</td><td>Political rights + civil liberties</td><td>1973â€“present</td></tr>
      </tbody>
    </table>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">Score Bands &amp; Interpretation</div>
  <div class="m-sect-body">
    <div class="risk-band-row"><span class="band-swatch dvl"></span><span class="band-range mono">0 â€“ 19</span><span class="band-label">VERY LOW</span><span class="band-desc">Structural stability. No acute risk factors above historical norm.</span></div>
    <div class="risk-band-row"><span class="band-swatch dlo"></span><span class="band-range mono">20 â€“ 39</span><span class="band-label">LOW</span><span class="band-desc">Minor vulnerabilities. Within manageable range for this country.</span></div>
    <div class="risk-band-row"><span class="band-swatch dmd"></span><span class="band-range mono">40 â€“ 59</span><span class="band-label">MODERATE</span><span class="band-desc">Meaningful risk. Active monitoring warranted. Elevated vs baseline.</span></div>
    <div class="risk-band-row"><span class="band-swatch dhi"></span><span class="band-range mono">60 â€“ 74</span><span class="band-label">HIGH</span><span class="band-desc">Significant stress. Near-term policy response or intervention likely.</span></div>
    <div class="risk-band-row"><span class="band-swatch dvh"></span><span class="band-range mono">75 â€“ 89</span><span class="band-label">VERY HIGH</span><span class="band-desc">Acute crisis conditions. Multiple risk factors simultaneously elevated.</span></div>
    <div class="risk-band-row"><span class="band-swatch dvh"></span><span class="band-range mono">90 â€“ 100</span><span class="band-label">CRITICAL</span><span class="band-desc">Active crisis or severe institutional breakdown.</span></div>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">Bayesian Confidence Interval</div>
  <div class="m-sect-body">
    <div class="infobox">
      Every score ships a 95% CI computed from 500-sample Monte Carlo
      perturbation of the input indicators. Wider CI = less data or higher
      sensitivity to individual indicators. Confidence (0â€“1) reflects data
      coverage: 1.0 = all 10 economic indicators + events + NLP + governance present.
    </div>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">6 / 12-Month Forecast</div>
  <div class="m-sect-body">
    <div class="infobox warn">
      âš  The forecast is Theil-Sen extrapolation of score history combined
      with IMF WEO macro projections. It is NOT a prediction model.
      It extends current trends linearly. Use for scenario planning only.
      CI widens linearly with horizon.
    </div>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">Calibration â€” Backtest on Crisis Events</div>
  <div class="m-sect-body">
    <div class="two-col">
      <div style="padding:6px 0">
        {cal_rows}
      </div>
      <div style="padding:6px 8px">
        <div class="infobox" style="margin:0">
          Dataset: ~220 crisis events (sovereign defaults, IMF programmes,
          currency crises, banking crises, civil war onsets, coups).<br>
          Sources: IMF HPDD Â· Laeven &amp; Valencia (2012/2018) Â· UCDP Â·
          REIGN Â· World Bank (2000â€“2023).
        </div>
      </div>
    </div>
    <p style="font-size:10px;color:#666;margin-top:6px">{bt_note}</p>
    <div style="margin-top:8px;display:flex;gap:12px;flex-wrap:wrap">
      <a href="/calibration/roc" style="font-size:11px">Full ROC data &#x25B8;</a>
      <a href="/calibration/dataset" style="font-size:11px">Crisis event dataset &#x25B8;</a>
      <a href="/calibration/summary" style="font-size:11px">JSON summary &#x25B8;</a>
    </div>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">Limitations &amp; Known Issues</div>
  <div class="m-sect-body">
    <div class="infobox warn">
      âš  Scores are relative to own history â€” a country that has always been
      unstable may score low even during acute crises. Cross-country comparison
      of raw scores should be done with care.
    </div>
    <div class="infobox" style="margin-top:6px">
      NLP component requires central-bank statements in the database. Without
      statements, NLP defaults to 50 (neutral). The governance layer updates
      annually with source data; intra-year governance shifts are not captured.
    </div>
  </div>
</div>

</div><!-- /.scrollable -->
<div class="winfooter">
  <span>VisibleHand v0.3 Â· MIT Â· Calibration preprint: SSRN Q4 2026</span>
  <a href="/api">API Reference &#x25B8;</a>
</div>
{_tabbar([("Browse","/"),("Dashboard","/dashboard"),("Terminal","/terminal"),("API","/api"),("Methodology","/methodology"),("",""),("Exit","/")], active="Methodology")}
</div></div></body></html>""")


@router.get("/api", response_class=HTMLResponse, include_in_schema=False)
async def api_reference() -> HTMLResponse:

    def ep(method, path, desc, params="", resp=""):
        badge = f'<span class="badge {method.lower()}">{method}</span>'
        detail = ""
        if params:
            detail += f'<div style="margin-top:4px;font-size:10px;color:#555">{params}</div>'
        if resp:
            detail += f'<div style="margin-top:3px;font-size:10px;color:#888">{resp}</div>'
        return (f'<tr>'
                f'<td>{badge}</td>'
                f'<td class="mono" style="white-space:nowrap">{path}</td>'
                f'<td>{desc}{detail}</td>'
                f'</tr>')

    endpoints = (
        ep("GET", "/risk/{code}", "Composite risk score + 95% CI + driver attributions + forecast",
           "code: ISO-3166 alpha-2 (e.g. US, AR, UA)",
           "â†’ RiskResponse Â· computed fresh or from cache"),
        ep("GET", "/risk/compare", "Compare up to 10 countries in one call",
           "countries: comma-separated codes (e.g. US,BR,AR,DE)",
           "â†’ list[RiskResponse]"),
        ep("GET", "/risk/{code}/history", "All stored score snapshots for a country",
           "limit: int (default 100) Â· offset: int",
           "â†’ list[HistoryPoint]"),
        ep("GET", "/risk/{code}/drivers", "Signed per-indicator driver attributions",
           "code: country code",
           "â†’ list[DriverAttribution]"),
        ep("GET", "/risk/{code}/aspects", "5-aspect NLP breakdown (central-bank statement)",
           "code: country code",
           "â†’ AspectScoresResponse"),
        ep("GET", "/risk/{code}/forecast", "6-month and 12-month score extrapolations",
           "code: country code",
           "â†’ &#123; '6m': ForecastPoint, '12m': ForecastPoint &#125;"),
        ep("GET", "/risk/movers", "Countries with largest risk score change (7-day window)",
           "limit: int (default 10)",
           "â†’ list[MoverPoint]"),
        ep("GET", "/risk/bulk", "Batch score multiple countries (POST body)",
           "body: &#123; countries: [code, â€¦] &#125;",
           "â†’ list[RiskResponse]"),
        ep("GET", "/indicators/{code}", "Raw economic indicator time series",
           "code: country Â· metric: filter by name",
           "â†’ list[IndicatorRow]"),
        ep("GET", "/events/{code}", "Political event feed with severity scores",
           "code: country Â· limit: int",
           "â†’ list[EventRow]"),
        ep("GET", "/governance/{code}", "Governance sub-scores (V-Dem, WJP, TI, FH)",
           "code: country",
           "â†’ GovernanceResponse"),
        ep("GET", "/nlp/{code}", "Central-bank NLP hawkishness + latest statement text",
           "code: country",
           "â†’ NLPResponse"),
        ep("GET", "/calibration/summary", "Methodology, component weights, AUC estimate",
           "",
           "â†’ CalibrationSummary"),
        ep("GET", "/calibration/roc", "Full ROC/PR curve data Â· include_curve=true for arrays",
           "include_curve: bool",
           "â†’ ROCResult"),
        ep("GET", "/calibration/dataset", "Crisis event dataset (220 events, 2000â€“2023)",
           "",
           "â†’ &#123; n_total, events: [â€¦] &#125;"),
        ep("GET", "/health", "API health + DB connectivity + scored country count",
           "",
           "â†’ HealthResponse"),
        ep("GET", "/health/ready", "Kubernetes readiness probe",
           "",
           "â†’ 200 / 503"),
        ep("GET", "/metrics", "Prometheus scrape endpoint",
           "",
           "â†’ text/plain"),
    )

    return HTMLResponse(_head("API Reference â€” VisibleHand") + f"""
<body>
{_menubar(["File","Edit","Go"])}
<div class="desktop"><div class="window">
{_titlebar("VisibleHand API Reference v0.3", "/")}
<div class="statbar">
  <span>Base URL: <span class="mono">https://api.visiblehand.xyz</span>&nbsp;&nbsp;&#183;&nbsp;&nbsp;MIT License</span>
  <a href="/docs" style="font-size:10px">Interactive Swagger &#x25B8;</a>
</div>
<div class="scrollable">

<div class="m-sect">
  <div class="m-sect-hdr">Authentication</div>
  <div class="m-sect-body">
    <div class="infobox">
      All read endpoints (<span class="mono">GET</span>) are public â€” no key required.
      Set <span class="mono">X-API-Key</span> header to bypass rate limits (contact for key).
    </div>
    <div class="infobox" style="margin-top:6px">
      <span style="font-weight:bold">Rate limit:</span>&nbsp;
      60 requests / minute per IP (default).
      429 Too Many Requests is returned when exceeded. Headers:
      <span class="mono">X-RateLimit-Limit</span>, <span class="mono">X-RateLimit-Remaining</span>.
    </div>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">Endpoints</div>
  <div class="m-sect-body" style="padding:0">
    <table class="m-tbl">
      <thead><tr><th style="width:52px">Method</th><th style="width:260px">Path</th><th>Description &amp; Parameters</th></tr></thead>
      <tbody>{"".join(endpoints)}</tbody>
    </table>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">Example â€” GET /risk/&#123;code&#125;</div>
  <div class="m-sect-body">
    <div class="two-col">
      <div style="padding-right:10px">
        <div style="font-size:10px;font-weight:bold;margin-bottom:4px">Request</div>
        <div class="doc-pre"><span class="g">$</span> <span class="k">curl</span> https://api.visiblehand.xyz/<span class="v">risk/AR</span>

<span class="g"># Optional weight overrides:</span>
<span class="g">$</span> <span class="k">curl</span> "â€¦/risk/AR?economic_weight=0.5
  &amp;political_weight=0.3
  &amp;nlp_weight=0.1
  &amp;governance_weight=0.1"</div>
        <div style="font-size:10px;font-weight:bold;margin:8px 0 4px">Parameters</div>
        <table class="m-tbl">
          <thead><tr><th>Param</th><th>Type</th><th>Default</th></tr></thead>
          <tbody>
            <tr><td class="param-name">economic_weight</td><td class="param-type">float</td><td>0.45</td></tr>
            <tr><td class="param-name">political_weight</td><td class="param-type">float</td><td>0.25</td></tr>
            <tr><td class="param-name">nlp_weight</td><td class="param-type">float</td><td>0.20</td></tr>
            <tr><td class="param-name">governance_weight</td><td class="param-type">float</td><td>0.10</td></tr>
          </tbody>
        </table>
      </div>
      <div style="padding-left:10px">
        <div style="font-size:10px;font-weight:bold;margin-bottom:4px">Response â€” 200 OK</div>
        <div class="doc-pre">{{
  <span class="k">"country"</span>:   <span class="s">"AR"</span>,
  <span class="k">"name"</span>:      <span class="s">"Argentina"</span>,
  <span class="k">"composite"</span>: <span class="v">84.3</span>,
  <span class="k">"ci_low"</span>:    <span class="v">77.1</span>,
  <span class="k">"ci_high"</span>:   <span class="v">91.2</span>,
  <span class="k">"confidence"</span>:<span class="v">0.82</span>,
  <span class="k">"risk_level"</span>:<span class="s">"Very High"</span>,
  <span class="k">"breakdown"</span>: {{
    <span class="k">"economic"</span>:   <span class="v">88.1</span>,
    <span class="k">"political"</span>:  <span class="v">71.0</span>,
    <span class="k">"nlp_sentiment"</span>:<span class="v">85.0</span>,
    <span class="k">"governance"</span>: <span class="v">79.4</span>
  }},
  <span class="k">"top_drivers"</span>: [
    <span class="s">"high_inflation"</span>,
    <span class="s">"high_debt_burden"</span>
  ],
  <span class="k">"driver_attributions"</span>: [
    {{<span class="k">"name"</span>:<span class="s">"high_inflation"</span>,
      <span class="k">"contribution"</span>:<span class="v">18.2</span>,
      <span class="k">"direction"</span>:<span class="s">"risk"</span>,
      <span class="k">"sub_scorer"</span>:<span class="s">"economic"</span>}}
  ],
  <span class="k">"forecast"</span>: {{
    <span class="k">"6m"</span>: {{<span class="k">"composite"</span>:<span class="v">87.0</span>,
           <span class="k">"ci_low"</span>:<span class="v">79.0</span>,<span class="k">"ci_high"</span>:<span class="v">95.0</span>}},
    <span class="k">"12m"</span>:{{<span class="k">"composite"</span>:<span class="v">90.1</span>,
           <span class="k">"ci_low"</span>:<span class="v">78.0</span>,<span class="k">"ci_high"</span>:<span class="v">100.0</span>}}
  }},
  <span class="k">"updated_at"</span>: <span class="s">"2026-06-27T14:30:00Z"</span>
}}</div>
      </div>
    </div>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">Error Codes</div>
  <div class="m-sect-body" style="padding:0">
    <table class="m-tbl">
      <thead><tr><th style="width:60px">Status</th><th>Meaning</th><th>Body</th></tr></thead>
      <tbody>
        <tr><td class="mono" style="font-weight:bold">200</td><td>OK</td><td>Requested resource</td></tr>
        <tr><td class="mono" style="font-weight:bold">404</td><td>Not Found</td><td><span class="mono">&#123;"detail":"â€¦"&#125;</span> â€” unknown country code or no data yet</td></tr>
        <tr><td class="mono" style="font-weight:bold">422</td><td>Validation Error</td><td><span class="mono">&#123;"detail":[â€¦]&#125;</span> â€” invalid parameter type/range</td></tr>
        <tr><td class="mono" style="font-weight:bold">429</td><td>Rate Limited</td><td><span class="mono">&#123;"error":"rate limit exceeded"&#125;</span></td></tr>
        <tr><td class="mono" style="font-weight:bold">500</td><td>Server Error</td><td><span class="mono">&#123;"detail":"internal server error"&#125;</span></td></tr>
      </tbody>
    </table>
  </div>
</div>

<div class="m-sect">
  <div class="m-sect-hdr">SDK â€” Python Client</div>
  <div class="m-sect-body">
    <div class="doc-pre"><span class="g"># Install</span>
<span class="k">pip install</span> visiblehand

<span class="g"># Sync</span>
<span class="k">from</span> visiblehand <span class="k">import</span> Client
c = Client()
score = c.risk(<span class="s">"AR"</span>)
<span class="k">print</span>(score.composite, score.risk_level)

<span class="g"># Async</span>
<span class="k">from</span> visiblehand <span class="k">import</span> AsyncClient
<span class="k">async with</span> AsyncClient() <span class="k">as</span> c:
    scores = <span class="k">await</span> c.compare([<span class="s">"US"</span>, <span class="s">"BR"</span>, <span class="s">"AR"</span>])</div>
    <div style="margin-top:6px;font-size:10px;color:#666">
      SDK source: <span class="mono">sdk/visiblehand/__init__.py</span> Â· Install locally: <span class="mono">pip install -e sdk/</span>
    </div>
  </div>
</div>

</div><!-- /.scrollable -->
<div class="winfooter">
  <span>VisibleHand v0.3 Â· MIT License Â· Free &amp; open-source</span>
  <a href="/docs" style="font-size:10px">Interactive Swagger &#x25B8;</a>
</div>
{_tabbar([("Browse","/"),("Dashboard","/dashboard"),("Terminal","/terminal"),("API","/api"),("Methodology","/methodology"),("",""),("Exit","/")], active="API")}
</div></div></body></html>""")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing() -> HTMLResponse:
    return HTMLResponse(_head("VisibleHand â€” Open Country Risk API") + """
<body>
<div class="menubar">
  <span class="apple">&#x2318;</span>
  <span class="mi">File</span><span class="mi">Edit</span><span class="mi">Go</span>
  <span class="mi-r">VisibleHand v0.3</span>
</div>
<div class="desktop">
<div class="window">
<div class="titlebar">
  <div class="closebox"></div>
  <div class="titletext">VisibleHand â€” Open Country Risk API</div>
  <div class="zoombox">&#x25B8;</div>
</div>

<div class="hero">
  <div class="hero-l">
    <hr class="hero-rule">
    <div class="hero-h1">VisibleHand<br>Risk Monitor</div>
    <hr class="hero-rule">
    <div class="cbx-row"><span class="cbx"></span> Introduction</div>
    <p class="intro">
      An open, programmable political-economic risk score for every country â€”
      built from live World Bank, IMF, GDELT/ACLED, V-Dem data and NLP on
      central-bank statements. Free. Calibrated. Transparent.<br><br>
      Click the Dashboard tab below after you've seen the Introduction.
    </p>
    <div>
      <a class="mac-btn def" href="/dashboard">Live Dashboard</a>
      <a class="mac-btn" href="/studio">Data Studio</a>
      <a class="mac-btn" href="/compare">Compare</a>
      <a class="mac-btn" href="/map">Risk Map</a>
      <a class="mac-btn" href="/validation">Validation</a>
      <a class="mac-btn" href="/world">World Map</a>
      <a class="mac-btn" href="/terminal">ASCII Terminal</a>
      <a class="mac-btn" href="/docs">API Docs</a>
      <a class="mac-btn" href="/methodology">Methodology</a>
    </div>
  </div>
  <div class="hero-r">
    <div class="code-win"><span class="g">$ </span><span class="k">curl</span> api.visiblehand.xyz/<span class="v">risk/AR</span>

{
  <span class="k">"country"</span>:    <span class="s">"AR"</span>,
  <span class="k">"composite"</span>:  <span class="v">84.3</span>,
  <span class="k">"ci_low"</span>:     <span class="v">77.1</span>,
  <span class="k">"ci_high"</span>:    <span class="v">91.2</span>,
  <span class="k">"confidence"</span>: <span class="v">0.82</span>,
  <span class="k">"risk_level"</span>: <span class="s">"Very High"</span>,
  <span class="k">"breakdown"</span>: {
    <span class="k">"economic"</span>:   <span class="v">88.1</span>,
    <span class="k">"political"</span>:  <span class="v">71.0</span>,
    <span class="k">"nlp"</span>:        <span class="v">85.0</span>,
    <span class="k">"governance"</span>: <span class="v">79.4</span>
  },
  <span class="k">"driver_attributions"</span>: [
    {<span class="k">"name"</span>: <span class="s">"high_inflation"</span>,  <span class="k">"contribution"</span>: <span class="v">18.2</span>},
    {<span class="k">"name"</span>: <span class="s">"high_debt_burden"</span>, <span class="k">"contribution"</span>: <span class="v">12.1</span>}
  ],
  <span class="k">"forecast"</span>: {
    <span class="k">"6m"</span>:  {<span class="k">"composite"</span>: <span class="v">87.0</span>, <span class="k">"ci"</span>: [<span class="v">79</span>, <span class="v">95</span>]},
    <span class="k">"12m"</span>: {<span class="k">"composite"</span>: <span class="v">90.1</span>, <span class="k">"ci"</span>: [<span class="v">78</span>, <span class="v">100</span>]}
  }
}</div>
  </div>
</div>

<div class="feat-hdr">What's in the Box</div>
<div class="feat-grid">
  <div class="fc"><div class="fc-h">Scored vs own history</div>
    <p class="fc-p">Robust median/MAD normalisation â€” a country is judged against its own trajectory, not a global mean.</p></div>
  <div class="fc"><div class="fc-h">Bayesian uncertainty</div>
    <p class="fc-p">Every score ships a 95% CI from 500-sample Monte Carlo. No commercial competitor publishes bounds.</p></div>
  <div class="fc"><div class="fc-h">Hawkish/dovish NLP</div>
    <p class="fc-p">FinBERT + domain lexicon reads central-bank statements with aspect-level breakdowns.</p></div>
  <div class="fc"><div class="fc-h">Hawkes process</div>
    <p class="fc-p">Political violence is self-exciting. We fit a Hawkes process per country and report the branching ratio.</p></div>
  <div class="fc"><div class="fc-h">Governance layer</div>
    <p class="fc-p">V-Dem, WJP Rule of Law, TI CPI, and Freedom House â€” structural factors that economic data misses.</p></div>
  <div class="fc"><div class="fc-h">6/12-month forecast</div>
    <p class="fc-p">Theil-Sen extrapolation on score history + IMF WEO projections. Transparent about what it is.</p></div>
</div>

<div class="winfooter">
  <span>Free &amp; open-source &nbsp;&#183;&nbsp; Commercial equivalents cost $15â€“50k/yr</span>
  <a href="/docs">API Documentation &#x25B8;</a>
</div>

<div class="tabbar">
  <a class="tab on" href="/">Browse</a>
  <a class="tab" href="/dashboard">Dashboard</a>
  <a class="tab" href="/world">World</a>
  <a class="tab" href="/terminal">Terminal</a>
  <a class="tab" href="/api">API</a>
  <a class="tab" href="/methodology">Methodology</a>
  <span class="tab-gap"></span>
  <a class="tab" href="/dashboard">Exit</a>
</div>
</div>
</div>
</body></html>""")
