# Methodology Overview

VisibleHand computes a **composite country risk score** (0–100, higher = more risk) by blending four independently scored sub-dimensions:

## Composite formula

$$\text{Composite} = \frac{\sum_i w_i \cdot s_i}{\sum_i w_i}$$

where the sum runs over available components (weights renormalise if a component has no data).

| Component | Default weight | Description |
|-----------|---------------|-------------|
| `economic` | 45% | Macroeconomic stress via 10 indicators |
| `political` | 25% | Event-driven instability via Hawkes process |
| `nlp` | 20% | Central-bank language hawkishness/stress |
| `governance` | 10% | Institutional quality and rule of law |

## Confidence intervals

Each score ships a **Bayesian 95% CI** via Monte Carlo (500 samples).  
Each sub-score is perturbed by `Gaussian(0, (1-confidence)×15)` per sample.
The composite is recomputed for each sample; CI = [2.5th, 97.5th percentile].

## Driver attribution

For a linear composite, attribution is exact:

$$\text{contribution}_i = \frac{w_i}{\sum_j w_j} \times s_i$$

Economic indicators are further drilled down proportionally within the economic sub-score.

## Forecast

Theil-Sen slope extrapolation on the last 24 stored composite scores.  
CI widens linearly with horizon. **This is extrapolation, not prediction.**

## Calibration

Weights were author-assigned for v0.3 and validated via heuristic backtest against  
~220 historical crisis events (2000–2023). Full ROC-AUC reporting at `/calibration/roc`.  
Phase 7 will run full re-scoring against live DB for final weights.

---

See the sub-pages for each scorer's detailed methodology.
