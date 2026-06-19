# -*- coding: utf-8 -*-
"""
文件相关数据模型
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    """文件上传响应"""
    id: UUID
    filename: str
    original_name: str
    content_type: Optional[str]
    size: int
    created_at: datetime


class FileListResponse(BaseModel):
    """文件列表响应"""
    id: UUID
    filename: str
    original_name: str
    content_type: Optional[str]
    size: int
    session_id: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class SandboxFileItem(BaseModel):
    """沙箱文件项"""
    name: str
    path: str
    type: str  # "file" or "directory"
    size: Optional[int] = None
    modified: Optional[str] = None
    children: Optional[List["SandboxFileItem"]] = None


class SandboxBindingResponse(BaseModel):
    """沙箱绑定响应"""
    id: UUID
    session_id: str
    sandbox_id: str
    workspace_path: str
    is_active: bool
    synced_file_ids: List[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class SyncFilesRequest(BaseModel):
    """同步文件请求"""
    file_ids: List[str]


class SyncFilesResponse(BaseModel):
    """同步文件响应"""
    success: bool
    synced_count: int
    sandbox_paths: List[str]
    message: str
