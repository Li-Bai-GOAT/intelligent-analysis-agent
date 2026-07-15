# Formula contracts

These are generic example contracts. Confirm the organization's official definitions before financial use.

| Metric | Formula | Edge handling |
| --- | --- | --- |
| Gross profit | `sum(revenue) - sum(cost)` | Report missing/invalid inputs |
| Gross margin | `gross_profit / sum(revenue)` | Undefined when revenue is zero |
| Conversion rate | `sum(orders) / sum(visits)` | Undefined when visits are zero |
| Weighted average | `sum(value * weight) / sum(weight)` | Exclude pairs with a missing member; undefined when weights sum to zero |
| Growth rate | `(current - base) / base` | Undefined when base is zero |
| Structure share | `part / total` | Undefined when total is zero |
| Customer average | `amount / distinct_customers` | Undefined when customer count is zero |

Do not average row-level percentages unless the contract explicitly calls for equal row weighting.

Sources: NumPy weighted-average reference, https://numpy.org/doc/stable/reference/generated/numpy.average.html .

