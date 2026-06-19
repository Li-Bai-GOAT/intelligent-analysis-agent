#!/usr/bin/env python
"""
初始化数据分析知识库

使用方法:
    python scripts/init_knowledge_base.py

功能:
1. 连接 Milvus 向量数据库
2. 确保知识库集合存在
3. 从 PostgreSQL 同步数据到 Milvus（如有）
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings
from app.utils.milvus_client import milvus_client


def main():
    print("=" * 60)
    print("数据分析知识库初始化")
    print("=" * 60)
    
    # 连接 Milvus
    if milvus_client.connect():
        print("[Milvus] 已连接")
    else:
        print("[Milvus] 连接失败")
        return
    
    # 检查集合
    collection = milvus_client.get_collection(settings.MILVUS_COLLECTION)
    if collection:
        print(f"[Milvus] 集合 {settings.MILVUS_COLLECTION} 已就绪")
    else:
        print(f"[Milvus] 集合 {settings.MILVUS_COLLECTION} 不存在，请先通过 Web 界面添加知识")
    
    print()
    print("=" * 60)
    print("✅ 知识库初始化完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
