#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
为 knowledge_items 表的 category 字段添加索引
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from tortoise import Tortoise
from app.config import settings


async def add_index():
    await Tortoise.init(
        db_url=settings.DATABASE_URL,
        modules={"models": ["app.models"]},
    )
    
    conn = Tortoise.get_connection("default")
    
    # 检查索引是否存在
    check_sql = """
        SELECT indexname FROM pg_indexes 
        WHERE tablename = 'knowledge_items' AND indexname = 'idx_knowledge_items_category'
    """
    result = await conn.execute_query(check_sql)
    
    if result[1]:
        print("[跳过] 索引 idx_knowledge_items_category 已存在")
    else:
        # 创建索引
        create_sql = "CREATE INDEX idx_knowledge_items_category ON knowledge_items (category)"
        await conn.execute_query(create_sql)
        print("[完成] 已创建索引 idx_knowledge_items_category")
    
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(add_index())
