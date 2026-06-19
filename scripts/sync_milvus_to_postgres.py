#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
同步 Milvus 知识库数据到 PostgreSQL

将 Milvus 中的知识条目同步到 PostgreSQL 的 knowledge_items 表

使用方法:
    python scripts/sync_milvus_to_postgres.py
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from pymilvus import connections, Collection, utility, db
from tortoise import Tortoise

# Milvus 配置
MILVUS_URI = os.getenv("MILVUS_URI", "http://100.100.30.61:19530")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "root:Milvus")
MILVUS_DATABASE = os.getenv("MILVUS_DATABASE", "default")
COLLECTION_NAME = "rca_knowledge_base"


def connect_milvus():
    """连接 Milvus"""
    # 解析 token
    if MILVUS_TOKEN and ":" in MILVUS_TOKEN:
        user, password = MILVUS_TOKEN.split(":", 1)
    else:
        user, password = "root", "Milvus"
    
    # 解析 URI
    uri = MILVUS_URI.replace("http://", "").replace("https://", "")
    if ":" in uri:
        host, port = uri.split(":")
    else:
        host, port = uri, "19530"
    
    connections.connect(
        alias="default",
        host=host,
        port=port,
        user=user,
        password=password,
    )
    
    # 切换到指定数据库
    if MILVUS_DATABASE:
        db.using_database(MILVUS_DATABASE)
    
    print(f"[Milvus] 已连接: {host}:{port}, 数据库: {MILVUS_DATABASE}")


def get_all_milvus_data():
    """获取 Milvus 中的所有知识条目"""
    if not utility.has_collection(COLLECTION_NAME):
        print(f"[Milvus] 集合 {COLLECTION_NAME} 不存在")
        return []
    
    collection = Collection(COLLECTION_NAME)
    collection.load()
    
    # 查询所有数据（不使用向量搜索，直接查询）
    # Milvus 2.x 支持 query 方法
    results = collection.query(
        expr="id != ''",  # 匹配所有记录
        output_fields=["id", "title", "content", "category"],
        limit=10000,  # 足够大的限制
    )
    
    print(f"[Milvus] 查询到 {len(results)} 条记录")
    return results


async def init_db():
    """初始化数据库连接"""
    from app.config import settings
    
    await Tortoise.init(
        db_url=settings.DATABASE_URL,
        modules={"models": ["app.models"]},
    )
    print(f"[PostgreSQL] 已连接: {settings.DATABASE_URL.split('@')[-1]}")


async def sync_to_postgres(milvus_data: list):
    """将 Milvus 数据同步到 PostgreSQL"""
    from app.models.knowledge import KnowledgeItem
    
    synced = 0
    skipped = 0
    
    for item in milvus_data:
        milvus_id = item.get("id")
        title = item.get("title", "")
        content = item.get("content", "")
        category = item.get("category", "")
        
        # 检查是否已存在（通过 milvus_id 或 title）
        existing = await KnowledgeItem.filter(milvus_id=milvus_id).first()
        if existing:
            skipped += 1
            continue
        
        # 也检查标题是否重复
        existing_by_title = await KnowledgeItem.filter(title=title).first()
        if existing_by_title:
            # 更新 milvus_id
            existing_by_title.milvus_id = milvus_id
            await existing_by_title.save()
            skipped += 1
            continue
        
        # 创建新记录
        await KnowledgeItem.create(
            id=uuid.uuid4(),
            title=title,
            content=content,
            category=category,
            milvus_id=milvus_id,
            metadata={"source": "milvus_sync"},
        )
        synced += 1
        print(f"  [+] 同步: {title[:40]}...")
    
    return synced, skipped


async def main():
    print("=" * 60)
    print("Milvus → PostgreSQL 知识库同步")
    print("=" * 60)
    
    # 1. 连接 Milvus
    print("\n[1/3] 连接 Milvus...")
    connect_milvus()
    
    # 2. 获取 Milvus 数据
    print("\n[2/3] 读取 Milvus 数据...")
    milvus_data = get_all_milvus_data()
    
    if not milvus_data:
        print("[警告] Milvus 中没有数据，退出")
        return
    
    # 3. 同步到 PostgreSQL
    print("\n[3/3] 同步到 PostgreSQL...")
    await init_db()
    
    synced, skipped = await sync_to_postgres(milvus_data)
    
    # 关闭连接
    await Tortoise.close_connections()
    connections.disconnect("default")
    
    print("\n" + "=" * 60)
    print(f"✅ 同步完成: 新增 {synced} 条, 跳过 {skipped} 条")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
