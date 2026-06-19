#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复数据一致性问题，确保所有公式计算正确
"""

import pandas as pd
import numpy as np

np.random.seed(42)

DATA_DIR = "/home/phantom/projects/root_cause_analysis_agent/data"


def fix_sales_data(df: pd.DataFrame) -> pd.DataFrame:
    """修复销售明细表数据一致性"""
    print("修复销售明细表...")
    df = df.copy()
    
    # 1. 修复业绩折扣 = 业绩额 / 业绩单据牌价额
    df["业绩折扣"] = (df["业绩额"] / df["业绩单据牌价额"]).round(4)
    
    # 2. 修复实际收订量 = 收订量 - 取消收订量
    df["实际收订量"] = df["收订量"] - df["取消收订量"]
    
    # 3. 修复实际收订金额 = 收订金额 - 取消收订金额
    df["实际收订金额"] = (df["收订金额"] - df["取消收订金额"]).round(2)
    
    # 4. 修复实际收订牌价额 = 收订牌价额 - 取消收订牌价额
    df["实际收订牌价额"] = (df["收订牌价额"] - df["取消收订牌价额"]).round(2)
    
    # 5. 修复收订折扣 = 收订金额 / 收订牌价额
    df["收订折扣"] = (df["收订金额"] / df["收订牌价额"]).round(4)
    
    # 6. 修复退货率 = 退货额 / 发货额
    df["退货率"] = np.where(
        df["发货额"] > 0,
        (df["退货额"] / df["发货额"]).round(4),
        0
    )
    
    # 7. 修复同期数据的公式一致性
    # 同期业绩折扣 = 同期业绩额 / 同期业绩单据牌价额
    df["业绩折扣_同期"] = np.where(
        df["业绩单据牌价额_同期"] > 0,
        (df["业绩额_同期"] / df["业绩单据牌价额_同期"]).round(4),
        df["业绩折扣_同期"]
    )
    
    # 同期实际收订量
    df["实际收订量_同期"] = df["收订量_同期"] - df["取消收订量_同期"]
    
    # 同期实际收订金额
    df["实际收订金额_同期"] = (df["收订金额_同期"] - df["取消收订金额_同期"]).round(2)
    
    # 同期实际收订牌价额
    df["实际收订牌价额_同期"] = (df["收订牌价额_同期"] - df["取消收订牌价额_同期"]).round(2)
    
    # 同期收订折扣
    df["收订折扣_同期"] = np.where(
        df["收订牌价额_同期"] > 0,
        (df["收订金额_同期"] / df["收订牌价额_同期"]).round(4),
        df["收订折扣_同期"]
    )
    
    # 同期退货率
    df["退货率_同期"] = np.where(
        df["发货额_同期"] > 0,
        (df["退货额_同期"] / df["发货额_同期"]).round(4),
        0
    )
    
    # 8. 修复环比数据的公式一致性（如果有环比列）
    if "业绩额_环比" in df.columns:
        # 环比折扣需要基于实际数据计算，这里保持合理范围
        df["业绩折扣_环比"] = df["业绩折扣"] + np.random.uniform(-0.01, 0.01, len(df))
        df["业绩折扣_环比"] = df["业绩折扣_环比"].clip(0.45, 0.75).round(4)
        
        df["退货率_环比"] = df["退货率"] + np.random.uniform(-0.02, 0.02, len(df))
        df["退货率_环比"] = df["退货率_环比"].clip(0, 0.30).round(4)
    
    return df


def fix_raw_data(df: pd.DataFrame) -> pd.DataFrame:
    """修复原始底层数据一致性"""
    print("修复原始底层数据...")
    df = df.copy()
    
    # 1. 考核利润 = 地区利润 + 返利
    if "返利" in df.columns and "地区利润" in df.columns:
        df["考核利润"] = (df["地区利润"] + df["返利"]).round(2)
    
    # 2. 重新计算达成率
    if "业绩额月度目标" in df.columns:
        df["业绩目标达成"] = np.where(
            df["业绩额月度目标"] > 0,
            (df["业绩额"] / df["业绩额月度目标"]).round(4),
            0
        )
    
    if "考核利润月度目标" in df.columns:
        df["考核利润目标达成"] = np.where(
            df["考核利润月度目标"] > 0,
            (df["考核利润"] / df["考核利润月度目标"]).round(4),
            0
        )
    
    if "地区利润月度目标" in df.columns:
        df["地区利润目标达成"] = np.where(
            df["地区利润月度目标"] > 0,
            (df["地区利润"] / df["地区利润月度目标"]).round(4),
            0
        )
    
    if "牌价月度目标" in df.columns:
        df["牌价目标达成"] = np.where(
            df["牌价月度目标"] > 0,
            (df["牌价收入"] / df["牌价月度目标"]).round(4),
            0
        )
    
    # 3. 计算目标差异
    if "业绩额月度目标" in df.columns:
        df["业绩目标差异"] = (df["业绩额"] - df["业绩额月度目标"]).round(2)
    
    if "考核利润月度目标" in df.columns:
        df["考核利润目标差异"] = (df["考核利润"] - df["考核利润月度目标"]).round(2)
    
    if "地区利润月度目标" in df.columns:
        df["地区利润目标差异"] = (df["地区利润"] - df["地区利润月度目标"]).round(2)
    
    if "牌价月度目标" in df.columns:
        df["牌价目标差异"] = (df["牌价收入"] - df["牌价月度目标"]).round(2)
    
    # 4. 同期数据的考核利润一致性
    if "地区利润_同期" in df.columns and "返利" in df.columns:
        # 假设同期返利也按比例
        返利比例 = df["返利"] / df["地区利润"].replace(0, 1)
        df["考核利润_同期"] = (df["地区利润_同期"] * (1 + 返利比例.clip(0, 0.5))).round(2)
    
    return df


def validate_data(df_sales: pd.DataFrame, df_raw: pd.DataFrame):
    """验证修复后的数据"""
    print("\n" + "=" * 70)
    print("修复后数据验证")
    print("=" * 70)
    
    # 销售明细表验证
    print("\n【销售明细表】")
    
    # 1. 业绩折扣
    calc_discount = df_sales["业绩额"] / df_sales["业绩单据牌价额"]
    diff = abs(df_sales["业绩折扣"] - calc_discount)
    print(f"1. 业绩折扣一致性: 不一致行数 = {(diff > 0.001).sum()}")
    
    # 2. 实际收订量
    calc_qty = df_sales["收订量"] - df_sales["取消收订量"]
    diff = abs(df_sales["实际收订量"] - calc_qty)
    print(f"2. 实际收订量一致性: 不一致行数 = {(diff > 0).sum()}")
    
    # 3. 实际收订金额
    calc_amt = df_sales["收订金额"] - df_sales["取消收订金额"]
    diff = abs(df_sales["实际收订金额"] - calc_amt)
    print(f"3. 实际收订金额一致性: 不一致行数 = {(diff > 0.01).sum()}")
    
    # 4. 退货率
    calc_return = np.where(df_sales["发货额"] > 0, df_sales["退货额"] / df_sales["发货额"], 0)
    diff = abs(df_sales["退货率"] - calc_return)
    print(f"4. 退货率一致性: 不一致行数 = {(diff > 0.001).sum()}")
    
    # 5. 收订折扣
    calc_order_discount = df_sales["收订金额"] / df_sales["收订牌价额"]
    diff = abs(df_sales["收订折扣"] - calc_order_discount)
    print(f"5. 收订折扣一致性: 不一致行数 = {(diff > 0.001).sum()}")
    
    # 原始底层数据验证
    print("\n【原始底层数据】")
    
    # 1. 考核利润
    if "返利" in df_raw.columns:
        calc_profit = df_raw["地区利润"] + df_raw["返利"]
        diff = abs(df_raw["考核利润"] - calc_profit)
        print(f"1. 考核利润一致性: 不一致行数 = {(diff > 0.01).sum()}")
    
    # 2. 达成率
    if "业绩额月度目标" in df_raw.columns:
        calc_rate = df_raw["业绩额"] / df_raw["业绩额月度目标"]
        diff = abs(df_raw["业绩目标达成"] - calc_rate)
        print(f"2. 业绩达成率一致性: 不一致行数 = {(diff > 0.001).sum()}")
    
    # 数据质量统计
    print("\n【数据质量统计】")
    print(f"销售明细表: {len(df_sales)} 行, {len(df_sales.columns)} 列")
    print(f"原始底层数据: {len(df_raw)} 行, {len(df_raw.columns)} 列")
    
    # 同比增长率
    yoy_sales = (df_sales["业绩额"] - df_sales["业绩额_同期"]) / df_sales["业绩额_同期"]
    print(f"\n销售明细同比增长率: {yoy_sales.mean()*100:.1f}% (范围: {yoy_sales.min()*100:.1f}% ~ {yoy_sales.max()*100:.1f}%)")
    
    yoy_raw = (df_raw["业绩额"] - df_raw["业绩额_同期"]) / df_raw["业绩额_同期"]
    print(f"原始数据同比增长率: {yoy_raw.mean()*100:.1f}% (范围: {yoy_raw.min()*100:.1f}% ~ {yoy_raw.max()*100:.1f}%)")


def main():
    print("=" * 70)
    print("修复数据一致性")
    print("=" * 70)
    
    # 读取数据
    df_sales = pd.read_excel(f"{DATA_DIR}/销售明细表.xlsx")
    df_raw = pd.read_excel(f"{DATA_DIR}/原始底层数据.xlsx")
    
    print("\n读取数据:")
    print(f"  销售明细表: {df_sales.shape}")
    print(f"  原始底层数据: {df_raw.shape}")
    
    # 修复数据
    df_sales_fixed = fix_sales_data(df_sales)
    df_raw_fixed = fix_raw_data(df_raw)
    
    # 验证
    validate_data(df_sales_fixed, df_raw_fixed)
    
    # 保存
    print("\n保存修复后的数据...")
    df_sales_fixed.to_excel(f"{DATA_DIR}/销售明细表.xlsx", index=False)
    df_raw_fixed.to_excel(f"{DATA_DIR}/原始底层数据.xlsx", index=False)
    
    print("\n✓ 数据修复完成!")


if __name__ == "__main__":
    main()
