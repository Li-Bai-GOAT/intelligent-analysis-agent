---
name: correlation-analysis
description: Pearson/Spearman相关性分析，快速定位与目标指标强相关的因素
allowed-tools:
  read: true
  write: true
  bash: true
---

# 相关性分析 (Correlation Analysis)

快速识别与目标变量（利润、退货率等）相关性最强的因素。

## 核心功能

1. **Pearson相关**：线性相关分析
2. **Spearman相关**：秩相关（适合非线性）
3. **相关矩阵**：多变量相关性矩阵
4. **偏相关**：控制其他变量后的相关性

## 使用方法

```python
from correlation_analysis import (
    pearson_correlation,
    spearman_correlation,
    correlation_matrix,
    find_top_correlations,
    correlation_with_target,
    get_correlation_report,
)

# 计算两变量相关性
corr, pval = pearson_correlation(df, '退货率', '考核利润')

# 找与利润最相关的因素
top_factors = find_top_correlations(df, '考核利润', features, top_k=5)

# 生成报告
report = get_correlation_report(df, '考核利润', features)
```

## 相关性强度解读

| |r| 范围 | 强度 |
|----------|------|
| 0.8-1.0 | 极强 |
| 0.6-0.8 | 强 |
| 0.4-0.6 | 中等 |
| 0.2-0.4 | 弱 |
| 0-0.2 | 极弱 |

## 适用场景

- 利润分析：找影响利润的关键因素
- 退货分析：分析退货率与其他指标的关系
- 转化分析：定位影响转化率的因素
