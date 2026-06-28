# Limitations

VH-WSM v0.1 is a strong, honest foundation — not a finished forecasting system.
Read these before relying on any output.

## Data

- The modelling feature panel starts in **2013**; crises from 2000–2012 inform
  *labels* but have no matching feature vectors.
- Crisis labels are **annual** (onset year), so 6/12/18-month horizons are
  approximations, not month-precise.
- Several targets (`banking_crisis`, `civil_conflict`, `coup`) have too few
  positive labels in the 44-country panel to train a learned model and fall back
  to the heuristic. `sanctions_shock` has no labels at all.

## Models

- Hazard probabilities are **experimental**. The v0.1 logistic baseline is
  over-confident (high Brier); use as rankings, not literal frequencies, until
  post-hoc calibration is added. `calibration_status` is exposed everywhere.
- Embeddings are linear (PCA). Non-linear structure is not captured in v0.1.
- Spillover is a **deterministic** graph aggregate; no learned contagion yet.

## Scope

- Frontier models are intentionally **not shipped**: TimesFM (macro trajectory),
  TabPFN (small-data hazards), Transformer/Mamba-Hawkes (events), temporal GNN
  (spillover). They are benchmark-gated experiments (build guide §6–§10) and must
  beat these baselines on `/model/leaderboard` first.

## Honest defaults

- Every output is versioned (model / feature / embedding / data cutoff).
- Uncertainty is always shown; low-confidence states abstain.
- Benchmarks are published even when the simple model wins.
