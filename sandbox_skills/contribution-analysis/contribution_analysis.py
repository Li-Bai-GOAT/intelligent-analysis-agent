"""
基于树模型的特征贡献度分析（TreeSHAP）

用于识别影响业绩/利润的关键因素，快速轻量无需GPU。
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
import warnings

# 尝试导入shap，如果失败则使用简化版本
try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False
    warnings.warn("shap未安装，将使用基于特征重要性的简化版本")


def analyze_feature_importance(
    df: pd.DataFrame,
    target: str,
    features: List[str],
    model_type: str = 'rf',
    n_estimators: int = 100
) -> Dict:
    """
    分析特征对目标变量的贡献度
    
    Args:
        df: 数据DataFrame
        target: 目标变量列名
        features: 特征列名列表
        model_type: 模型类型 ('rf' for RandomForest, 'gb' for GradientBoosting)
        n_estimators: 树的数量
        
    Returns:
        dict: 包含特征重要性和SHAP值
    """
    # 验证列存在
    valid_features = [f for f in features if f in df.columns]
    if target not in df.columns:
        raise ValueError(f"目标变量 {target} 不存在")
    if len(valid_features) < 1:
        raise ValueError(f"没有有效的特征列")
    
    # 准备数据
    df_clean = df[valid_features + [target]].dropna()
    X = df_clean[valid_features]
    y = df_clean[target]
    
    if len(X) < 10:
        raise ValueError(f"数据量太少: {len(X)}，需要至少10条")
    
    # 训练模型
    if model_type == 'rf':
        model = RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=6,
            random_state=42,
            n_jobs=-1
        )
    else:
        model = GradientBoostingRegressor(
            n_estimators=n_estimators,
            max_depth=4,
            random_state=42
        )
    
    model.fit(X, y)
    
    # 获取基本特征重要性
    basic_importance = dict(zip(valid_features, model.feature_importances_))
    
    result = {
        'features': valid_features,
        'target': target,
        'n_samples': len(X),
        'model_type': model_type,
        'model_score': model.score(X, y),
        'basic_importance': basic_importance,
    }
    
    # 使用SHAP计算贡献度
    if HAS_SHAP:
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)
        
        # 计算平均绝对SHAP值作为特征重要性
        mean_abs_shap = np.abs(shap_values).mean(axis=0)
        shap_importance = dict(zip(valid_features, mean_abs_shap))
        
        # 按重要性排序
        sorted_importance = dict(sorted(
            shap_importance.items(),
            key=lambda x: x[1],
            reverse=True
        ))
        
        result.update({
            'feature_importance': sorted_importance,
            'shap_values': shap_values,
            'base_value': explainer.expected_value,
            'method': 'TreeSHAP'
        })
    else:
        # 简化版：使用基本特征重要性
        sorted_importance = dict(sorted(
            basic_importance.items(),
            key=lambda x: x[1],
            reverse=True
        ))
        result.update({
            'feature_importance': sorted_importance,
            'method': 'FeatureImportance'
        })
    
    return result


def explain_single_sample(
    df: pd.DataFrame,
    target: str,
    features: List[str],
    sample_idx: int,
    model_type: str = 'rf'
) -> Dict:
    """
    解释单个样本的预测结果
    
    Args:
        df: 数据DataFrame
        target: 目标变量列名
        features: 特征列名列表
        sample_idx: 样本索引
        model_type: 模型类型
        
    Returns:
        dict: 该样本的解释信息
    """
    valid_features = [f for f in features if f in df.columns]
    
    df_clean = df[valid_features + [target]].dropna()
    X = df_clean[valid_features]
    y = df_clean[target]
    
    # 训练模型
    if model_type == 'rf':
        model = RandomForestRegressor(n_estimators=100, max_depth=6, random_state=42)
    else:
        model = GradientBoostingRegressor(n_estimators=100, max_depth=4, random_state=42)
    
    model.fit(X, y)
    
    # 获取样本数据
    if sample_idx >= len(X):
        sample_idx = len(X) - 1
    
    sample_X = X.iloc[[sample_idx]]
    sample_y = y.iloc[sample_idx]
    predicted_y = model.predict(sample_X)[0]
    
    result = {
        'sample_idx': sample_idx,
        'actual_value': sample_y,
        'predicted_value': predicted_y,
        'sample_features': dict(sample_X.iloc[0]),
    }
    
    if HAS_SHAP:
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(sample_X)[0]
        
        # 创建特征-SHAP值对
        feature_shap = list(zip(valid_features, shap_values))
        
        # 排序找出正负贡献最大的因素
        sorted_by_value = sorted(feature_shap, key=lambda x: x[1], reverse=True)
        
        positive_factors = [(f, v) for f, v in sorted_by_value if v > 0]
        negative_factors = [(f, v) for f, v in sorted_by_value if v < 0]
        
        result.update({
            'base_value': explainer.expected_value,
            'shap_values': dict(feature_shap),
            'top_positive_factors': positive_factors[:3],
            'top_negative_factors': negative_factors[-3:][::-1],
            'method': 'TreeSHAP'
        })
    else:
        # 简化版：基于与均值的偏差
        mean_values = X.mean()
        deviations = sample_X.iloc[0] - mean_values
        
        result.update({
            'deviations_from_mean': dict(deviations),
            'method': 'MeanDeviation'
        })
    
    return result


def get_top_factors(
    importance_dict: Dict[str, float],
    top_k: int = 5
) -> List[Tuple[str, float]]:
    """
    获取贡献度最高的K个因素
    
    Args:
        importance_dict: 特征重要性字典
        top_k: 返回前K个
        
    Returns:
        List of (feature_name, importance) tuples
    """
    sorted_items = sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)
    return sorted_items[:top_k]


def contribution_report(
    df: pd.DataFrame,
    target: str,
    features: List[str]
) -> str:
    """
    生成完整的贡献度分析报告
    
    Args:
        df: 数据DataFrame
        target: 目标变量列名
        features: 特征列名列表
        
    Returns:
        str: 格式化的报告
    """
    result = analyze_feature_importance(df, target, features)
    
    report = []
    report.append("=" * 60)
    report.append("📊 特征贡献度分析报告")
    report.append("=" * 60)
    
    report.append(f"\n目标变量: {target}")
    report.append(f"样本数量: {result['n_samples']}")
    report.append(f"模型拟合度 (R²): {result['model_score']:.3f}")
    report.append(f"分析方法: {result['method']}")
    
    report.append(f"\n{'='*40}")
    report.append("📈 特征重要性排名")
    report.append("=" * 40)
    
    importance = result['feature_importance']
    total_importance = sum(importance.values())
    
    for i, (feat, imp) in enumerate(importance.items(), 1):
        pct = imp / total_importance * 100 if total_importance > 0 else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        report.append(f"{i:2d}. {feat:20s} {bar} {pct:5.1f}%")
    
    # 主要发现
    report.append(f"\n{'='*40}")
    report.append("🔍 主要发现")
    report.append("=" * 40)
    
    top_factors = get_top_factors(importance, 3)
    top_factor = top_factors[0] if top_factors else (None, 0)
    
    if top_factor[0]:
        report.append(f"• 对{target}影响最大的因素是【{top_factor[0]}】")
        report.append(f"• 前三大影响因素合计贡献 {sum(v for _, v in top_factors) / total_importance * 100:.1f}% 的解释力")
    
    report.append("\n" + "=" * 60)
    
    return "\n".join(report)


def batch_explain(
    df: pd.DataFrame,
    target: str,
    features: List[str],
    filter_col: Optional[str] = None,
    filter_condition: str = 'bottom',
    n_samples: int = 10
) -> pd.DataFrame:
    """
    批量解释多个样本
    
    Args:
        df: 数据DataFrame
        target: 目标变量
        features: 特征列
        filter_col: 筛选列（如按目标值筛选最差的）
        filter_condition: 'bottom' 或 'top'
        n_samples: 解释的样本数
        
    Returns:
        DataFrame: 每个样本的主要影响因素
    """
    valid_features = [f for f in features if f in df.columns]
    df_clean = df[valid_features + [target]].dropna().copy()
    
    # 筛选样本
    if filter_col and filter_col in df_clean.columns:
        if filter_condition == 'bottom':
            sample_indices = df_clean[filter_col].nsmallest(n_samples).index.tolist()
        else:
            sample_indices = df_clean[filter_col].nlargest(n_samples).index.tolist()
    else:
        sample_indices = df_clean.head(n_samples).index.tolist()
    
    # 训练模型
    X = df_clean[valid_features]
    y = df_clean[target]
    
    model = RandomForestRegressor(n_estimators=100, max_depth=6, random_state=42)
    model.fit(X, y)
    
    results = []
    
    if HAS_SHAP:
        explainer = shap.TreeExplainer(model)
        
        for idx in sample_indices:
            loc_idx = df_clean.index.get_loc(idx)
            sample_X = X.iloc[[loc_idx]]
            shap_vals = explainer.shap_values(sample_X)[0]
            
            # 找主要因素
            feature_shap = list(zip(valid_features, shap_vals))
            sorted_shap = sorted(feature_shap, key=lambda x: abs(x[1]), reverse=True)
            
            top_factor = sorted_shap[0] if sorted_shap else ('无', 0)
            
            results.append({
                'index': idx,
                target: df_clean.loc[idx, target],
                '主要影响因素': top_factor[0],
                '影响值': top_factor[1],
                '影响方向': '正向' if top_factor[1] > 0 else '负向'
            })
    
    return pd.DataFrame(results)


if __name__ == "__main__":
    # 测试示例
    np.random.seed(42)
    
    # 生成测试数据
    n = 200
    df = pd.DataFrame({
        '业绩额': np.random.normal(100000, 30000, n),
        '折扣': np.random.normal(0.65, 0.1, n),
        '退货率': np.random.exponential(0.15, n),
        '转化率': np.random.beta(5, 3, n),
        '人力费用率': np.random.normal(0.08, 0.02, n),
    })
    
    # 生成目标变量（模拟利润）
    df['考核利润'] = (
        df['业绩额'] * 0.3 
        - df['业绩额'] * df['折扣'] * 0.1
        - df['业绩额'] * df['退货率'] * 0.5
        + df['业绩额'] * df['转化率'] * 0.2
        - df['业绩额'] * df['人力费用率']
        + np.random.normal(0, 5000, n)
    )
    
    # 分析
    features = ['业绩额', '折扣', '退货率', '转化率', '人力费用率']
    print(contribution_report(df, '考核利润', features))
    
    # 解释单个样本
    print("\n" + "=" * 60)
    print("单样本解释示例（利润最低的账号）")
    print("=" * 60)
    
    worst_idx = df['考核利润'].idxmin()
    explanation = explain_single_sample(df, '考核利润', features, worst_idx)
    
    print(f"实际利润: {explanation['actual_value']:,.0f}")
    print(f"预测利润: {explanation['predicted_value']:,.0f}")
    
    if 'top_negative_factors' in explanation:
        print("\n主要负面因素:")
        for feat, val in explanation['top_negative_factors']:
            print(f"  - {feat}: {val:+.0f}")
