"""
End-to-end smoke test against seeded data.
Covers all V3 endpoints — run after seed_demo_data.py.
Exit code 0 = all checks passed.
"""

from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient
from api.main import app

CODES = ["AR", "UA", "DE", "US", "BR", "NG", "IN", "ZA"]
PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {name}")
    else:
        print(f"  {FAIL}  {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


c = TestClient(app)

print("\n=== VisibleHand V3 Smoke Test ===\n")

# ── Health endpoints ──────────────────────────────────────────────────────────
print("[ Health ]")
h = c.get("/health")
check("GET /health 200", h.status_code == 200)
check("health.version = 0.3.0", h.json().get("version") == "0.3.0")

live = c.get("/health/live")
check("GET /health/live 200", live.status_code == 200)
check("health/live.status = alive", live.json().get("status") == "alive")

ready = c.get("/health/ready")
check("GET /health/ready 200 or 503", ready.status_code in (200, 503))

scores_h = c.get("/health/scores")
check("GET /health/scores 200", scores_h.status_code == 200)
check("health/scores has scored_countries", "scored_countries" in scores_h.json())

metrics = c.get("/metrics")
check("GET /metrics 200 or 503", metrics.status_code in (200, 503))

# ── Risk scoring ──────────────────────────────────────────────────────────────
print("\n[ Risk scoring ]")
for code in CODES:
    r = c.get(f"/risk/{code}")
    check(f"GET /risk/{code} 200", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        check(f"{code} composite in [0,100]", 0 <= data.get("composite", -1) <= 100)
        check(f"{code} has ci_low/ci_high", data.get("ci_low") is not None)
        check(f"{code} has confidence", data.get("confidence") is not None)
        check(f"{code} has driver_attributions", isinstance(data.get("driver_attributions"), list))
        check(f"{code} has governance", "governance" in data.get("breakdown", {}))
        eco = data["breakdown"].get("economic")
        pol = data["breakdown"].get("political")
        if eco and pol:
            name = data["name"][:14].ljust(14)
            print(f"      {code}  {name}  composite={data['composite']:>5}  "
                  f"[{data.get('ci_low',0):.1f}-{data.get('ci_high',0):.1f}]  "
                  f"conf={data['confidence']:.2f}  "
                  f"eco={eco:.0f}  pol={pol:.0f}  "
                  f"gov={data['breakdown'].get('governance', 'N/A')}")

# ── Validation ────────────────────────────────────────────────────────────────
print("\n[ Validation ]")
bad = c.get("/risk/BADCODE")
check("GET /risk/BADCODE 422", bad.status_code == 422)
bad2 = c.get("/risk/123")
check("GET /risk/123 422", bad2.status_code == 422)

# ── Compare ───────────────────────────────────────────────────────────────────
print("\n[ Compare & bulk ]")
cmp = c.get("/risk/compare?countries=AR,DE,US")
check("GET /risk/compare 200", cmp.status_code == 200)
check("compare returns 3 items", len(cmp.json()) == 3)

bulk = c.get("/risk/bulk")
check("GET /risk/bulk 200", bulk.status_code == 200)
check("bulk returns list", isinstance(bulk.json(), list))

movers = c.get("/risk/movers")
check("GET /risk/movers 200", movers.status_code == 200)
check("movers returns list", isinstance(movers.json(), list))

# ── History & forecast ────────────────────────────────────────────────────────
print("\n[ History & forecast ]")
hist = c.get("/risk/AR/history")
check("GET /risk/AR/history 200", hist.status_code == 200)
check("history is list", isinstance(hist.json(), list))

forecast = c.get("/risk/UA/forecast")
check("GET /risk/UA/forecast 200", forecast.status_code == 200)
check("forecast has composite_current", "composite_current" in forecast.json())

drivers = c.get("/risk/BR/drivers")
check("GET /risk/BR/drivers 200", drivers.status_code == 200)
check("drivers has driver_attributions", "driver_attributions" in drivers.json())

# ── Governance ────────────────────────────────────────────────────────────────
print("\n[ Governance ]")
gov = c.get("/governance/DE")
check("GET /governance/DE 200", gov.status_code == 200)
if gov.status_code == 200:
    check("governance score in [0,100]", 0 <= gov.json().get("score", -1) <= 100)
    check("governance has components", "components" in gov.json())

# ── NLP ───────────────────────────────────────────────────────────────────────
print("\n[ NLP ]")
aspects = c.get("/risk/BR/aspects")
check("GET /risk/BR/aspects 200 or 404", aspects.status_code in (200, 404))
stmts = c.get("/statements/BR")
check("GET /statements/BR 200", stmts.status_code == 200)

# ── Calibration ───────────────────────────────────────────────────────────────
print("\n[ Calibration ]")
cal = c.get("/calibration/summary")
check("GET /calibration/summary 200", cal.status_code == 200)
roc = c.get("/calibration/roc")
check("GET /calibration/roc 200", roc.status_code == 200)
if roc.status_code == 200:
    roc_data = roc.json()
    check("calibration/roc has auc", "auc" in roc_data)
    check("calibration/roc auc > 0.5", roc_data.get("auc", 0) > 0.5)

dataset = c.get("/calibration/dataset")
check("GET /calibration/dataset 200", dataset.status_code == 200)
if dataset.status_code == 200:
    check("calibration dataset has events", len(dataset.json().get("events", [])) > 50)

# ── Dashboard ─────────────────────────────────────────────────────────────────
print("\n[ Dashboard ]")
dash = c.get("/dashboard")
check("GET /dashboard 200", dash.status_code == 200)
check("dashboard returns HTML", "text/html" in dash.headers.get("content-type", ""))
landing = c.get("/")
check("GET / 200", landing.status_code == 200)
docs = c.get("/docs")
check("GET /docs 200", docs.status_code == 200)

# ── Indicators / events ───────────────────────────────────────────────────────
print("\n[ Indicators & events ]")
ind = c.get("/indicators/BR")
check("GET /indicators/BR 200", ind.status_code == 200)
evts = c.get("/events/UA")
check("GET /events/UA 200", evts.status_code == 200)

# ── Custom weights ────────────────────────────────────────────────────────────
print("\n[ Custom weights ]")
custom = c.get("/risk/AR?political_weight=0.6&economic_weight=0.3&nlp_weight=0.1&governance_weight=0.0")
check("GET /risk/AR custom weights 200", custom.status_code == 200)

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
if failures:
    print(f"FAILED {len(failures)}/{len(failures)+sum(1 for _ in [])} checks:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    total = 65  # approximate
    print(f"All checks passed. VisibleHand V3 smoke test OK.")
    sys.exit(0)
