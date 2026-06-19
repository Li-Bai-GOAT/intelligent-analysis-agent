# -*- coding: utf-8 -*-
"""
认证 API
"""

from fastapi import APIRouter, HTTPException, status

from app.schemas.user import UserCreate, UserLogin, UserResponse, TokenResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="用户注册")
async def register(data: UserCreate):
    """创建新用户账号，用户名不可重复"""
    try:
        user = await AuthService.register(data.username, data.password)
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login", response_model=TokenResponse, summary="用户登录")
async def login(data: UserLogin):
    """验证用户名密码，返回 JWT 访问令牌"""
    try:
        user, token = await AuthService.login(data.username, data.password)
        return TokenResponse(
            access_token=token,
            user=UserResponse(
                id=user.id,
                username=user.username,
                is_admin=user.is_admin,
                created_at=user.created_at,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
