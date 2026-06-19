---
name: clustering-analysis
description: K-means聚类分析，用于对主播/账号进行分群，识别典型问题类型（折扣失控型、高退货型、转化率低型等）。
metadata:
  version: 1.0.0
  dependencies: python>=3.8, pandas>=2.0.0, numpy>=1.20.0, scikit-learn>=1.0.0
---

# 聚类分析算法（Clustering Analysis）

这个Skill实现了K-means聚类分析，用于对主播/账号进行分群，识别典型问题类型。

## 使用场景

当需要进行以下分析时使用此Skill：
- 将主播/账号按表现特征分群
- 识别典型问题类型（折扣失控型、高退货型、转化率低型）
- 发现数据中的自然分组模式
- 为不同群体制定差异化策略

## 核心算法

### K-means聚类
1. 数据标准化（StandardScaler）
2. 自动确定最优K值（肘部法则 + 轮廓系数）
3. K-means聚类
4. 聚类特征分析和标签生成

### 典型问题类型识别

基于以下维度进行聚类：
- **客单价变化率**：识别价格让利问题
- **退货率**：识别高退货问题
- **转化率**：识别话术/排品问题
- **折扣差异**：识别折扣管控问题

## 提供的函数

### `cluster_accounts(df, features, n_clusters)`
对账号进行聚类分析。

### `find_optimal_k(df, features, max_k)`
使用肘部法则和轮廓系数找最优K值。

### `analyze_clusters(df, features, cluster_col)`
分析各聚类的特征。

### `label_clusters(df, cluster_stats)`
为聚类生成业务标签。

## 使用示例

```python
from clustering_analysis import cluster_accounts, analyze_clusters, label_clusters

# 定义聚类特征
features = ['客单价变化率', '退货率', '转化率', '折扣差异']

# 聚类分析
result_df, cluster_stats = cluster_accounts(
    df=sales_df,
    features=features,
    n_clusters='auto'  # 自动确定最优K值
)

# 查看聚类结果
print(f"聚类数量: {result_df['cluster'].nunique()}")
for cluster_id, stats in cluster_stats.items():
    print(f"聚类 {cluster_id}: {stats['count']} 个账号")
    print(f"  特征: {stats['description']}")

# 生成业务标签
labeled_df = label_clusters(result_df, cluster_stats)
print(labeled_df[['主播编码', 'cluster', 'cluster_label']])
```

## 聚类标签规则

| 聚类特征 | 标签 | 说明 |
|---------|------|------|
| 客单价变化率低 + 折扣高 | 折扣失控型 | 价格让利过多 |
| 退货率高 | 高退货型 | 冲动消费/尺码问题 |
| 转化率低 | 转化率低型 | 话术弱/排品乱 |
| 各指标均正常 | 健康型 | 表现良好 |
| 各指标均优秀 | 标杆型 | 值得学习推广 |

## 输出说明

- `cluster`: 聚类编号（0, 1, 2, ...）
- `cluster_label`: 业务标签（折扣失控型、高退货型等）
- `cluster_stats`: 各聚类的统计特征
- `silhouette_score`: 轮廓系数（越接近1越好）

## 文件结构

- `SKILL.md` - 技能说明文档
- `clustering_analysis.py` - 核心算法实现
- `requirements.txt` - Python依赖
