# -*- coding: utf-8 -*-
"""
知识库 API
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.user import User
from app.api.deps import get_admin_user
from app.schemas.knowledge import KnowledgeCreate, KnowledgeUpdate, KnowledgeResponse
from app.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["知识库"])


@router.get("", response_model=dict, summary="获取知识列表")
async def list_knowledge(
    category: Optional[str] = Query(None, description="类别筛选"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: User = Depends(get_admin_user),
):
    """分页获取知识库条目，支持按类别筛选，需要管理员权限"""
    items, total = await KnowledgeService.list(category, limit, offset)
    return {
        "items": [KnowledgeResponse.model_validate(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{item_id}", response_model=KnowledgeResponse, summary="获取知识详情")
async def get_knowledge(
    item_id: UUID,
    admin: User = Depends(get_admin_user),
):
    """根据 ID 获取单个知识条目的完整内容，需要管理员权限"""
    item = await KnowledgeService.get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识条目不存在")
    return item


@router.post("", response_model=KnowledgeResponse, status_code=status.HTTP_201_CREATED, summary="创建知识条目")
async def create_knowledge(
    data: KnowledgeCreate,
    user: User = Depends(get_admin_user),
):
    """创建新的知识条目，需要管理员权限"""
    return await KnowledgeService.create(data)


@router.put("/{item_id}", response_model=dict, summary="更新知识条目")
async def update_knowledge(
    item_id: UUID,
    data: KnowledgeUpdate,
    user: User = Depends(get_admin_user),
):
    """更新指定知识条目的内容，需要管理员权限"""
    success = await KnowledgeService.update(item_id, data)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识条目不存在")
    return {"success": True, "message": "更新成功"}


@router.delete("/{item_id}", summary="删除知识条目")
async def delete_knowledge(
    item_id: UUID,
    user: User = Depends(get_admin_user),
):
    """删除指定的知识条目，需要管理员权限"""
    success = await KnowledgeService.delete(item_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识条目不存在")
    return {"success": True, "message": "删除成功"}
