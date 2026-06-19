# -*- coding: utf-8 -*-
"""
知识库数据访问层
"""

from typing import Optional, List
from uuid import UUID

from app.models.knowledge import KnowledgeItem


class KnowledgeRepository:
    """知识库数据访问"""
    
    @staticmethod
    async def create(
        title: str,
        content: str,
        category: str,
        metadata: Optional[dict] = None,
        milvus_id: Optional[str] = None,
    ) -> KnowledgeItem:
        return await KnowledgeItem.create(
            title=title,
            content=content,
            category=category,
            metadata=metadata,
            milvus_id=milvus_id,
        )
    
    @staticmethod
    async def get_by_id(item_id: UUID) -> Optional[KnowledgeItem]:
        return await KnowledgeItem.filter(id=item_id).first()
    
    @staticmethod
    async def list_all(
        category: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[KnowledgeItem]:
        query = KnowledgeItem.all()
        if category:
            query = query.filter(category=category)
        return await query.offset(offset).limit(limit).order_by("-updated_at")
    
    @staticmethod
    async def update(item_id: UUID, **kwargs) -> int:
        return await KnowledgeItem.filter(id=item_id).update(**kwargs)
    
    @staticmethod
    async def delete(item_id: UUID) -> int:
        return await KnowledgeItem.filter(id=item_id).delete()
    
    @staticmethod
    async def count(category: Optional[str] = None) -> int:
        query = KnowledgeItem.all()
        if category:
            query = query.filter(category=category)
        return await query.count()
