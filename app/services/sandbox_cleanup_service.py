# -*- coding: utf-8 -*-
"""Backward-compatible import surface for the persistent lifecycle service.

New code must use :mod:`sandbox_lifecycle_service`. Keeping this thin module
avoids breaking integrations that imported the old cleanup service while
ensuring they no longer get an in-memory source of truth.
"""

from app.services.sandbox_lifecycle_service import (
    SandboxLifecycleService,
    get_lifecycle_service,
)


class SandboxCleanupService(SandboxLifecycleService):
    """Deprecated name retained for source compatibility."""


def get_cleanup_service(
    idle_timeout_seconds: int = 7200,
    scan_interval_seconds: int = 300,
) -> SandboxLifecycleService:
    # Runtime configuration is intentionally centralised in Settings. Legacy
    # arguments are accepted so old callers can upgrade without a crash.
    return get_lifecycle_service()


__all__ = ["SandboxCleanupService", "get_cleanup_service"]
