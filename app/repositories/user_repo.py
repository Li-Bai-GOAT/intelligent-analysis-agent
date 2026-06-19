# -*- coding: utf-8 -*-
"""
用户数据访问层
"""

from typing import Optional
from uuid import UUID

from app.models.user import User


class UserRepository:
    """用户数据访问"""
    
    @staticmethod
    async def create(username: str, password_hash: str) -> User:
        return await User.create(username=username, password_hash=password_hash)
    
    @staticmethod
    async def get_by_id(user_id: UUID) -> Optional[User]:
        return await User.filter(id=user_id).first()
    
    @staticmethod
    async def get_by_username(username: str) -> Optional[User]:
        return await User.filter(username=username).first()
    
    @staticmethod
    async def exists(username: str) -> bool:
        return await User.filter(username=username).exists()
