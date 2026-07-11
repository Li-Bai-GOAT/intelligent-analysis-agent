# -*- coding: utf-8 -*-
"""
会话相关数据模型
"""

from datetime import datetime
from typing import Any, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field



class MessageResponse(BaseModel):
    """消息响应"""
    id: int
    role: str
    msg_type: str = "message"  # message, reasoning, plugin_call, plugin_call_output
    content: Any
    file_ids: List[str] | None = None  # 用户消息携带的文件ID列表
    file_paths: List[str] | None = None  # 文件在沙箱中的路径列表
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class SessionResponse(BaseModel):
    """会话列表响应（不含消息内容）"""
    id: UUID
    session_id: str
    user_id: str
    name: str | None = None  # 会话名称
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    
    model_config = ConfigDict(from_attributes=True)


class ContextInfo(BaseModel):
    """上下文使用信息"""
    estimated_tokens: int = 0  # 估算 token 数
    max_tokens: int = 200000   # 最大 token 数
    usage_percent: float = 0   # 使用百分比


class SessionDetailResponse(BaseModel):
    """会话详情响应（含消息内容）"""
    id: UUID
    session_id: str
    user_id: str
    name: str | None = None  # 会话名称
    created_at: datetime
    updated_at: datetime
    messages: List[MessageResponse] = Field(default_factory=list)
    context_info: ContextInfo | None = None  # 上下文使用信息
    
    model_config = ConfigDict(from_attributes=True)
