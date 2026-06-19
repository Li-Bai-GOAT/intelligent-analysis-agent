"""
K-means聚类分析实现

用于对主播/账号进行分群，识别典型问题类型。
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score


def find_optimal_k(
    df: pd.DataFrame,
    features: List[str],
    max_k: int = 10,
    min_k: int = 2
) -> Tuple[int, Dict]:
    """
    使用肘部法则和轮廓系数找最优K值
    
    Args:
        df: 数据DataFrame
        features: 聚类特征列名
        max_k: 最大聚类数
        min_k: 最小聚类数
        
    Returns:
        (optimal_k, metrics_dict)
    """
    # 准备数据
    X = df[features].dropna()
    if len(X) < min_k:
        return min_k, {'error': '数据量太少'}
    
    # 标准化
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # 计算不同K值的指标
    inertias = []
    silhouettes = []
    k_range = range(min_k, min(max_k + 1, len(X)))
    
    for k in k_range:
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        kmeans.fit(X_scaled)
        inertias.append(kmeans.inertia_)
        
        if k > 1:
            sil = silhouette_score(X_scaled, kmeans.labels_)
            silhouettes.append(sil)
        else:
            silhouettes.append(0)
    
    # 肘部法则：找拐点
    # 计算斜率变化
    if len(inertias) >= 3:
        slopes = np.diff(inertias)
        slope_changes = np.diff(slopes)
        elbow_idx = np.argmax(slope_changes) + 1
        elbow_k = list(k_range)[elbow_idx]
    else:
        elbow_k = min_k
    
    # 轮廓系数法：找最大值
    if silhouettes:
        best_sil_idx = np.argmax(silhouettes)
        sil_k = list(k_range)[best_sil_idx]
    else:
        sil_k = min_k
    
    # 综合考虑：优先轮廓系数，但不超过肘部法则太多
    optimal_k = sil_k if sil_k <= elbow_k + 1 else elbow_k
    
    metrics = {
        'k_range': list(k_range),
        'inertias': inertias,
        'silhouettes': silhouettes,
        'elbow_k': elbow_k,
        'silhouette_k': sil_k,
        'optimal_k': optimal_k,
        'best_silhouette': max(silhouettes) if silhouettes else 0
    }
    
    return optimal_k, metrics


def cluster_accounts(
    df: pd.DataFrame,
    features: List[str],
    n_clusters: Union[int, str] = 'auto',
    id_col: Optional[str] = None
) -> Tuple[pd.DataFrame, Dict]:
    """
    对账号进行聚类分析
    
    Args:
        df: 数据DataFrame
        features: 聚类特征列名
        n_clusters: 聚类数，'auto'则自动确定
        id_col: ID列名（如"主播编码"）
        
    Returns:
        (result_df, cluster_stats)
    """
    # 检查特征列
    valid_features = [f for f in features if f in df.columns]
    if len(valid_features) < 2:
        raise ValueError(f"需要至少2个有效特征列，当前: {valid_features}")
    
    # 准备数据
    df_clean = df.dropna(subset=valid_features).copy()
    X = df_clean[valid_features]
    
    # 标准化
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # 确定聚类数
    if n_clusters == 'auto':
        n_clusters, _ = find_optimal_k(df_clean, valid_features)
    
    n_clusters = min(n_clusters, len(X) - 1)
    n_clusters = max(n_clusters, 2)
    
    # K-means聚类
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df_clean['cluster'] = kmeans.fit_predict(X_scaled)
    
    # 计算轮廓系数
    sil_score = silhouette_score(X_scaled, df_clean['cluster'])
    
    # 计算各聚类的统计特征
    cluster_stats = {}
    for cluster_id in range(n_clusters):
        cluster_data = df_clean[df_clean['cluster'] == cluster_id]
        stats = {
            'count': len(cluster_data),
            'percentage': len(cluster_data) / len(df_clean),
        }
        
        # 各特征的均值和标准差
        for feat in valid_features:
            stats[f'{feat}_mean'] = cluster_data[feat].mean()
            stats[f'{feat}_std'] = cluster_data[feat].std()
        
        # 与整体均值的比较
        comparisons = []
        for feat in valid_features:
            overall_mean = df_clean[feat].mean()
            cluster_mean = stats[f'{feat}_mean']
            diff = cluster_mean - overall_mean
            overall_std = df_clean[feat].std()
            
            if overall_std > 0:
                z = diff / overall_std
                if z > 0.5:
                    comparisons.append(f"{feat}偏高")
                elif z < -0.5:
                    comparisons.append(f"{feat}偏低")
        
        stats['characteristics'] = comparisons
        stats['description'] = '、'.join(comparisons) if comparisons else '各指标正常'
        
        cluster_stats[cluster_id] = stats
    
    # 添加元数据
    cluster_stats['_meta'] = {
        'n_clusters': n_clusters,
        'silhouette_score': sil_score,
        'features': valid_features,
        'total_samples': len(df_clean)
    }
    
    return df_clean, cluster_stats


def label_clusters(
    df: pd.DataFrame,
    cluster_stats: Dict,
    cluster_col: str = 'cluster'
) -> pd.DataFrame:
    """
    为聚类生成业务标签
    
    Args:
        df: 包含聚类结果的DataFrame
        cluster_stats: 聚类统计信息
        cluster_col: 聚类列名
        
    Returns:
        DataFrame: 附加cluster_label列
    """
    result_df = df.copy()
    
    # 定义标签规则
    label_rules = {
        '折扣失控型': ['折扣差异偏高', '客单价变化率偏低'],
        '高退货型': ['退货率偏高'],
        '转化率低型': ['转化率偏低'],
        '价格让利型': ['客单价变化率偏低'],
        '健康型': [],
        '标杆型': ['转化率偏高', '退货率偏低'],
    }
    
    # 为每个聚类生成标签
    cluster_labels = {}
    for cluster_id, stats in cluster_stats.items():
        if cluster_id == '_meta':
            continue
            
        chars = stats.get('characteristics', [])
        
        # 匹配标签规则
        best_label = '健康型'
        best_match_count = 0
        
        for label, required_chars in label_rules.items():
            if not required_chars:
                continue
            match_count = sum(1 for rc in required_chars if any(rc in c for c in chars))
            if match_count > best_match_count:
                best_match_count = match_count
                best_label = label
        
        # 检查是否为标杆型
        if '转化率偏高' in str(chars) and '退货率偏低' in str(chars):
            best_label = '标杆型'
        
        cluster_labels[cluster_id] = best_label
    
    # 应用标签
    result_df['cluster_label'] = result_df[cluster_col].map(cluster_labels)
    
    return result_df


def analyze_clusters(
    df: pd.DataFrame,
    features: List[str],
    cluster_col: str = 'cluster'
) -> pd.DataFrame:
    """
    分析各聚类的特征
    
    Args:
        df: 包含聚类结果的DataFrame
        features: 特征列名
        cluster_col: 聚类列名
        
    Returns:
        DataFrame: 各聚类的特征统计
    """
    valid_features = [f for f in features if f in df.columns]
    
    # 聚合统计
    agg_dict = {f: ['mean', 'std', 'min', 'max'] for f in valid_features}
    agg_dict[cluster_col] = 'count'
    
    summary = df.groupby(cluster_col).agg(agg_dict)
    summary.columns = ['_'.join(col).strip() for col in summary.columns.values]
    summary = summary.rename(columns={f'{cluster_col}_count': 'count'})
    
    # 计算占比
    summary['percentage'] = summary['count'] / summary['count'].sum()
    
    return summary.reset_index()


def get_cluster_report(
    df: pd.DataFrame,
    features: List[str],
    cluster_col: str = 'cluster',
    label_col: str = 'cluster_label'
) -> str:
    """
    生成聚类分析报告
    
    Args:
        df: 包含聚类结果的DataFrame
        features: 特征列名
        cluster_col: 聚类列名
        label_col: 标签列名
        
    Returns:
        str: 格式化的报告
    """
    report = []
    report.append("=" * 60)
    report.append("📊 聚类分析报告")
    report.append("=" * 60)
    
    n_clusters = df[cluster_col].nunique()
    report.append(f"\n聚类数量: {n_clusters}")
    report.append(f"样本总数: {len(df)}")
    
    for cluster_id in sorted(df[cluster_col].unique()):
        cluster_data = df[df[cluster_col] == cluster_id]
        label = cluster_data[label_col].iloc[0] if label_col in df.columns else f'聚类{cluster_id}'
        
        report.append(f"\n{'='*40}")
        report.append(f"📌 {label} (聚类 {cluster_id})")
        report.append(f"   样本数: {len(cluster_data)} ({len(cluster_data)/len(df):.1%})")
        
        for feat in features:
            if feat in df.columns:
                mean_val = cluster_data[feat].mean()
                overall_mean = df[feat].mean()
                diff = mean_val - overall_mean
                report.append(f"   {feat}: {mean_val:.3f} (vs 均值: {diff:+.3f})")
    
    report.append("\n" + "=" * 60)
    
    return "\n".join(report)


if __name__ == "__main__":
    # 测试示例
    np.random.seed(42)
    
    # 生成测试数据（模拟3种类型的主播）
    n = 150
    
    # 类型1: 折扣失控型
    type1 = pd.DataFrame({
        '主播编码': [f'ZB{i:03d}' for i in range(50)],
        '客单价变化率': np.random.normal(-0.2, 0.05, 50),
        '折扣差异': np.random.normal(0.08, 0.02, 50),
        '退货率': np.random.normal(0.18, 0.05, 50),
        '转化率': np.random.normal(0.72, 0.08, 50),
    })
    
    # 类型2: 高退货型
    type2 = pd.DataFrame({
        '主播编码': [f'ZB{i:03d}' for i in range(50, 100)],
        '客单价变化率': np.random.normal(0.0, 0.08, 50),
        '折扣差异': np.random.normal(0.02, 0.02, 50),
        '退货率': np.random.normal(0.35, 0.08, 50),
        '转化率': np.random.normal(0.68, 0.10, 50),
    })
    
    # 类型3: 健康型
    type3 = pd.DataFrame({
        '主播编码': [f'ZB{i:03d}' for i in range(100, 150)],
        '客单价变化率': np.random.normal(0.05, 0.05, 50),
        '折扣差异': np.random.normal(0.01, 0.01, 50),
        '退货率': np.random.normal(0.12, 0.04, 50),
        '转化率': np.random.normal(0.82, 0.06, 50),
    })
    
    df = pd.concat([type1, type2, type3], ignore_index=True)
    
    # 聚类分析
    features = ['客单价变化率', '折扣差异', '退货率', '转化率']
    result_df, cluster_stats = cluster_accounts(df, features, n_clusters='auto')
    
    # 生成标签
    labeled_df = label_clusters(result_df, cluster_stats)
    
    # 输出报告
    print(get_cluster_report(labeled_df, features))
    
    # 查看各类型分布
    print("\n各类型分布:")
    print(labeled_df['cluster_label'].value_counts())
