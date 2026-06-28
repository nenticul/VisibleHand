# VisibleHand Scoring Methodology (v2)

## Overview

VisibleHand produces a composite country risk score (0–100, higher = higher
risk) by combining three sub-models — economic (50%), political (30%), and NLP
sentiment (20%) — whose weights are configurable per API request. Every score
ships with:

- a **confidence** figure (0–1) reflecting data coverage and freshness,
- a **risk band** (Very Low → Critical),
- a list of **top drivers**, and
- a plain-language **methodology** string.

**Core design principle:** a country is scored against *its own historical
trajectory*, not a global mean. A developing economy is not penalised for being
developing; what matters is whether conditions are deteriorating relative to its
own baseline.

**What changed in v2 (the accuracy upgrade):**

| Area | v1 (naive) | v2 (current) |
|------|-----------|--------------|
| Normalisation | mean/std z-score | robust **median/MAD** z-score, winsorised history |
| Direction of travel | level only | level **+ momentum** (Theil–Sen slope) |
| Tail behaviour | linear | **convex** risk mapping (extremes penalised) |
| Political baseline | absolute event counts | **baseline-relative** + **escalation** detection |
| NLP | DistilBERT/SST-2 (movie reviews) | **FinBERT + central-bank hawkish/dovish lexicon** |
| Output | bare score | score **+ confidence + drivers + components** |

---

## 1. Economic Sub-Scorer (default weight 50%)

### Data sources

| Indicator | Source | Code | Frequency |
|-----------|--------|------|-----------|
| GDP growth | World Bank WDI | NY.GDP.MKTP.KD.ZG | Annual |
| Inflation (CPI) | World Bank WDI | FP.CPI.TOTL.ZG | Annual |
| Debt/GDP | IMF / World Bank | GGXWDG_NGDP / GC.DOD.TOTL.GD.ZS | Annual |
| FX reserves (months cover) | World Bank | FI.RES.TOTL.MO | Annual |
| Current account (% GDP) | World Bank | BN.CAB.XOKA.GD.ZS | Annual |

Indicator weights: GDP 25%, inflation 20%, debt/GDP 20%, FX reserves 20%,
current account 15%.

### Robust normalisation

Each indicator's latest value is normalised against its own ~10-year history
using a **median/MAD z-score** rather than mean/std:

```
z = (latest − median(history)) / (1.4826 × MAD(history))   clipped to [−3, 3]
```

The MAD (median absolute deviation) estimator is resistant to the crisis years
(COVID-2020, hyperinflation spikes) that wreck a standard deviation — and those
are exactly the years where a risk model must not break. The history used for
the baseline is **winsorised** (top/bottom 10% clamped) before estimating
spread, but the *latest* value being scored is never winsorised — otherwise the
very spike we need to detect would be clamped away.

**Zero-variance fallback.** When a country's history is perfectly flat, MAD and
std are both zero. Rather than silently returning 0, the scorer falls back to a
bounded *relative* deviation (`clip · tanh((x−median)/(½|median|))`), so a 5%
move reads as mild and an 800% move reads as extreme — magnitude ordering is
preserved.

### Level + momentum

Each indicator contributes two signals:

- **Level** (weight 0.70): where the latest value sits vs the country's baseline.
- **Momentum** (weight 0.30): the **Theil–Sen robust slope** over the last 5
  years — the median of all pairwise slopes, immune to a single anomalous year.

A country can look fine on levels yet be deteriorating fast; momentum captures
that. Drivers are annotated `…_deteriorating` when momentum is strongly adverse.

### Direction and convex tail

Indicators are oriented so positive always means higher risk (high inflation /
debt → risk; low growth / reserves / current account → risk). The blended
z-score is mapped to a [0, 100] contribution through a **convex** function:
being 3 SD into the danger zone is penalised disproportionately more than 1 SD,
matching the non-linear way macro risk actually bites.

### Confidence

Reported per score as `0.6 × (indicators_present / 5) + 0.4 × (series_depth)`.
A score built on 2 short series is explicitly flagged as less trustworthy than
one built on 5 deep ones.

### Known limitations

- World Bank data lags 12–18 months; the latest year is often the prior year.
- Annual frequency misses rapid within-year deterioration (mitigated, not
  solved, by the momentum term).
- Indicator weights are author-assigned, not estimated from default outcomes
  (see §6, Calibration).

---

## 2. Political Sub-Scorer (default weight 30%)

### Data sources

- **GDELT** event/tone feed (free, no key) — protests, conflict, leadership.
- **ACLED** (optional) — higher-precision armed-conflict event classification.

### Event taxonomy

Intensity multipliers: coup 5.0, conflict 3.0, sanction 2.5, leadership change
2.0, protest 1.5, election 0.5 (elections *reduce* medium-term uncertainty).
Each event also carries a per-event severity.

### Three blended signals

