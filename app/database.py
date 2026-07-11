# -*- coding: utf-8 -*-
"""
数据库连接管理 (Tortoise ORM)
"""

import asyncio

from tortoise import Tortoise

from app.config import settings

_init_lock = asyncio.Lock()
_initialized = False

TORTOISE_ORM = {
    "connections": {
        "default": {
            "engine": "tortoise.backends.asyncpg",
            "credentials": {
                "host": settings.DB_HOST,
                "port": settings.DB_PORT,
                "user": settings.DB_USER,
                "password": settings.DB_PASSWORD,
                "database": settings.DB_NAME,
            },
            # 连接池配置，防止长时间等待后连接失效
            "minsize": 1,
            "maxsize": 10,
            # 连接超时时间（秒）
            "timeout": 30,
            # 命令超时时间（秒）
            "command_timeout": 60,
        },
    },
    "apps": {
        "models": {
            "models": ["app.models", "aerich.models"],
            "default_connection": "default",
        },
    },
}


async def init_db():
    """Initialize the ORM once per process without touching Tortoise internals."""
    global _initialized
    if _initialized:
        return
    async with _init_lock:
        if _initialized:
            return
        await Tortoise.init(config=TORTOISE_ORM)
        if settings.DB_AUTO_CREATE_SCHEMA:
            await Tortoise.generate_schemas(safe=True)
        _initialized = True


async def close_db():
    """关闭数据库连接"""
    global _initialized
    await Tortoise.close_connections()
    _initialized = False
