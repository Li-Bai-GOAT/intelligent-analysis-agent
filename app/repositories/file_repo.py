# -*- coding: utf-8 -*-
"""
文件数据仓储
"""

import uuid
from datetime import datetime
from typing import List, Optional, Sequence

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
        status: str = "ACTIVE",
        last_activity_at: Optional[datetime] = None,
        lease_expires_at: Optional[datetime] = None,
        config_version: str = "v1",
    ) -> SandboxBinding:
        is_active = status in {"ACTIVE", "IDLE", "RELEASING"}
        return await SandboxBinding.create(
            id=uuid.uuid4(),
            user_id=user_id,
            session_id=session_id,
            sandbox_id=sandbox_id,
            sandbox_type=sandbox_type,
            workspace_path=workspace_path,
            mount_dir=mount_dir,
            status=status,
            is_active=is_active,
            last_activity_at=last_activity_at,
            lease_expires_at=lease_expires_at,
            config_version=config_version,
        )
    
    @staticmethod
    async def get_by_session(session_id: str) -> Optional[SandboxBinding]:
        return await SandboxBinding.filter(session_id=session_id).first()

    @staticmethod
    async def list_active() -> List[SandboxBinding]:
        """返回仍声明占用运行时沙箱的绑定。"""
        return await SandboxBinding.filter(
            status__in=["ACTIVE", "IDLE", "RELEASING"]
        ).all()

    @staticmethod
    async def list_by_statuses(statuses: Sequence[str]) -> List[SandboxBinding]:
        return await SandboxBinding.filter(status__in=list(statuses)).all()

    @staticmethod
    async def list_idle_oldest() -> List[SandboxBinding]:
        return await SandboxBinding.filter(status="IDLE").order_by(
            "last_activity_at", "created_at"
        )
    
    @staticmethod
    async def update(
        session_id: str,
        sandbox_id: Optional[str] = None,
        workspace_path: Optional[str] = None,
        mount_dir: Optional[str] = None,
        is_active: Optional[bool] = None,
        synced_file_ids: Optional[List[str]] = None,
        status: Optional[str] = None,
        last_activity_at: Optional[datetime] = None,
        lease_expires_at: Optional[datetime] = None,
        released_at: Optional[datetime] = None,
        release_attempts: Optional[int] = None,
        last_error: Optional[str] = None,
        runtime_seen_at: Optional[datetime] = None,
        config_version: Optional[str] = None,
        clear_lease: bool = False,
        clear_released_at: bool = False,
        clear_last_error: bool = False,
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
        if status is not None:
            update_data["status"] = status
            # Keep the temporary legacy field truthful for callers that have
            # not yet moved to the lifecycle response.
            update_data["is_active"] = status in {"ACTIVE", "IDLE", "RELEASING"}
        if last_activity_at is not None:
            update_data["last_activity_at"] = last_activity_at
        if lease_expires_at is not None:
            update_data["lease_expires_at"] = lease_expires_at
        if released_at is not None:
            update_data["released_at"] = released_at
        if release_attempts is not None:
            update_data["release_attempts"] = release_attempts
        if last_error is not None:
            update_data["last_error"] = last_error
        if runtime_seen_at is not None:
            update_data["runtime_seen_at"] = runtime_seen_at
        if config_version is not None:
            update_data["config_version"] = config_version
        if clear_lease:
            update_data["lease_expires_at"] = None
        if clear_released_at:
            update_data["released_at"] = None
        if clear_last_error:
            update_data["last_error"] = None
        
        if update_data:
            update_data["updated_at"] = datetime.now()
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
