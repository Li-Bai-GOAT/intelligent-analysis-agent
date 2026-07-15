from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def read_table(path: Path, sheet: str | None) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype="string")
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet or 0, dtype="string")
    raise ValueError("input must be CSV or Excel")


def safe_ratio(numerator: float, denominator: float) -> dict[str, float | str | None]:
    if denominator == 0:
        return {"value": None, "status": "undefined_zero_denominator"}
    return {"value": numerator / denominator, "status": "ok"}


def compute(df: pd.DataFrame, args: argparse.Namespace) -> dict:
    fields = [args.revenue, args.cost, args.visits, args.orders, args.value, args.weight]
    missing = [field for field in fields if field not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")

    invalid: dict[str, int] = {}
    for field in fields:
        original = df[field]
        parsed = pd.to_numeric(original, errors="coerce")
        invalid[field] = int((original.notna() & parsed.isna()).sum())
        df[field] = parsed

    revenue = float(df[args.revenue].sum(skipna=True))
    cost = float(df[args.cost].sum(skipna=True))
    visits = float(df[args.visits].sum(skipna=True))
    orders = float(df[args.orders].sum(skipna=True))
    gross_profit = revenue - cost
    pairs = df[[args.value, args.weight]].dropna()
    weight_sum = float(pairs[args.weight].sum())
    weighted_numerator = float((pairs[args.value] * pairs[args.weight]).sum())
    return {
        "rows": len(df),
        "inputs": {"revenue": revenue, "cost": cost, "visits": visits, "orders": orders},
        "gross_profit": {"formula": "sum(revenue) - sum(cost)", "value": gross_profit, "status": "ok"},
        "gross_margin": {"formula": "gross_profit / sum(revenue)", **safe_ratio(gross_profit, revenue)},
        "conversion_rate": {"formula": "sum(orders) / sum(visits)", **safe_ratio(orders, visits)},
        "weighted_average": {
            "formula": "sum(value * weight) / sum(weight)",
            "numerator": weighted_numerator,
            "denominator": weight_sum,
            **safe_ratio(weighted_numerator, weight_sum),
        },
        "invalid_numeric": invalid,
        "missing_numeric": {field: int(df[field].isna().sum()) for field in fields},
        "negative_value_rows": {field: int((df[field] < 0).sum()) for field in fields},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate auditable business metrics.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sheet")
    parser.add_argument("--revenue", default="revenue")
    parser.add_argument("--cost", default="cost")
    parser.add_argument("--visits", default="visits")
    parser.add_argument("--orders", default="orders")
    parser.add_argument("--value", default="score")
    parser.add_argument("--weight", default="weight")
    parser.add_argument("--group-by")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    df = read_table(args.input.resolve(), args.sheet)
    overall = compute(df.copy(), args)
    grouped = {}
    if args.group_by:
        if args.group_by not in df.columns:
            raise ValueError(f"missing group-by column: {args.group_by}")
        for name, group in df.groupby(args.group_by, dropna=False):
            grouped[str(name)] = compute(group.copy(), args)
    results = {"source": args.input.name, "overall": overall, "groups": grouped}
    (output_dir / "metric_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Business metric report",
        "",
        f"- Source: `{args.input.name}`",
        f"- Rows: {overall['rows']}",
        f"- Revenue: {overall['inputs']['revenue']}",
        f"- Cost: {overall['inputs']['cost']}",
        f"- Gross profit: {overall['gross_profit']['value']}",
        f"- Gross margin: {overall['gross_margin']['value']} ({overall['gross_margin']['status']})",
        f"- Conversion rate: {overall['conversion_rate']['value']} ({overall['conversion_rate']['status']})",
        f"- Weighted average: {overall['weighted_average']['value']} ({overall['weighted_average']['status']})",
        "",
        "Rates use aggregate numerators and denominators. Missing numeric values are excluded from sums and reported in JSON.",
    ]
    (output_dir / "metric_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