1. **Decayed pressure** (0.45). Every event's intensity is exponentially
   decayed with a **90-day half-life** (`exp(−ln2/90 · days)`), summed, and
   squashed: `pressure / (pressure + 10) × 100`. Recent unrest dominates old.

2. **Baseline ratio** (0.30). Current pressure is compared to the country's
   *own* trailing baseline (pressure as it stood 180/270/360 days ago). This is
   what makes the score baseline-relative: a heavily-reported country (the US
   generates more news events than Uruguay regardless of risk) is judged on its
   *deviation from normal*, not its absolute event volume.

3. **Escalation** (0.25). Per-day event intensity over the last 30 days vs the
   preceding 90 days. A sudden burst surfaces a `rapid_escalation` driver even
   before absolute pressure is high.

### Why a 90-day half-life

Market risk premia from a political shock typically normalise within 1–2
quarters absent further escalation. A coup attempt three years ago should not
weigh like one from last month. 90 days is a calibrated approximation, not a
fitted constant.

### Known limitations

- GDELT infers events from media tone, so coverage gaps and media bias affect
  low-coverage countries.
- State vs criminal violence are not yet distinguished.

---

## 3. NLP Sub-Scorer (default weight 20%) — the biggest accuracy fix

### The problem with v1

v1 used `distilbert-base-uncased-finetuned-sst-2-english`, a **movie-review**
sentiment model. On central-bank text it is actively misleading: *"we remain
vigilant"* and *"prepared to act decisively"* read as **positive** to a
movie-review model, yet they are unambiguously **hawkish** (tightening → higher
risk). Generic positive/negative sentiment is simply the wrong axis. The right
axis for monetary policy is **hawkish ↔ dovish**.

### The v2 hybrid

Two complementary signals are fused:

1. **FinBERT** (`ProsusAI/finbert`), a BERT model fine-tuned on financial text
   (positive / negative / neutral). Its `negative` mass maps to risk; far better
   calibrated to economic language than SST-2. Statements are split into
   sentences (FinBERT's natural unit) and averaged.

2. **A central-bank lexicon** (`core/nlp/lexicon.py`) of signed hawkish /
   dovish / stress phrases with **negation and intensifier handling**
   ("we will *not* raise rates" flips sign; "*significantly* tighten" amplifies).
   It catches policy idioms — "higher for longer", "sufficiently restrictive",
   "remain vigilant" — that even FinBERT can miss, and it is fully deterministic
   and interpretable.

Final score = `0.55 × FinBERT + 0.45 × lexicon`. Agreement between the two
raises the reported confidence; divergence lowers it. **If the transformer is
unavailable** (not installed, no weights, offline), the scorer degrades
gracefully to the lexicon alone and still returns a sensible, deterministic
score — the API never hard-fails on NLP.

### Score interpretation

| Range | Meaning |
|-------|---------|
| 0–35 | Dovish — accommodative, supportive |
| 35–65 | Neutral — balanced, data-dependent |
| 65–85 | Hawkish — inflation concern, tightening bias |
| 85–100 | Very hawkish / stressed — emergency or crisis tone |

### Known limitations

- English only (ECB/Bundesbank/Banque de France native-language statements need
  multilingual models — see extensions).
- Hawkishness from strength (proactive tightening) vs from crisis (defending a
  collapsing currency) are not yet separated; the stress lexicon partially
  bridges this.

---

## 4. Composite

```
composite = Σ (wᵢ / Σw) · scoreᵢ      over the components that have data
```

Missing components are **dropped and the remaining weights renormalised**,
rather than scored as a neutral 50 — so a country with no event data isn't
silently pushed toward the middle. Overall **confidence** is the weight-blended
component confidence, lightly penalised when components are missing. Drivers are
ordered so the **dominant** risk leads (conflict for a war economy; hawkish
language when the central bank is the main story).

Callers can re-weight per request, e.g.
`?political_weight=0.6&economic_weight=0.3&nlp_weight=0.1`.

---

## 5. What VisibleHand does **not** claim

It will not match expert-panel scores (PRS Group ICRG, Control Risks) on soft
factors — rule of law, corruption perception, regulatory quality, expropriation
risk — which need qualitative judgement. The claim is narrower and defensible: a
**transparent, reproducible, programmable** score a developer or researcher can
inspect, extend, and integrate. Transparency is itself the feature.

---

## 6. Calibration (research extension)

To validate scores against real outcomes:

1. Assemble a labelled set of stress events — sovereign defaults, >30% currency
   devaluations, coups, IMF bailouts.
2. Extract VisibleHand scores 6 / 12 / 18 months prior.
3. Compute ROC-AUC (does an elevated score predict stress better than chance?)
   and a calibration curve (when the model says 70, what is the empirical
   12-month stress probability?).

This turns the project from a methodology demonstration into publishable
research, and would let the currently author-assigned weights be *estimated*
from outcomes rather than hand-set.
