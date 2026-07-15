---
name: business-metric-formulas
description: Calculate and reconcile growth, gross profit, gross margin, conversion rate, structure share, customer average, and weighted averages from CSV or Excel data. Use when business ratios require explicit formulas, field mappings, aggregation-level controls, zero-denominator handling, grouped results, and auditable intermediate totals.
---

# Business Metric Formulas

Calculate business metrics from aggregate numerators and denominators, with explicit edge-case status.

## Workflow

1. State the requested metric, field mapping, unit, filters, time window, and aggregation level.
2. Read [references/formula_contracts.md](references/formula_contracts.md) for the applicable contract.
3. Run the deterministic calculator when the standard fields are present.
4. Reconcile totals against the source and report excluded or invalid rows.
5. Return the formula, intermediate totals, result, and status. Never hide a zero denominator.

## Command

```bash
python scripts/calculate_metrics.py INPUT \
  --output-dir OUTPUT_DIR \
  --revenue revenue --cost cost \
  --visits visits --orders orders \
  --value score --weight weight \
  --group-by region
```

The command creates `metric_results.json` and `metric_report.md`. CSV and Excel are supported; use `--sheet` for a non-default Excel sheet.

## Guardrails

- Compute rate totals as `sum(numerator) / sum(denominator)`, not an unweighted mean of row rates.
- Return `undefined_zero_denominator` rather than infinity or a fabricated zero.
- Preserve negative values and flag them for interpretation; do not silently clip returns or reversals.
- Report invalid numeric and missing values per input field.
- If the user requests an Excel deliverable, use the existing `xlsx` Skill to write dynamic formulas and verify formula errors.

