# -*- coding: utf-8 -*-
"""
API 依赖项
"""

from typing import Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.models.user import User
from app.services.auth_service import AuthService

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token: Optional[str] = Query(None),
) -> User:
    """获取当前登录用户 - 支持 Bearer header 或 query token 参数"""
    # 优先使用 Authorization header
    if credentials:
        user = await AuthService.get_current_user(credentials.credentials)
        if user:
            return user

    # 回退到 query token 参数（用于 <img>/<a> 等无法设置 header 的场景）
    if token:
        user = await AuthService.get_current_user(token)
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未提供认证令牌",
    )


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
