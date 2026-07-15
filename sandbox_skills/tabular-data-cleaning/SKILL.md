---
name: tabular-data-cleaning
description: Audit and clean CSV or Excel tables while preserving identifiers and the source file. Use for missing values, duplicate records, mixed types, whitespace/case normalization, invalid dates, numeric parsing, business-key conflicts, outlier candidates, or whenever a reproducible data-quality report and cleaned table are required.
---

# Tabular Data Cleaning

Produce an auditable cleaned table without overwriting the source.

## Workflow

1. Inspect the file, sheet names, headers, row count, and candidate identifiers.
2. Confirm business keys and any domain-specific missing-value policy. Do not invent one.
3. Preserve identifiers such as order numbers as strings, including leading zeroes.
4. Run `scripts/profile_and_clean.py` for a deterministic baseline.
5. Review `data_quality_summary.json` and unresolved issues before using the cleaned data.
6. Deliver both `cleaned_data.csv` and `data_quality_report.md`; state every destructive rule applied.

## Command

```bash
python scripts/profile_and_clean.py INPUT \
  --output-dir OUTPUT_DIR \
  --business-key order_id \
  --date-columns order_date \
  --numeric-columns revenue,cost,visits,orders,score,weight \
  --categorical-columns region \
  --drop-exact-duplicates
```

For Excel input, optionally pass `--sheet SHEET_NAME`. The script reads all columns as text first. It trims strings, normalizes configured categories to lowercase, parses configured dates to ISO format, converts configured numeric fields, and reports IQR outlier candidates. Invalid or missing values remain missing; it never silently imputes them.

## Guardrails

- Write outputs to a new directory under `/workspace`; never replace the input.
- Treat IQR results as review candidates, not automatic errors.
- Report both exact duplicate rows and repeated business keys.
- Keep a row unless an explicitly selected rule removes it.
- Stop with a clear error when a requested column does not exist.
- Read [references/cleaning_rules.md](references/cleaning_rules.md) when choosing a missing-value or duplicate policy.

