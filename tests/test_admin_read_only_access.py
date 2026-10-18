import unittest
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.api import knowledge, model_audits, sandbox, system_prompt
from app.api.deps import get_admin_user, get_current_user


def _route_dependency(router, path: str, method: str):
    full_path = f"{router.prefix}{path}"
    route = next(
        route
        for route in router.routes
        if route.path == full_path and method in route.methods
    )
    return route.dependant.dependencies[0].call


class AdminReadOnlyAccessTests(unittest.TestCase):
    def test_shared_read_routes_require_login_not_administrator(self):
        routes = [
            (knowledge.router, "", "GET"),
            (knowledge.router, "/{item_id}", "GET"),
            (system_prompt.router, "", "GET"),
            (sandbox.router, "/skills", "GET"),
            (sandbox.router, "/skills/{skill_id}", "GET"),
            (sandbox.router, "/skills/{skill_id}/files", "GET"),
            (sandbox.router, "/skills/{skill_id}/files/{file_path:path}", "GET"),
            (sandbox.router, "/mcps", "GET"),
            (sandbox.router, "/mcps/{mcp_id}", "GET"),
        ]

        for router, path, method in routes:
            with self.subTest(path=path):
                self.assertIs(_route_dependency(router, path, method), get_current_user)

    def test_shared_write_routes_remain_administrator_only(self):
        routes = [
            (knowledge.router, "", "POST"),
            (knowledge.router, "/{item_id}", "PUT"),
            (knowledge.router, "/{item_id}", "DELETE"),
            (system_prompt.router, "", "PUT"),
            (sandbox.router, "/skills/upload", "POST"),
            (sandbox.router, "/skills/{skill_id}/toggle", "PATCH"),
            (sandbox.router, "/skills/{skill_id}", "DELETE"),
            (sandbox.router, "/mcps", "POST"),
            (sandbox.router, "/mcps/{mcp_id}", "PUT"),
            (sandbox.router, "/mcps/{mcp_id}", "DELETE"),
            (sandbox.router, "/agents", "GET"),
            (sandbox.router, "/agents/names", "GET"),
        ]

        for router, path, method in routes:
            with self.subTest(path=path, method=method):
                self.assertIs(_route_dependency(router, path, method), get_admin_user)

    def test_model_audit_route_requires_administrator(self):
        self.assertIs(_route_dependency(model_audits.router, "/model-audits", "GET"), get_admin_user)

    def test_model_audit_query_forwards_filters_and_pagination(self):
        async def scenario():
            with patch(
                "app.api.model_audits.read_audits",
                return_value=([{"request_id": "req-1"}], 1),
            ) as read_mock:
                response = await model_audits.list_model_audits(
                    start_time=None,
                    end_time=None,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    source=None,
                    session_id=None,
                    task_id="task-1",
                    request_id=None,
                    result=None,
                    limit=25,
                    offset=50,
                    _admin=SimpleNamespace(is_admin=True),
                )
            self.assertEqual(response, {"items": [{"request_id": "req-1"}], "total": 1, "limit": 25, "offset": 50})
            read_mock.assert_called_once_with(
                {
                    "start_time": None,
                    "end_time": None,
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "source": None,
                    "session_id": None,
                    "parent_task_id": "task-1",
                    "request_id": None,
                    "result": None,
                },
                limit=25,
                offset=50,
            )

        asyncio.run(scenario())

    def test_mcp_response_masks_values_for_normal_users(self):
        now = datetime.now()
        mcp = SimpleNamespace(
            id=1,
            name="private-remote",
            mcp_type="remote",
            url="https://alice:secret@example.com/mcp?token=super-secret",
            command=["npx", "--token=super-secret", "server"],
            headers={"Authorization": "Bearer super-secret"},
            environment={"API_KEY": "super-secret"},
            enabled=True,
            created_at=now,
            updated_at=now,
        )

        response = sandbox._mcp_to_response(mcp, reveal_secrets=False)

        self.assertNotIn("super-secret", response.url or "")
        self.assertNotIn("alice", response.url or "")
        self.assertEqual(response.headers, {"Authorization": "***"})
        self.assertEqual(response.environment, {"API_KEY": "***"})
        self.assertEqual(response.command, ["npx", "--token=***", "***"])

    def test_mcp_response_masks_legacy_plaintext_secrets_for_administrators(self):
        now = datetime.now()
        mcp = SimpleNamespace(
            id=1,
            name="private-local",
            mcp_type="local",
            url=None,
            command=["npx", "server"],
            headers={},
            environment={"API_KEY": "super-secret"},
            enabled=True,
            created_at=now,
            updated_at=now,
        )

        response = sandbox._mcp_to_response(mcp, reveal_secrets=True)

        self.assertEqual(response.command, ["npx", "server"])
        self.assertEqual(response.environment, {"API_KEY": "***"})

    def test_mcp_response_keeps_secret_references_visible_for_administrators(self):
        now = datetime.now()
        mcp = SimpleNamespace(
            id=1,
            name="referenced-remote",
            mcp_type="remote",
            url="https://mcp.example.com/mcp?key={{secret:AMAP_MCP_KEY}}",
            command=[],
            headers={},
            environment={},
            enabled=True,
            created_at=now,
            updated_at=now,
        )

        response = sandbox._mcp_to_response(mcp, reveal_secrets=True)

        self.assertIn("{{secret:AMAP_MCP_KEY}}", response.url or "")
