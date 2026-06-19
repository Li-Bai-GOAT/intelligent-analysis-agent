# -*- coding: utf-8 -*-
"""
知识库服务

管理 PostgreSQL + Milvus 双写，知识库全局共享
"""

import logging
from typing import Optional, List
from uuid import UUID

from app.config import settings
from app.models.knowledge import KnowledgeItem
from app.repositories.knowledge_repo import KnowledgeRepository
from app.schemas.knowledge import KnowledgeCreate, KnowledgeUpdate
from app.utils.milvus_client import milvus_client

logger = logging.getLogger(__name__)

COLLECTION = settings.MILVUS_COLLECTION


class KnowledgeService:
    """知识库服务（全局共享）"""
    
    @staticmethod
    def _sync_to_milvus(item_id: str, title: str, content: str, category: str) -> bool:
        """同步到 Milvus"""
        embedding = milvus_client.get_embedding(f"{title}\n{content}")
        if not embedding:
            return False
        
        return milvus_client.insert(COLLECTION, {
            "id": item_id,
            "title": title[:256],
            "content": content[:8192],
            "category": category[:64],
            "embedding": embedding,
        })
    
    @staticmethod
    async def create(data: KnowledgeCreate) -> KnowledgeItem:
        """创建知识条目"""
        item = await KnowledgeRepository.create(
            title=data.title,
            content=data.content,
            category=data.category,
            metadata=data.metadata,
        )
        
        # 同步到 Milvus
        milvus_id = str(item.id)
        if KnowledgeService._sync_to_milvus(milvus_id, data.title, data.content, data.category):
            await KnowledgeRepository.update(item.id, milvus_id=milvus_id)
        
        return item
    
    @staticmethod
    async def get(item_id: UUID) -> Optional[KnowledgeItem]:
        """获取知识条目"""
        return await KnowledgeRepository.get_by_id(item_id)
    
    @staticmethod
    async def list(category: Optional[str] = None, limit: int = 100, offset: int = 0) -> tuple[List[KnowledgeItem], int]:
        """列出知识条目"""
        items = await KnowledgeRepository.list_all(category, limit, offset)
        total = await KnowledgeRepository.count(category)
        return items, total
    
    @staticmethod
    async def update(item_id: UUID, data: KnowledgeUpdate) -> bool:
        """更新知识条目"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        if not update_data:
            return False
        
        count = await KnowledgeRepository.update(item_id, **update_data)
        if count == 0:
            return False
        
        # 同步更新 Milvus（删除后重新插入）
        item = await KnowledgeRepository.get_by_id(item_id)
        if item:
            milvus_client.delete(COLLECTION, f'id == "{item_id}"')
            KnowledgeService._sync_to_milvus(str(item_id), item.title, item.content, item.category)
        
        return True
    
    @staticmethod
    async def delete(item_id: UUID) -> bool:
        """删除知识条目"""
        milvus_client.delete(COLLECTION, f'id == "{item_id}"')
        return await KnowledgeRepository.delete(item_id) > 0
