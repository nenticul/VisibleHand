# Conformal uncertainty & abstention

`core/worldstate/uncertainty.py` provides distribution-free prediction intervals
and an abstention rule.

## Split conformal

```python
cal = ConformalCalibrator().fit(y_true, y_pred)
lo, hi = cal.interval(score, alpha=0.1)     # 90% interval, clipped to [0,100]
cal.coverage_report(alpha=0.1)
```

The half-width is the finite-sample conformal quantile of absolute residuals on a
held-out calibration set. v0.1 calibrates on **predictive-stability residuals**
(year-over-year score movement); empirical coverage ≈ 0.905 at the 0.90 target.

> Time series violate exchangeability, so the coverage report is always published
> alongside the interval, and rolling-window calibration is the upgrade path.

## Abstention

`abstain = true` when any of:

- `data_quality_score < 0.5`
- `missing_feature_count > 4`
- conformal interval width > 40 points
- hazard model `calibration_status == "invalid"`

The API returns `abstain` and human-readable `abstain_reasons`; the dashboard
marks low-confidence outputs.

```json
{
  "score": 70.7,
  "conformal_90": [60.5, 80.9],
  "coverage_target": 0.9,
  "empirical_coverage": 0.905,
  "abstain": false,
  "abstain_reasons": []
}
```
