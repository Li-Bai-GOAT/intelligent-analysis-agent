from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def column_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def read_table(path: Path, sheet: str | None) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype="string", keep_default_na=True)
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet or 0, dtype="string")
    raise ValueError("input must be CSV or Excel")


def require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [name for name in columns if name not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile and clean a tabular file without overwriting it.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sheet")
    parser.add_argument("--business-key", default="")
    parser.add_argument("--date-columns", default="")
    parser.add_argument("--numeric-columns", default="")
    parser.add_argument("--categorical-columns", default="")
    parser.add_argument("--drop-exact-duplicates", action="store_true")
    args = parser.parse_args()

    source = args.input.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir == source.parent and output_dir / "cleaned_data.csv" == source:
        raise ValueError("output must not overwrite input")
    output_dir.mkdir(parents=True, exist_ok=True)

    business_keys = column_list(args.business_key)
    date_columns = column_list(args.date_columns)
    numeric_columns = column_list(args.numeric_columns)
    categorical_columns = column_list(args.categorical_columns)
    df = read_table(source, args.sheet)
    require_columns(df, business_keys + date_columns + numeric_columns + categorical_columns)
    original_rows = len(df)

    for column in df.columns:
        if pd.api.types.is_string_dtype(df[column].dtype):
            df[column] = df[column].str.strip().replace("", pd.NA)
    for column in categorical_columns:
        df[column] = df[column].str.lower()

    invalid_dates: dict[str, int] = {}
    for column in date_columns:
        present = df[column].notna()
        parsed = pd.to_datetime(df[column], errors="coerce", format="mixed")
        invalid_dates[column] = int((present & parsed.isna()).sum())
        df[column] = parsed.dt.strftime("%Y-%m-%d").astype("string")

    invalid_numeric: dict[str, int] = {}
    for column in numeric_columns:
        present = df[column].notna()
        parsed = pd.to_numeric(df[column], errors="coerce")
        invalid_numeric[column] = int((present & parsed.isna()).sum())
        df[column] = parsed

    exact_mask = df.duplicated(keep="first")
    exact_duplicate_rows = int(exact_mask.sum())
    business_duplicate_rows = int(df.duplicated(subset=business_keys, keep=False).sum()) if business_keys else 0

    outliers: dict[str, dict[str, float | int | None]] = {}
    for column in numeric_columns:
        values = df[column].dropna()
        if len(values) < 4:
            outliers[column] = {"count": 0, "lower": None, "upper": None}
            continue
        q1, q3 = float(values.quantile(0.25)), float(values.quantile(0.75))
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers[column] = {
            "count": int(((values < lower) | (values > upper)).sum()),
            "lower": lower,
            "upper": upper,
        }

    if args.drop_exact_duplicates:
        df = df.loc[~exact_mask].copy()

    missing_values = {column: int(count) for column, count in df.isna().sum().items() if count}
    summary = {
        "source": source.name,
        "original_rows": original_rows,
        "cleaned_rows": len(df),
        "removed_exact_duplicates": exact_duplicate_rows if args.drop_exact_duplicates else 0,
        "exact_duplicate_rows_found": exact_duplicate_rows,
        "business_duplicate_rows_found": business_duplicate_rows,
        "invalid_dates": invalid_dates,
        "invalid_numeric": invalid_numeric,
        "missing_values_after_cleaning": missing_values,
        "outlier_candidates": outliers,
        "source_overwritten": False,
    }

    df.to_csv(output_dir / "cleaned_data.csv", index=False, encoding="utf-8-sig")
    (output_dir / "data_quality_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Data quality report",
        "",
        f"- Source: `{source.name}`",
        f"- Rows before/after: {original_rows} / {len(df)}",
        f"- Exact duplicates found/removed: {exact_duplicate_rows} / {summary['removed_exact_duplicates']}",
        f"- Business-key duplicate rows: {business_duplicate_rows}",
        f"- Invalid dates: {sum(invalid_dates.values())}",
        f"- Invalid numeric values: {sum(invalid_numeric.values())}",
        "",
        "## Unresolved missing values",
        "",
    ]
    lines.extend([f"- {name}: {count}" for name, count in missing_values.items()] or ["- None"])
    lines.extend(["", "## IQR outlier candidates", ""])
    lines.extend([f"- {name}: {data['count']}" for name, data in outliers.items()] or ["- None"])
    (output_dir / "data_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

