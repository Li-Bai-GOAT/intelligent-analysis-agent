"""
相关性分析

用于快速识别与目标指标（利润、退货率等）强相关的因素。
使用 Pearson（线性）和 Spearman（非线性/秩相关）两种方法。
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
from scipy import stats


def pearson_correlation(
    df: pd.DataFrame,
    col1: str,
    col2: str
) -> Tuple[float, float]:
    """
    计算两列的 Pearson 相关系数
    
    Args:
        df: 数据DataFrame
        col1, col2: 列名
        
    Returns:
        (correlation, p_value)
    """
    data = df[[col1, col2]].dropna()
    if len(data) < 3:
        return 0.0, 1.0
    
    corr, pval = stats.pearsonr(data[col1], data[col2])
    return corr, pval


def spearman_correlation(
    df: pd.DataFrame,
    col1: str,
    col2: str
) -> Tuple[float, float]:
    """
    计算两列的 Spearman 秩相关系数（适用于非线性关系）
    
    Args:
        df: 数据DataFrame
        col1, col2: 列名
        
    Returns:
        (correlation, p_value)
    """
    data = df[[col1, col2]].dropna()
    if len(data) < 3:
        return 0.0, 1.0
    
    corr, pval = stats.spearmanr(data[col1], data[col2])
    return corr, pval


def correlation_matrix(
    df: pd.DataFrame,
    columns: List[str],
    method: str = 'pearson'
) -> pd.DataFrame:
    """
    计算相关性矩阵
    
    Args:
        df: 数据DataFrame
        columns: 要分析的列
        method: 'pearson' 或 'spearman'
        
    Returns:
        DataFrame: 相关性矩阵
    """
    valid_cols = [c for c in columns if c in df.columns]
    
    if method == 'spearman':
        return df[valid_cols].corr(method='spearman')
    else:
        return df[valid_cols].corr(method='pearson')


def find_top_correlations(
    df: pd.DataFrame,
    target: str,
    features: List[str],
    method: str = 'pearson',
    top_k: int = 5,
    min_corr: float = 0.1
) -> List[Dict]:
    """
    找出与目标变量相关性最强的特征
    
    Args:
        df: 数据DataFrame
        target: 目标变量列名
        features: 候选特征列表
        method: 相关性计算方法
        top_k: 返回前K个
        min_corr: 最小相关系数阈值
        
    Returns:
        List of dicts: 按相关性排序的特征列表
    """
    if target not in df.columns:
        raise ValueError(f"目标变量 {target} 不存在")
    
    valid_features = [f for f in features if f in df.columns and f != target]
    
    results = []
    for feat in valid_features:
        if method == 'spearman':
            corr, pval = spearman_correlation(df, target, feat)
        else:
            corr, pval = pearson_correlation(df, target, feat)
        
        if abs(corr) >= min_corr:
            results.append({
                'feature': feat,
                'correlation': corr,
                'abs_correlation': abs(corr),
                'p_value': pval,
                'significant': pval < 0.05,
                'direction': '正相关' if corr > 0 else '负相关',
                'strength': _correlation_strength(corr)
            })
    
    # 按绝对值排序
    results.sort(key=lambda x: x['abs_correlation'], reverse=True)
    
    return results[:top_k]


def _correlation_strength(corr: float) -> str:
    """判断相关性强度"""
    abs_corr = abs(corr)
    if abs_corr >= 0.8:
        return '极强'
    elif abs_corr >= 0.6:
        return '强'
    elif abs_corr >= 0.4:
        return '中等'
    elif abs_corr >= 0.2:
        return '弱'
    else:
        return '极弱'


def correlation_with_target(
    df: pd.DataFrame,
    target: str,
    features: Optional[List[str]] = None,
    method: str = 'pearson'
) -> pd.DataFrame:
    """
    计算所有特征与目标变量的相关性
    
    Args:
        df: 数据DataFrame
        target: 目标变量
        features: 特征列表，None则使用所有数值列
        method: 相关性方法
        
    Returns:
        DataFrame: 相关性结果表
    """
    if features is None:
        features = df.select_dtypes(include=[np.number]).columns.tolist()
        features = [f for f in features if f != target]
    
    results = []
    for feat in features:
        if feat not in df.columns:
            continue
            
        if method == 'spearman':
            corr, pval = spearman_correlation(df, target, feat)
        else:
            corr, pval = pearson_correlation(df, target, feat)
        
        results.append({
            '特征': feat,
            '相关系数': corr,
            '|相关系数|': abs(corr),
            'P值': pval,
            '显著': '是' if pval < 0.05 else '否',
            '方向': '正' if corr > 0 else '负',
            '强度': _correlation_strength(corr)
        })
    
    result_df = pd.DataFrame(results)
    result_df = result_df.sort_values('|相关系数|', ascending=False)
    
    return result_df


def partial_correlation(
    df: pd.DataFrame,
    x: str,
    y: str,
    control: List[str]
) -> Tuple[float, float]:
    """
    计算偏相关系数（控制其他变量后的相关性）
    
    Args:
        df: 数据DataFrame
        x, y: 要计算相关性的两个变量
        control: 控制变量列表
        
    Returns:
        (partial_corr, p_value)
    """
    from scipy.linalg import lstsq
    
    valid_cols = [x, y] + control
    data = df[valid_cols].dropna()
    
    if len(data) < len(control) + 3:
        return 0.0, 1.0
    
    # 回归残差法计算偏相关
    def residuals(target, controls):
        X = data[controls].values
        X = np.column_stack([np.ones(len(X)), X])
        y_vec = data[target].values
        beta, _, _, _ = lstsq(X, y_vec)
        return y_vec - X @ beta
    
    res_x = residuals(x, control)
    res_y = residuals(y, control)
    
    corr, pval = stats.pearsonr(res_x, res_y)
    return corr, pval


def get_correlation_report(
    df: pd.DataFrame,
    target: str,
    features: List[str],
    method: str = 'pearson'
) -> str:
    """
    生成相关性分析报告
    
    Args:
        df: 数据DataFrame
        target: 目标变量
        features: 特征列表
        method: 相关性方法
        
    Returns:
        str: 格式化报告
    """
    report = []
    report.append("=" * 60)
    report.append(f"📊 相关性分析报告 ({method.upper()})")
    report.append("=" * 60)
    report.append(f"\n目标变量: {target}")
    report.append(f"分析特征数: {len(features)}")
    
    # 计算相关性
    corr_df = correlation_with_target(df, target, features, method)
    
    report.append(f"\n{'='*40}")
    report.append("📈 与目标变量的相关性排名")
    report.append("=" * 40)
    
    for _, row in corr_df.head(10).iterrows():
        feat = row['特征']
        corr = row['相关系数']
        strength = row['强度']
        direction = row['方向']
        sig = '***' if row['显著'] == '是' else ''
        
        bar_len = int(abs(corr) * 20)
        bar = ('▓' if corr > 0 else '░') * bar_len + '·' * (20 - bar_len)
        
        report.append(f"  {feat:20s} {bar} {corr:+.3f} {sig} ({strength}{direction})")
    
    # 主要发现
    report.append(f"\n{'='*40}")
    report.append("🔍 主要发现")
    report.append("=" * 40)
    
    strong_positive = corr_df[(corr_df['相关系数'] > 0.4) & (corr_df['显著'] == '是')]
    strong_negative = corr_df[(corr_df['相关系数'] < -0.4) & (corr_df['显著'] == '是')]
    
    if len(strong_positive) > 0:
        top_pos = strong_positive.iloc[0]['特征']
        top_pos_corr = strong_positive.iloc[0]['相关系数']
        report.append(f"• 最强正相关：{top_pos} (r={top_pos_corr:.3f})")
    
    if len(strong_negative) > 0:
        top_neg = strong_negative.iloc[0]['特征']
        top_neg_corr = strong_negative.iloc[0]['相关系数']
        report.append(f"• 最强负相关：{top_neg} (r={top_neg_corr:.3f})")
    
    if len(strong_positive) == 0 and len(strong_negative) == 0:
        report.append("• 未发现显著强相关特征（|r| > 0.4）")
    
    report.append("\n" + "=" * 60)
    return "\n".join(report)


# 电商直播常用分析场景
ECOMMERCE_CORRELATION_TARGETS = {
    '利润分析': {
        'target': '考核利润',
        'features': ['业绩额', '折扣', '退货率', '人力费率', '其他费率', '转化率']
    },
    '退货分析': {
        'target': '退货率',
        'features': ['业绩折扣', '客单价', '收订量', '业绩转化率']
    },
    '转化分析': {
        'target': '业绩转化率',
        'features': ['收订金额', '退货率', '业绩折扣', '收订量']
    }
}


if __name__ == "__main__":
    # 测试示例
    np.random.seed(42)
    
    n = 200
    df = pd.DataFrame({
        '业绩额': np.random.normal(100000, 30000, n),
        '折扣': np.random.normal(0.65, 0.1, n),
        '退货率': np.random.exponential(0.15, n),
        '转化率': np.random.beta(5, 3, n),
        '人力费率': np.random.normal(0.08, 0.02, n),
    })
    
    # 生成有相关性的目标变量
    df['考核利润'] = (
        df['业绩额'] * 0.3 
        - df['业绩额'] * df['退货率'] * 0.5
        + df['业绩额'] * df['转化率'] * 0.2
        - df['业绩额'] * df['人力费率']
        + np.random.normal(0, 5000, n)
    )
    
    features = ['业绩额', '折扣', '退货率', '转化率', '人力费率']
    print(get_correlation_report(df, '考核利润', features))
