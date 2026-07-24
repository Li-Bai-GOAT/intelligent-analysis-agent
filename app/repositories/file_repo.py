# -*- coding: utf-8 -*-
"""
文件数据仓储
"""

import uuid
from typing import List, Optional

from app.models.file import UserFile, SandboxBinding


class FileRepository:
    """用户文件仓储"""
    
    @staticmethod
    async def create(
        user_id: str,
        filename: str,
        original_name: str,
        local_path: str,
        content_type: Optional[str] = None,
        size: int = 0,
        session_id: Optional[str] = None,
    ) -> UserFile:
        return await UserFile.create(
            id=uuid.uuid4(),
            user_id=user_id,
            filename=filename,
            original_name=original_name,
            local_path=local_path,
            content_type=content_type,
            size=size,
            session_id=session_id,
        )
    
    @staticmethod
    async def get(file_id: str) -> Optional[UserFile]:
        return await UserFile.filter(id=file_id).first()
    
    @staticmethod
    async def get_by_user(user_id: str, file_id: str) -> Optional[UserFile]:
        return await UserFile.filter(id=file_id, user_id=user_id).first()
    
    @staticmethod
    async def list_by_user(user_id: str) -> List[UserFile]:
        return await UserFile.filter(user_id=user_id).order_by("-created_at")
    
    @staticmethod
    async def list_by_session(user_id: str, session_id: str) -> List[UserFile]:
        return await UserFile.filter(user_id=user_id, session_id=session_id).order_by("-created_at")
    
    @staticmethod
    async def list_by_ids(user_id: str, file_ids: List[str]) -> List[UserFile]:
        return await UserFile.filter(user_id=user_id, id__in=file_ids)
    
    @staticmethod
    async def delete(user_id: str, file_id: str) -> int:
        return await UserFile.filter(id=file_id, user_id=user_id).delete()


class SandboxBindingRepository:
    """沙箱绑定仓储"""
    
    @staticmethod
    async def create(
        user_id: str,
        session_id: str,
        sandbox_id: str,
        sandbox_type: str = "data_analysis",
        workspace_path: str = "/workspace",
        mount_dir: Optional[str] = None,
    ) -> SandboxBinding:
        return await SandboxBinding.create(
            id=uuid.uuid4(),
            user_id=user_id,
            session_id=session_id,
            sandbox_id=sandbox_id,
            sandbox_type=sandbox_type,
            workspace_path=workspace_path,
            mount_dir=mount_dir,
        )
    
    @staticmethod
    async def get_by_session(session_id: str) -> Optional[SandboxBinding]:
        return await SandboxBinding.filter(session_id=session_id).first()

    @staticmethod
    async def list_active() -> List[SandboxBinding]:
        """返回仍声明占用运行时沙箱的绑定。"""
        return await SandboxBinding.filter(is_active=True).all()
    
    @staticmethod
    async def update(
        session_id: str,
        sandbox_id: Optional[str] = None,
        workspace_path: Optional[str] = None,
        mount_dir: Optional[str] = None,
        is_active: Optional[bool] = None,
        synced_file_ids: Optional[List[str]] = None,
    ) -> int:
        update_data = {}
        if sandbox_id is not None:
            update_data["sandbox_id"] = sandbox_id
        if workspace_path is not None:
            update_data["workspace_path"] = workspace_path
        if mount_dir is not None:
            update_data["mount_dir"] = mount_dir
        if is_active is not None:
            update_data["is_active"] = is_active
        if synced_file_ids is not None:
            update_data["synced_file_ids"] = synced_file_ids
        
        if update_data:
            return await SandboxBinding.filter(session_id=session_id).update(**update_data)
        return 0
    
    @staticmethod
    async def add_synced_file(session_id: str, file_id: str) -> None:
        binding = await SandboxBinding.filter(session_id=session_id).first()
        if binding:
            if file_id not in binding.synced_file_ids:
                binding.synced_file_ids.append(file_id)
                await binding.save()
    
    @staticmethod
    async def delete(session_id: str) -> int:
        return await SandboxBinding.filter(session_id=session_id).delete()
