# -*- coding: utf-8 -*-
"""
数据库连接管理 (Tortoise ORM)
"""

import asyncio
import logging
from pathlib import Path

from aerich.models import Aerich
from tortoise import Tortoise
from tortoise.exceptions import OperationalError

from app.config import settings

_init_lock = asyncio.Lock()
_initialized = False
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "models"


def expected_migration_versions() -> list[str]:
    """Return repository migration filenames in Aerich execution order."""
    return [
        path.name
        for path in sorted(
            MIGRATIONS_DIR.glob("[0-9]*_*.py"),
            key=lambda path: int(path.name.split("_", 1)[0]),
        )
    ]


async def verify_migration_state() -> None:
    """Fail startup when the database is not at the repository migration head."""
    expected = expected_migration_versions()
    if not expected:
        raise RuntimeError("No Aerich migrations found; refusing to start without a schema baseline")
    try:
        applied = set(await Aerich.filter(app="models").values_list("version", flat=True))
    except OperationalError as exc:
        raise RuntimeError(
            "Database has no Aerich baseline. Run: python scripts/db_maintenance.py migrate"
        ) from exc

    missing = [version for version in expected if version not in applied]
    if missing:
        raise RuntimeError(
            "Database migrations are pending: "
            + ", ".join(missing)
            + ". Run: python scripts/db_maintenance.py migrate"
        )

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
            logger.warning(
                "DB_AUTO_CREATE_SCHEMA is enabled; use this only for a disposable development database"
            )
            await Tortoise.generate_schemas(safe=True)
        else:
            await verify_migration_state()
        _initialized = True


async def close_db():
    """关闭数据库连接"""
    global _initialized
    await Tortoise.close_connections()
    _initialized = False
