# -*- coding: utf-8 -*-
"""
数据库连接管理 (Tortoise ORM)
"""

from tortoise import Tortoise

from app.config import settings

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
    """初始化数据库连接"""
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas(safe=True)


async def close_db():
    """关闭数据库连接"""
    await Tortoise.close_connections()
