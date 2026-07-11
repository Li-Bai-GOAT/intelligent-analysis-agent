# -*- coding: utf-8 -*-
"""
用户认证服务
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import bcrypt
import jwt

from app.config import settings
from app.models.user import User
from app.repositories.user_repo import UserRepository


class AuthService:
    """认证服务"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """密码哈希"""
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """验证密码"""
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    
    @staticmethod
    def create_token(user_id: UUID, username: str) -> str:
        """创建 JWT"""
        payload = {
            "sub": str(user_id),
            "username": username,
            "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS),
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    
    @staticmethod
    def decode_token(token: str) -> Optional[dict]:
        """解码 JWT"""
        try:
            return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        except jwt.PyJWTError:
            return None
    
    @classmethod
    async def register(cls, username: str, password: str) -> User:
        """用户注册"""
        if await UserRepository.exists(username):
            raise ValueError("用户名已存在")
        
        password_hash = cls.hash_password(password)
        return await UserRepository.create(username, password_hash)
    
    @classmethod
    async def login(cls, username: str, password: str) -> tuple[User, str]:
        """用户登录，返回 (user, token)"""
        user = await UserRepository.get_by_username(username)
        if not user or not cls.verify_password(password, user.password_hash):
            raise ValueError("用户名或密码错误")
        
        token = cls.create_token(user.id, user.username)
        return user, token
    
    @classmethod
    async def get_current_user(cls, token: str) -> Optional[User]:
        """从 token 获取当前用户"""
        payload = cls.decode_token(token)
        if not payload:
            return None
        
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        return await UserRepository.get_by_id(UUID(user_id))
