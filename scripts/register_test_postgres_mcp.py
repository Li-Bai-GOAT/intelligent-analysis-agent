"""Register the local generated-data PostgreSQL MCP in the admin backend.

This is intentionally limited to the disposable Docker test source started by
``mcp_test_postgres/docker-compose.yml``.  It must never be adapted to store a
real database password or intranet connection string.
"""

import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import close_db, init_db
from app.models import SandboxMcp


TEST_MCP_NAME = "analytics_postgres_test"
TEST_CONNECTION_STRING = (
    "postgresql://dataagent_mcp_ro@host.docker.internal:55578/"
    "dataagent_mcp_test"
)


async def main() -> None:
    await init_db()
    try:
        mcp, created = await SandboxMcp.get_or_create(
            name=TEST_MCP_NAME,
            defaults={
                "mcp_type": "local",
                "command": ["postgres-mcp", "run"],
                "environment": {
                    "PGSQL_MCP_CONNECTION_STRING": TEST_CONNECTION_STRING,
                    "PGSQL_MCP_DISABLE_CWD_ACCESS": "1",
                },
                "enabled": True,
            },
        )
        if not created:
            mcp.mcp_type = "local"
            mcp.url = None
            mcp.command = ["postgres-mcp", "run"]
            mcp.headers = {}
            mcp.environment = {
                "PGSQL_MCP_CONNECTION_STRING": TEST_CONNECTION_STRING,
                "PGSQL_MCP_DISABLE_CWD_ACCESS": "1",
            }
            mcp.enabled = True
            await mcp.save()

        print(
            f"Registered {TEST_MCP_NAME} (id={mcp.id}, "
            f"created={created}, enabled={mcp.enabled}, "
            f"command={' '.join(mcp.command)}, "
            f"environment_keys={sorted(mcp.environment)})."
        )
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
