"""Register the official AMap Streamable HTTP MCP without storing its key."""

import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import close_db, init_db
from app.models import SandboxMcp


MCP_NAME = "amap_maps"
MCP_URL = "https://mcp.amap.com/mcp?key={{secret:AMAP_MCP_KEY}}"


async def main() -> None:
    await init_db()
    try:
        mcp, created = await SandboxMcp.get_or_create(
            name=MCP_NAME,
            defaults={
                "mcp_type": "remote",
                "url": MCP_URL,
                "command": [],
                "headers": {},
                "environment": {},
                "enabled": True,
            },
        )
        if not created:
            mcp.mcp_type = "remote"
            mcp.url = MCP_URL
            mcp.command = []
            mcp.headers = {}
            mcp.environment = {}
            mcp.enabled = True
            await mcp.save()
        print(f"Registered {MCP_NAME} (id={mcp.id}, created={created}, enabled={mcp.enabled}).")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
