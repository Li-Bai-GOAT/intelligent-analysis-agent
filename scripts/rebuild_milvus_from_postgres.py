#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从 PostgreSQL 重建 Milvus 知识库集合

使用方法:
    python scripts/rebuild_milvus_from_postgres.py
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from pymilvus import (
    connections, Collection, FieldSchema, CollectionSchema,
    DataType, utility, db
)
import httpx
from tortoise import Tortoise

# Milvus 配置
MILVUS_URI = os.getenv("MILVUS_URI", "http://100.100.30.61:19530")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "root:Milvus")
MILVUS_DATABASE = os.getenv("MILVUS_DATABASE", "rca_agent")
MILVUS_DIM = int(os.getenv("MILVUS_DIM", "768"))

# Embedding 配置
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://100.100.30.150:9997/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL_NAME", "Qwen3-Embedding-4B")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "none")

COLLECTION_NAME = "rca_knowledge_base"


def connect_milvus():
    """连接 Milvus 并切换到指定数据库"""
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
    
    # 创建并切换到指定数据库
    if MILVUS_DATABASE:
        existing_dbs = db.list_database()
        if MILVUS_DATABASE not in existing_dbs:
            db.create_database(MILVUS_DATABASE)
            print(f"[Milvus] 已创建数据库 {MILVUS_DATABASE}")
        db.using_database(MILVUS_DATABASE)
    
    print(f"[Milvus] 已连接: {host}:{port}, 数据库: {MILVUS_DATABASE}")


def drop_collection():
    """删除集合"""
    if utility.has_collection(COLLECTION_NAME):
        utility.drop_collection(COLLECTION_NAME)
        print(f"[Milvus] 已删除集合 {COLLECTION_NAME}")
    else:
        print(f"[Milvus] 集合 {COLLECTION_NAME} 不存在，无需删除")


def create_collection():
    """创建集合"""
    # 定义 Schema
    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8192),
        FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=MILVUS_DIM),
    ]
    
    schema = CollectionSchema(
        fields=fields,
        description="数据分析知识库",
        enable_dynamic_field=True
    )
    
    collection = Collection(
        name=COLLECTION_NAME,
        schema=schema,
    )
    
    # 创建索引
    index_params = {
        "metric_type": "COSINE",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128}
    }
    collection.create_index(field_name="embedding", index_params=index_params)
    print(f"[Milvus] 已创建集合 {COLLECTION_NAME}")
    
    return collection


def get_embedding(text: str) -> list:
    """获取文本向量"""
    url = f"{EMBEDDING_BASE_URL}/embeddings"
    headers = {"Authorization": f"Bearer {EMBEDDING_API_KEY}"}
    
    request_body = {
        "model": EMBEDDING_MODEL,
        "input": text,
        "dimensions": MILVUS_DIM,
    }
    
    response = httpx.post(
        url,
        headers=headers,
        json=request_body,
        timeout=30.0
    )
    response.raise_for_status()
    
    data = response.json()
    return data["data"][0]["embedding"]


async def init_db():
    """初始化数据库连接"""
    from app.config import settings
    
    await Tortoise.init(
        db_url=settings.DATABASE_URL,
        modules={"models": ["app.models"]},
    )
    print("[PostgreSQL] 已连接")


async def get_postgres_data():
    """从 PostgreSQL 获取知识库数据"""
    from app.models.knowledge import KnowledgeItem
    
    items = await KnowledgeItem.all()
    print(f"[PostgreSQL] 查询到 {len(items)} 条记录")
    return items


def insert_to_milvus(collection, items):
    """将数据插入 Milvus"""
    if not items:
        print("[警告] 没有数据需要插入")
        return
    
    ids = []
    titles = []
    contents = []
    categories = []
    embeddings = []
    
    total = len(items)
    for i, item in enumerate(items, 1):
        # 使用 milvus_id 或生成新的 id
        item_id = item.milvus_id or str(item.id)[:64]
        title = item.title or ""
        content = item.content or ""
        category = item.category or ""
        
        # 组合标题和内容用于向量化
        text_for_embedding = f"{title}\n{content}"
        
        print(f"[{i}/{total}] Embedding: {title[:40]}...")
        try:
            embedding = get_embedding(text_for_embedding)
        except Exception as e:
            print(f"  [错误] Embedding失败: {e}, 跳过")
            continue
        
        ids.append(item_id[:64])
        titles.append(title[:256])
        contents.append(content[:8192])
        categories.append(category[:64])
        embeddings.append(embedding)
    
    if not ids:
        print("[警告] 没有成功生成任何embedding")
        return
    
    # 插入数据
    print(f"\n[Milvus] 插入 {len(ids)} 条数据...")
    collection.insert([ids, titles, contents, categories, embeddings])
    collection.flush()
    
    # 等待索引构建完成
    print("[Milvus] 等待索引构建...")
    utility.wait_for_index_building_complete(COLLECTION_NAME)
    
    # 加载到内存
    collection.load()
    print(f"[Milvus] 已插入 {len(ids)} 条知识并加载到内存")


async def main():
    print("=" * 60)
    print("PostgreSQL → Milvus 知识库重建")
    print("=" * 60)
    
    # 1. 连接 Milvus
    print("\n[1/5] 连接 Milvus...")
    connect_milvus()
    
    # 2. 删除旧集合
    print("\n[2/5] 删除旧集合...")
    drop_collection()
    
    # 3. 创建新集合
    print("\n[3/5] 创建新集合...")
    collection = create_collection()
    
    # 4. 从 PostgreSQL 获取数据
    print("\n[4/5] 从 PostgreSQL 读取数据...")
    await init_db()
    items = await get_postgres_data()
    
    if not items:
        print("[警告] PostgreSQL 中没有数据，请先通过 Web 界面添加知识")
        return
    else:
        # 5. 插入数据到 Milvus
        print("\n[5/5] 插入数据到 Milvus...")
        insert_to_milvus(collection, items)
    
    # 关闭连接
    await Tortoise.close_connections()
    connections.disconnect("default")
    
    print("\n" + "=" * 60)
    print("✅ 重建完成!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
