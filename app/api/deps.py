# -*- coding: utf-8 -*-
"""
API 依赖项
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.models.user import User
from app.repositories.session_repo import SessionRepository
from app.services.auth_service import AuthService

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> User:
    """获取当前登录用户"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
        )
    
    user = await AuthService.get_current_user(credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌",
        )
    
    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[User]:
    """获取当前用户（可选）"""
    if not credentials:
        return None
    return await AuthService.get_current_user(credentials.credentials)


async def get_admin_user(
    user: User = Depends(get_current_user),
) -> User:
    """获取当前管理员用户，非管理员返回 403"""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user


async def require_owned_session(
    session_id: str,
    user: User = Depends(get_current_user),
) -> User:
    """会话级接口的统一归属校验。

    FastAPI 会把路径里的 ``{session_id}`` 注入到本依赖，因此任何
    ``/{session_id}/...`` 路由只要依赖本函数，就自动获得"会话不存在或
    不属于当前用户 -> 404"的行为。

    这里统一返回 404 而不是 403：避免把接口变成"会话 ID 是否存在"的
    探测预言机（攻击者可用 403/404 的差异枚举他人的会话 ID）。
    """
    session = await SessionRepository.get(str(user.id), session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )
    return user
