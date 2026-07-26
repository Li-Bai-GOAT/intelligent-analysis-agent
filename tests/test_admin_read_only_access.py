import unittest
from datetime import datetime
from types import SimpleNamespace

from app.api import knowledge, sandbox, system_prompt
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

    def test_mcp_response_keeps_full_configuration_for_administrators(self):
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
        self.assertEqual(response.environment, {"API_KEY": "super-secret"})
