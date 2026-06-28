# Crisis hazards

Moves from one risk score to **eight crisis-type probabilities** at 6/12/18-month
horizons.

Targets: `sovereign_default`, `currency_crisis`, `imf_programme`,
`banking_crisis`, `civil_conflict`, `coup`, `sanctions_shock`,
`political_instability`.

```
GET /state/AR/hazards?horizon=12
```

## Models (v0.1)

- **`LogisticHazardModel`** — pure-numpy, L2-regularised, class-weighted logistic
  regression. Trained per `(target, horizon)` with a temporal split.
- **Heuristic fallback** — transparent feature-driven priors, always available,
  used when a target has too few positive labels to train. This guarantees every
  country gets a hazard estimate.

Gradient boosting / TabPFN / survival models are optional, **benchmark-gated**
experiments (build guide §7.3), not hard dependencies.

## Labels

Built from the curated crisis dataset (`core/calibration/crisis_dataset.py`),
mapping `crisis_type → target`. Annual resolution: horizon 6/12m → next year,
18m → next two years. `sanctions_shock` has no label coverage → heuristic only.

## Honesty

- Both logistic and heuristic baselines are logged to `model_leaderboard`.
- Every prediction carries `calibration_status` (`experimental` / `heuristic`).
- v0.1 logistic probabilities are **over-confident** (see
  [BENCHMARK](../../BENCHMARK_vh_wsm_0.1.md)); treat them as rankings until
  post-hoc calibration (Platt/isotonic) is added.

## No leakage

Training uses only feature rows dated within the train window; the live snapshot
is excluded from training (it has no realised horizon yet).
