---
name: contribution-analysis
description: 基于树模型的特征贡献度分析（TreeSHAP），用于识别影响业绩/利润的关键因素，快速轻量无需GPU。
metadata:
  version: 1.0.0
  dependencies: python>=3.8, pandas>=2.0.0, numpy>=1.20.0, scikit-learn>=1.0.0, shap>=0.42.0
---

# 贡献度分析（Contribution Analysis）

这个Skill实现了基于树模型的特征贡献度分析，使用TreeSHAP算法快速计算各因素对目标变量的贡献。

## 使用场景

当需要回答以下问题时使用此Skill：
- 哪些因素对利润影响最大？
- 各特征对业绩变化的贡献度如何？
- 为什么某个账号的表现异常？（个体解释）
- 如何排序影响因素的重要性？

## 核心算法

### TreeSHAP（树模型SHAP值）

使用轻量级的树模型（RandomForest / GradientBoosting）+ TreeSHAP：
- **速度快**：O(TLD²) 复杂度，比KernelSHAP快几个数量级
- **精确计算**：不是采样近似，是精确的Shapley值
- **无需GPU**：纯CPU计算，适合沙箱环境

### 工作流程

1. 训练轻量级树模型（RandomForest）
2. 使用TreeSHAP计算SHAP值
3. 分析全局特征重要性
4. 支持单样本解释（为什么这个账号表现差？）

## 提供的函数

### `analyze_feature_importance(df, target, features)`
分析特征对目标变量的贡献度。

### `explain_single_sample(df, target, features, sample_idx)`
解释单个样本的预测结果。

### `get_top_factors(shap_values, feature_names, top_k)`
获取贡献度最高的K个因素。

### `contribution_report(df, target, features)`
生成完整的贡献度分析报告。

## 使用示例

```python
from contribution_analysis import analyze_feature_importance, explain_single_sample

# 分析影响利润的关键因素
result = analyze_feature_importance(
    df=sales_df,
    target='考核利润',
    features=['业绩额', '折扣', '退货率', '转化率', '人力费用率']
)

# 查看特征重要性排名
print("特征重要性排名:")
for feat, importance in result['feature_importance'].items():
    print(f"  {feat}: {importance:.3f}")

# 解释某个表现差的账号
sample_explanation = explain_single_sample(
    df=sales_df,
    target='考核利润',
    features=features,
    sample_idx=5  # 第5行数据
)
print(f"该账号利润偏低的主要原因: {sample_explanation['top_negative_factors']}")
```

## 输出说明

- `feature_importance`: 各特征的全局重要性（平均|SHAP值|）
- `shap_values`: 每个样本每个特征的SHAP值
- `base_value`: 基准值（平均预测值）
- `top_positive_factors`: 正向贡献最大的因素
- `top_negative_factors`: 负向拖累最大的因素

## 与连环替代法的区别

| 方法 | 适用场景 | 优点 | 缺点 |
|-----|---------|------|------|
| 连环替代法 | 乘法/加法分解公式 | 符合业务逻辑 | 需要预设公式 |
| SHAP归因 | 任意多因素 | 自动发现关系 | 黑盒解释 |

**建议**：先用连环替代法做结构化分解，再用SHAP验证或发现隐藏因素。

## 性能说明

- 100条数据：< 1秒
- 1000条数据：< 5秒
- 10000条数据：< 30秒

## 文件结构

- `SKILL.md` - 技能说明文档
- `contribution_analysis.py` - 核心算法实现
- `requirements.txt` - Python依赖
