import os
import unittest
from unittest.mock import patch

from app.services.mcp_secrets import (
    McpSecretReferenceError,
    resolve_mcp_config,
    validate_mcp_secret_references,
)


class McpSecretReferenceTests(unittest.TestCase):
    def test_resolves_allowlisted_reference_without_storing_value_in_config(self):
        with patch.dict(
            os.environ,
            {
                "MCP_SECRET_REFERENCE_ALLOWLIST": "AMAP_MCP_KEY",
                "AMAP_MCP_KEY": "test-key",
            },
            clear=False,
        ):
            # Settings is cached, so replace the parsed allowlist for this unit
            # test rather than loading a developer's .env file.
            with patch("app.services.mcp_secrets._allowed_secret_names", return_value={"AMAP_MCP_KEY"}):
                config = resolve_mcp_config(
                    {"url": "https://mcp.amap.com/mcp?key={{secret:AMAP_MCP_KEY}}"}
                )
        self.assertEqual(config["url"], "https://mcp.amap.com/mcp?key=test-key")

    def test_rejects_unallowlisted_reference(self):
        with patch("app.services.mcp_secrets._allowed_secret_names", return_value=set()):
            with self.assertRaises(McpSecretReferenceError):
                resolve_mcp_config({"headers": {"Authorization": "Bearer {{secret:AMAP_MCP_KEY}}"}})

    def test_rejects_plaintext_sensitive_values(self):
        with self.assertRaises(McpSecretReferenceError):
            validate_mcp_secret_references(headers={"Authorization": "Bearer real-token"})
        with self.assertRaises(McpSecretReferenceError):
            validate_mcp_secret_references(url="https://mcp.amap.com/mcp?key=real-key")
        with self.assertRaises(McpSecretReferenceError):
            validate_mcp_secret_references(command=["server", "--api-key=real-key"])

    def test_accepts_reference_in_sensitive_values(self):
        with patch("app.services.mcp_secrets._allowed_secret_names", return_value={"AMAP_MCP_KEY"}):
            validate_mcp_secret_references(
                url="https://mcp.amap.com/mcp?key={{secret:AMAP_MCP_KEY}}"
            )


if __name__ == "__main__":
    unittest.main()
