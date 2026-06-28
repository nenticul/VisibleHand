# Benchmark — VH-WSM v0.1

Honest benchmark of the v0.1 hazard baselines. **If the heuristic beats the
learned model, we publish that** (build guide §18.7). Numbers below are from the
44-country seed panel with a temporal split (train ≤2018, test 2019–2023) and
are reproducible via the scripts in the model card. Live the leaderboard at
`GET /model/leaderboard`.

## Setup

- **Features:** `vh-wsm-features-0.1` (11-dim z-score + governance + score panel)
- **Split:** train years ≤ 2018, test years 2019–2023 (220 country-years)
- **Models:** `vh-wsm-hazard-logistic` (numpy, class-weighted, L2) vs
  `vh-wsm-hazard-heuristic` (transparent feature priors, no training)
- **Metrics:** ROC-AUC, PR-AUC, Brier, log-loss, expected calibration error

## Hazard results (test set, AUC / Brier)

| Target | Horizon | Logistic AUC | Heuristic AUC | Best (Brier) |
|--------|:------:|:-----------:|:-------------:|:------------:|
| sovereign_default | 18m | **0.816** | 0.698 | heuristic (0.071) |
| currency_crisis | 6m | **0.751** | 0.734 | heuristic (0.132) |
| currency_crisis | 12m | **0.751** | 0.734 | heuristic (0.132) |
| currency_crisis | 18m | **0.724** | 0.690 | heuristic (0.137) |
| imf_programme | 6m | 0.800 | **0.945** | heuristic (0.069) |
| imf_programme | 12m | 0.800 | **0.945** | heuristic (0.069) |
| imf_programme | 18m | 0.785 | **0.885** | heuristic (0.073) |
| political_instability | 18m | **0.903** | 0.590 | heuristic (0.028) |
| civil_conflict | 6/12/18m | (insufficient labels) | **0.90–0.92** | heuristic |
| banking_crisis | all | (insufficient labels) | heuristic only | heuristic |
| coup | all | (insufficient labels) | heuristic only | heuristic |
| sanctions_shock | all | no labels | heuristic only | heuristic |

## Honest reading of these numbers

- **Discrimination (AUC):** the logistic baseline is competitive or better on
  default / currency / political-instability; the **heuristic wins** on IMF
  programme and the sparse-label targets. Several targets have too few positive
  labels in the train split to fit a model, so they correctly fall back to the
  heuristic.
- **Calibration (Brier):** the class-weighted logistic is **over-confident**
  (Brier ~0.25) because balancing on a handful of positives inflates predicted
  probabilities. The heuristic has much lower Brier. **Until calibration is
  fixed (e.g. Platt/isotonic on a held-out fold), treat learned probabilities as
  rankings, not literal frequencies** — hence `calibration_status` is surfaced
  on every prediction.
- **Conclusion for v0.1:** ship the ensemble (logistic where trainable, else
  heuristic) but label everything experimental. The leaderboard is the source of
  truth and is regenerated on every training run.

## Uncertainty (conformal)

- Calibrator fitted on predictive-stability residuals (year-over-year score
  movement), n=484.
- 90% half-width ≈ **10.2 points**; empirical coverage **0.905** vs 0.90 target.

## Next benchmarks (Milestone 6, gated)

TimesFM macro-trajectory features, TabPFN small-data tabular hazards,
Transformer/Mamba-Hawkes event encoders, and a temporal GNN for spillover —
each must beat these baselines on this leaderboard before shipping.
