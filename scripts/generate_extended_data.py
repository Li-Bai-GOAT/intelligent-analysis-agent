#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成扩展数据：同期、环比、其他区域
确保数据逻辑一致，支持AI进行数据分析
"""

import pandas as pd
import numpy as np
import os

np.random.seed(42)

# 配置
DATA_DIR = "/home/phantom/projects/root_cause_analysis_agent/data"

# 其他区域配置
OTHER_REGIONS = {
    "华东-上海": {"scale": 1.2, "profit_margin": 0.08, "discount": 0.58},
    "华东-杭州": {"scale": 0.9, "profit_margin": 0.07, "discount": 0.56},
    "华北-北京": {"scale": 1.5, "profit_margin": 0.09, "discount": 0.60},
    "华北-天津": {"scale": 0.7, "profit_margin": 0.06, "discount": 0.55},
    "华南-广州": {"scale": 1.3, "profit_margin": 0.085, "discount": 0.59},
    "华南-深圳": {"scale": 1.1, "profit_margin": 0.075, "discount": 0.57},
    "西南-成都": {"scale": 0.8, "profit_margin": 0.065, "discount": 0.54},
    "西南-重庆": {"scale": 0.6, "profit_margin": 0.055, "discount": 0.53},
}

# 品牌增长率配置（同比）
BRAND_YOY_GROWTH = {
    "Nike": 0.12,      # 12% 增长
    "Adidas": 0.08,    # 8% 增长
    "Puma": 0.15,      # 15% 增长（表现最好）
    "Converse": 0.05,  # 5% 增长（较弱）
    "其他品牌": -0.03, # 3% 下降（问题品牌）
}

# 区域增长率配置（同比）
REGION_YOY_GROWTH = {
    "鄂赣闽-武汉": 0.10,
    "鄂赣闽-福州": 0.08,
    "鄂赣闽-南昌": 0.05,  # 表现较弱
    "鄂赣闽-厦门": 0.12,
}


def generate_yoy_data_sales(df: pd.DataFrame) -> pd.DataFrame:
    """为销售明细表生成符合逻辑的同期数据"""
    print("生成销售明细表同期数据...")
    
    df = df.copy()
    
    # 计算同期数据（去年同期 = 当期 / (1 + 增长率)）
    for idx, row in df.iterrows():
        brand = row["品牌组名称"]
        region = row["业绩归属大区"]
        
        # 获取增长率（品牌 + 区域 + 随机波动）
        brand_growth = BRAND_YOY_GROWTH.get(brand, 0.05)
        region_growth = REGION_YOY_GROWTH.get(region, 0.08)
        combined_growth = (brand_growth + region_growth) / 2 + np.random.uniform(-0.05, 0.05)
        
        # 计算同期值
        divisor = 1 + combined_growth
        
        # 数量类字段
        df.at[idx, "业绩量_同期"] = max(1, int(row["业绩量"] / divisor))
        df.at[idx, "收订量_同期"] = max(1, int(row["收订量"] / divisor))
        df.at[idx, "取消收订量_同期"] = max(0, int(row["取消收订量"] / divisor))
        df.at[idx, "实际收订量_同期"] = max(1, int(row["实际收订量"] / divisor))
        
        # 金额类字段
        df.at[idx, "业绩额_同期"] = round(row["业绩额"] / divisor, 2)
        df.at[idx, "业绩单据牌价额_同期"] = round(row["业绩单据牌价额"] / divisor, 2)
        df.at[idx, "收订金额_同期"] = round(row["收订金额"] / divisor, 2)
        df.at[idx, "收订牌价额_同期"] = round(row["收订牌价额"] / divisor, 2)
        df.at[idx, "取消收订金额_同期"] = round(row["取消收订金额"] / divisor, 2)
        df.at[idx, "取消收订牌价额_同期"] = round(row["取消收订牌价额"] / divisor, 2)
        df.at[idx, "实际收订金额_同期"] = round(row["实际收订金额"] / divisor, 2)
        df.at[idx, "实际收订牌价额_同期"] = round(row["实际收订牌价额"] / divisor, 2)
        df.at[idx, "发货额_同期"] = round(row["发货额"] / divisor, 2)
        df.at[idx, "退货额_同期"] = round(row["退货额"] / divisor, 2)
        
        # 单价（去年略低）
        df.at[idx, "业绩单据牌价_同期"] = round(row["业绩单据牌价"] * 0.98, 2)
        
        # 折扣（去年略高，折扣控制更差）
        df.at[idx, "业绩折扣_同期"] = round(min(0.75, row["业绩折扣"] + np.random.uniform(0.01, 0.03)), 4)
        df.at[idx, "收订折扣_同期"] = round(min(0.75, row["收订折扣"] + np.random.uniform(0.01, 0.03)), 4)
        
        # 退货率（去年略高）
        df.at[idx, "退货率_同期"] = round(min(0.30, row["退货率"] + np.random.uniform(0.01, 0.03)), 4)
    
    return df


def generate_yoy_data_raw(df: pd.DataFrame) -> pd.DataFrame:
    """为原始底层数据生成符合逻辑的同期数据"""
    print("生成原始底层数据同期数据...")
    
    df = df.copy()
    
    for idx, row in df.iterrows():
        brand = row["品牌组"]
        region = row["新大区"]
        
        # 获取增长率
        brand_growth = BRAND_YOY_GROWTH.get(brand, 0.05)
        region_growth = REGION_YOY_GROWTH.get(region, 0.08)
        combined_growth = (brand_growth + region_growth) / 2 + np.random.uniform(-0.03, 0.03)
        
        divisor = 1 + combined_growth
        
        # 同期数据
        df.at[idx, "牌价收入_同期"] = round(row["牌价收入"] / divisor, 2)
        df.at[idx, "业绩额_同期"] = round(row["业绩额"] / divisor, 2)
        df.at[idx, "考核利润_同期"] = round(row["考核利润"] / divisor, 2)
        df.at[idx, "地区利润_同期"] = round(row["地区利润"] / divisor, 2)
    
    return df


def generate_wow_data_sales(df: pd.DataFrame) -> pd.DataFrame:
    """生成环比数据（上周数据）"""
    print("生成销售明细表环比数据...")
    
    df = df.copy()
    
    # 添加环比列
    wow_cols = [
        "业绩量_环比", "业绩额_环比", "业绩折扣_环比",
        "收订量_环比", "收订金额_环比", "退货率_环比"
    ]
    for col in wow_cols:
        if col not in df.columns:
            df[col] = 0.0
    
    for idx, row in df.iterrows():
        # 环比增长率（周环比波动较小，±5%左右）
        wow_growth = np.random.uniform(-0.05, 0.08)
        divisor = 1 + wow_growth
        
        df.at[idx, "业绩量_环比"] = max(1, int(row["业绩量"] / divisor))
        df.at[idx, "业绩额_环比"] = round(row["业绩额"] / divisor, 2)
        df.at[idx, "业绩折扣_环比"] = round(row["业绩折扣"] + np.random.uniform(-0.01, 0.01), 4)
        df.at[idx, "收订量_环比"] = max(1, int(row["收订量"] / divisor))
        df.at[idx, "收订金额_环比"] = round(row["收订金额"] / divisor, 2)
        df.at[idx, "退货率_环比"] = round(max(0, row["退货率"] + np.random.uniform(-0.02, 0.02)), 4)
    
    return df


def generate_other_regions_sales(df: pd.DataFrame) -> pd.DataFrame:
    """生成其他区域的销售明细数据"""
    print("生成其他区域销售明细数据...")
    
    # 以鄂赣闽-武汉为模板
    template_df = df[df["业绩归属大区"] == "鄂赣闽-武汉"].copy()
    
    all_regions_data = [df]  # 保留原始数据
    
    for region_name, config in OTHER_REGIONS.items():
        region_df = template_df.copy()
        region_df["业绩归属大区"] = region_name
        
        scale = config["scale"]
        discount = config["discount"]
        
        # 调整主播编码和名称（避免重复）
        region_prefix = region_name.split("-")[0][:2]
        region_df["主播编码"] = region_df["主播编码"].apply(lambda x: f"{region_prefix}{x}")
        region_df["主播名称"] = region_df["主播名称"].apply(lambda x: f"{region_prefix}-{x}")
        
        # 调整数值
        for col in ["业绩量", "业绩额", "业绩单据牌价额", "收订量", "收订金额", 
                    "收订牌价额", "取消收订量", "取消收订金额", "实际收订量",
                    "实际收订金额", "实际收订牌价额", "发货额", "退货额"]:
            if col in region_df.columns:
                noise = np.random.uniform(0.9, 1.1, len(region_df))
                region_df[col] = (region_df[col] * scale * noise).round(2)
        
        # 调整折扣
        region_df["业绩折扣"] = discount + np.random.uniform(-0.02, 0.02, len(region_df))
        region_df["收订折扣"] = discount + np.random.uniform(-0.02, 0.02, len(region_df))
        
        # 调整退货率
        region_df["退货率"] = np.random.uniform(0.08, 0.15, len(region_df)).round(4)
        
        # 重新计算同期和环比
        region_df = generate_yoy_data_sales(region_df)
        region_df = generate_wow_data_sales(region_df)
        
        all_regions_data.append(region_df)
    
    return pd.concat(all_regions_data, ignore_index=True)


def generate_other_regions_raw(df: pd.DataFrame) -> pd.DataFrame:
    """生成其他区域的原始底层数据"""
    print("生成其他区域原始底层数据...")
    
    # 以现有数据为模板
    template_df = df[df["新大区"].str.startswith("鄂赣闽")].copy()
    
    all_regions_data = [df]
    
    for region_name, config in OTHER_REGIONS.items():
        region_df = template_df.copy()
        
        # 更新区域名称
        region_df["新大区"] = region_name
        
        scale = config["scale"]
        profit_margin = config["profit_margin"]
        
        # 调整金额类字段
        amount_cols = [c for c in region_df.columns if any(x in c for x in ["收入", "额", "利润", "费用", "返利", "毛利"])]
        for col in amount_cols:
            if col in region_df.columns and region_df[col].dtype in [np.float64, np.int64]:
                noise = np.random.uniform(0.85, 1.15, len(region_df))
                region_df[col] = (region_df[col] * scale * noise).round(2)
        
        # 调整达成率
        rate_cols = [c for c in region_df.columns if "达成" in c or "率" in c]
        for col in rate_cols:
            if col in region_df.columns and region_df[col].dtype in [np.float64, np.int64]:
                region_df[col] = region_df[col] * np.random.uniform(0.95, 1.05, len(region_df))
        
        # 重新计算同期
        region_df = generate_yoy_data_raw(region_df)
        
        all_regions_data.append(region_df)
    
    return pd.concat(all_regions_data, ignore_index=True)


def validate_data(df_sales: pd.DataFrame, df_raw: pd.DataFrame):
    """验证数据一致性"""
    print("\n=== 数据验证 ===")
    
    # 销售明细表
    print("\n销售明细表:")
    print(f"  总行数: {len(df_sales)}")
    print(f"  区域数: {df_sales['业绩归属大区'].nunique()}")
    print(f"  区域列表: {df_sales['业绩归属大区'].unique().tolist()}")
    print(f"  主播数: {df_sales['主播名称'].nunique()}")
    
    # 检查同期数据
    yoy_check = df_sales["业绩额_同期"].notna().sum()
    print(f"  同期数据填充率: {yoy_check / len(df_sales) * 100:.1f}%")
    
    # 检查同比增长率
    df_sales["_yoy_growth"] = (df_sales["业绩额"] - df_sales["业绩额_同期"]) / df_sales["业绩额_同期"]
    print(f"  平均同比增长率: {df_sales['_yoy_growth'].mean() * 100:.1f}%")
    df_sales.drop("_yoy_growth", axis=1, inplace=True)
    
    # 原始底层数据
    print("\n原始底层数据:")
    print(f"  总行数: {len(df_raw)}")
    print(f"  区域数: {df_raw['新大区'].nunique()}")
    print(f"  区域列表: {df_raw['新大区'].unique().tolist()}")
    
    print("\n✓ 数据验证完成")


def main():
    print("=" * 60)
    print("生成扩展数据：同期、环比、其他区域")
    print("=" * 60)
    
    # 读取原始数据
    print("\n读取原始数据...")
    df_sales = pd.read_excel(f"{DATA_DIR}/销售明细表.xlsx")
    df_raw = pd.read_excel(f"{DATA_DIR}/原始底层数据.xlsx")
    
    print(f"销售明细表: {df_sales.shape}")
    print(f"原始底层数据: {df_raw.shape}")
    
    # 备份原始数据
    backup_dir = f"{DATA_DIR}/backup"
    os.makedirs(backup_dir, exist_ok=True)
    df_sales.to_excel(f"{backup_dir}/销售明细表_backup.xlsx", index=False)
    df_raw.to_excel(f"{backup_dir}/原始底层数据_backup.xlsx", index=False)
    print(f"\n原始数据已备份到 {backup_dir}/")
    
    # 1. 生成同期数据
    df_sales = generate_yoy_data_sales(df_sales)
    df_raw = generate_yoy_data_raw(df_raw)
    
    # 2. 生成环比数据
    df_sales = generate_wow_data_sales(df_sales)
    
    # 3. 生成其他区域数据
    df_sales_extended = generate_other_regions_sales(df_sales)
    df_raw_extended = generate_other_regions_raw(df_raw)
    
    # 验证数据
    validate_data(df_sales_extended, df_raw_extended)
    
    # 保存扩展数据
    print("\n保存扩展数据...")
    df_sales_extended.to_excel(f"{DATA_DIR}/销售明细表.xlsx", index=False)
    df_raw_extended.to_excel(f"{DATA_DIR}/原始底层数据.xlsx", index=False)
    
    print(f"\n✓ 销售明细表: {df_sales_extended.shape}")
    print(f"✓ 原始底层数据: {df_raw_extended.shape}")
    
    print("\n" + "=" * 60)
    print("数据生成完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
