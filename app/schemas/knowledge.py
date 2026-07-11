# -*- coding: utf-8 -*-
"""
知识库相关数据模型
"""

from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class KnowledgeCreate(BaseModel):
    """创建知识条目"""
    title: str = Field(..., max_length=256)
    content: str
    category: str = Field(..., max_length=64)
    metadata: Optional[Dict[str, Any]] = None


class KnowledgeUpdate(BaseModel):
    """更新知识条目"""
    title: Optional[str] = Field(None, max_length=256)
    content: Optional[str] = None
    category: Optional[str] = Field(None, max_length=64)
    metadata: Optional[Dict[str, Any]] = None


class KnowledgeResponse(BaseModel):
    """知识条目响应"""
    id: UUID
    title: str
    content: str
    category: str
    metadata: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
