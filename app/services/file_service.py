# -*- coding: utf-8 -*-
"""
文件服务

处理文件上传、列表等
"""

import os
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any

from app.repositories.file_repo import FileRepository, SandboxBindingRepository
from app.models.file import UserFile, SandboxBinding


# 用户上传文件目录（与沙箱挂载目录分开，避免混乱）
USER_UPLOADS_DIR = Path("user_uploads")
USER_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


class FileService:
    """文件服务"""
    
    @staticmethod
    async def save_uploaded_file(
        user_id: str,
        file_content: bytes,
        original_name: str,
        content_type: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> UserFile:
        """
        保存上传的文件
        
        文件保存到 user_uploads/{session_id}/ 目录，
        对话时会自动复制到沙箱的挂载目录。
        """
        if not session_id:
            raise ValueError("session_id 为必填项，请先创建会话")
        
        # 会话上传目录
        session_dir = USER_UPLOADS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用原始文件名，同名文件添加后缀
        local_path = session_dir / original_name
        if local_path.exists():
            file_ext = Path(original_name).suffix
            file_stem = Path(original_name).stem
            unique_suffix = uuid.uuid4().hex[:8]
            local_path = session_dir / f"{file_stem}_{unique_suffix}{file_ext}"
        
        # 保存文件
        local_path.write_bytes(file_content)
        
        # 创建数据库记录
        return await FileRepository.create(
            user_id=user_id,
            filename=local_path.name,
            original_name=original_name,
            local_path=str(local_path),
            content_type=content_type,
            size=len(file_content),
            session_id=session_id,
        )
    
    @staticmethod
    async def get_file(user_id: str, file_id: str) -> Optional[UserFile]:
        """获取用户文件"""
        return await FileRepository.get_by_user(user_id, file_id)
    
    @staticmethod
    async def list_files(user_id: str, session_id: Optional[str] = None) -> List[UserFile]:
        """列出用户文件"""
        if session_id:
            return await FileRepository.list_by_session(user_id, session_id)
        return await FileRepository.list_by_user(user_id)
    
    @staticmethod
    async def delete_file(user_id: str, file_id: str) -> bool:
        """删除文件"""
        file = await FileRepository.get_by_user(user_id, file_id)
        if file:
            # 删除本地文件
            if os.path.exists(file.local_path):
                os.remove(file.local_path)
            # 删除数据库记录
            await FileRepository.delete(user_id, file_id)
            return True
        return False


class SandboxFileService:
    """沙箱文件服务"""
    
    def __init__(self, sandbox_service):
        self.sandbox_service = sandbox_service
    
    async def get_or_create_binding(
        self,
        user_id: str,
        session_id: str,
        sandbox_id: str,
        workspace_path: str = "/workspace",
    ) -> SandboxBinding:
        """获取或创建沙箱绑定"""
        binding = await SandboxBindingRepository.get_by_session(session_id)
        if binding:
            if binding.sandbox_id != sandbox_id:
                await SandboxBindingRepository.update(
                    session_id=session_id,
                    sandbox_id=sandbox_id,
                    workspace_path=workspace_path,
                    is_active=True,
                )
                binding = await SandboxBindingRepository.get_by_session(session_id)
        else:
            binding = await SandboxBindingRepository.create(
                user_id=user_id,
                session_id=session_id,
                sandbox_id=sandbox_id,
                workspace_path=workspace_path,
            )
        return binding
    
    async def list_uploaded_files(self, session_id: str) -> List[Dict[str, Any]]:
        """列出用户上传的文件"""
        local_base = USER_UPLOADS_DIR / session_id
        if not local_base.exists():
            return []
        
        files = []
        for item in local_base.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(local_base)
                files.append({
                    "name": item.name,
                    "path": f"/workspace/{rel_path}",
                    "size": item.stat().st_size,
                    "type": "file",
                })
        return files
    
    async def download_uploaded_file(self, session_id: str, filename: str) -> Optional[bytes]:
        """下载用户上传的文件"""
        local_path = USER_UPLOADS_DIR / session_id / filename
        try:
            if local_path.exists() and local_path.is_file():
                return local_path.read_bytes()
            return None
        except Exception:
            return None
    
