"""Secret-reference handling for MCP configuration.

MCP metadata is stored in PostgreSQL and is visible to administrators.  It
must therefore contain references, not provider keys or database passwords.
Values of the form ``{{secret:NAME}}`` are resolved only while a sandbox
configuration is written to its ephemeral container filesystem.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

from dotenv import dotenv_values

from app.config import settings


SECRET_REFERENCE_PATTERN = re.compile(r"\{\{secret:([A-Z][A-Z0-9_]{0,127})\}\}")
SENSITIVE_NAME_PATTERN = re.compile(r"(?:api[_-]?key|token|secret|password|credential|authorization|dsn|connection)", re.IGNORECASE)


class McpSecretReferenceError(ValueError):
    """Raised when an MCP secret reference cannot safely be resolved."""


def extract_secret_references(value: str) -> set[str]:
    return set(SECRET_REFERENCE_PATTERN.findall(value))


def is_secret_reference(value: str) -> bool:
    return bool(SECRET_REFERENCE_PATTERN.search(value))


def _allowed_secret_names() -> set[str]:
    return set(settings.mcp_secret_reference_allowlist)


def _dotenv_secret_values() -> Mapping[str, str | None]:
    project_root = Path(__file__).resolve().parents[2]
    return dotenv_values(project_root / ".env")


def resolve_secret_references(
    value: str,
    *,
    environment: Mapping[str, str] | None = None,
    dotenv_values_override: Mapping[str, str | None] | None = None,
) -> str:
    """Resolve approved references without ever logging the resolved value."""
    references = extract_secret_references(value)
    if not references:
        return value

    allowed = _allowed_secret_names()
    source_environment = environment if environment is not None else os.environ
    source_dotenv = dotenv_values_override if dotenv_values_override is not None else _dotenv_secret_values()

    def replace(match: re.Match[str]) -> str:
        secret_name = match.group(1)
        if secret_name not in allowed:
            raise McpSecretReferenceError(
                f"MCP secret reference '{secret_name}' is not allowlisted."
            )
        secret_value = source_environment.get(secret_name) or source_dotenv.get(secret_name)
        if not secret_value:
            raise McpSecretReferenceError(
                f"MCP secret reference '{secret_name}' is not configured."
            )
        return str(secret_value)

    return SECRET_REFERENCE_PATTERN.sub(replace, value)


def resolve_mcp_config(value: Any) -> Any:
    """Recursively resolve secret references in one MCP config dictionary."""
    if isinstance(value, str):
        return resolve_secret_references(value)
    if isinstance(value, list):
        return [resolve_mcp_config(item) for item in value]
    if isinstance(value, dict):
        return {key: resolve_mcp_config(item) for key, item in value.items()}
    return value


def validate_mcp_secret_references(
    *,
    url: str | None = None,
    command: list[Any] | None = None,
    headers: Mapping[str, str] | None = None,
    environment: Mapping[str, str] | None = None,
) -> None:
    """Reject plaintext values in conventional secret-bearing configuration fields."""
    def validate_value(field_name: str, value: str) -> None:
        for reference in extract_secret_references(value):
            if reference not in _allowed_secret_names():
                raise McpSecretReferenceError(
                    f"MCP secret reference '{reference}' is not allowlisted."
                )

        if SENSITIVE_NAME_PATTERN.search(field_name) and value and not is_secret_reference(value):
            raise McpSecretReferenceError(
                f"{field_name} must use a {{\u007bsecret:NAME\u007d}} reference instead of a plaintext secret."
            )

    if url:
        query = url.split("?", 1)[1] if "?" in url else ""
        for pair in query.split("&"):
            key, separator, value = pair.partition("=")
            if separator:
                # ``key`` is the conventional parameter name used by several
                # providers, including AMap.  It is too broad to classify every
                # configuration field named "key" as a secret, but is always
                # sensitive in a remote MCP URL query string.
                query_field = "api_key" if key.lower() in {
                    "key",
                    "api_key",
                    "apikey",
                    "access_token",
                    "token",
                    "secret",
                } else key
                validate_value(query_field, value)
        for reference in extract_secret_references(url):
            if reference not in _allowed_secret_names():
                raise McpSecretReferenceError(
                    f"MCP secret reference '{reference}' is not allowlisted."
                )

    for key, value in (headers or {}).items():
        validate_value(str(key), str(value))
    for key, value in (environment or {}).items():
        validate_value(str(key), str(value))

    for argument in command or []:
        text = str(argument)
        option, separator, option_value = text.partition("=")
        if separator:
            validate_value(option, option_value)
