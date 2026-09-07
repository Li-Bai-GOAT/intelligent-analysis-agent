# -*- coding: utf-8 -*-
"""Persistent lifecycle management for session-bound data sandboxes.

PostgreSQL is the source of truth for a sandbox binding.  The Runtime and
Redis are deliberately treated as operational dependencies: a temporary
failure in either must not turn a live binding into an orphan or make an
untracked container look released.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlsplit, urlunsplit

import redis.asyncio as aioredis

from app.config import settings
from app.models.file import SandboxBinding
from app.repositories.file_repo import SandboxBindingRepository

logger = logging.getLogger(__name__)


class SandboxStatus(StrEnum):
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    RELEASING = "RELEASING"
    RELEASED = "RELEASED"
    # ORPHANED is retained in addition to the five externally documented
    # states. It distinguishes a missing runtime from a verified release and
    # lets the next acquire preserve and migrate the workspace safely.
    ORPHANED = "ORPHANED"
    FAILED = "FAILED"


RUNTIME_OWNING_STATUSES = {
    SandboxStatus.ACTIVE,
    SandboxStatus.IDLE,
    SandboxStatus.RELEASING,
}


class SandboxLifecycleError(RuntimeError):
    """Base error returned to callers without Runtime implementation detail."""


class SandboxCapacityError(SandboxLifecycleError):
    """The configured hard Runtime container limit cannot admit another task."""


class SandboxUnavailableError(SandboxLifecycleError):
    """The Runtime state cannot be verified safely at this time."""


@dataclass(slots=True)
class SandboxAcquireResult:
    sandbox: Any
    binding: SandboxBinding
    recreated: bool
    config_mismatch: bool
    previous_sandbox_id: Optional[str]
    previous_mount_dir: Optional[str]


@dataclass(frozen=True, slots=True)
class RuntimePoolSnapshot:
    """Identity set for the Runtime manager's current prewarmed pool."""

    identities: frozenset[str]
    member_count: int


_SECRET_VALUE = re.compile(
    r"(?i)(bearer\s+|api[_-]?key[=:]\s*|token[=:]\s*|password[=:]\s*)([^\s,;]+)"
)
_MAX_ERROR_LENGTH = 500
_MISSING_RUNTIME_MARKERS = (
    "not found",
    "no container",
    "does not exist",
    "404",
)


def _utcnow() -> datetime:
    """Use one naive UTC representation compatible with existing ORM data."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc_naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _safe_error(error: BaseException | str) -> str:
    """Keep a useful release error without persisting credential material."""
    text = str(error).replace("\n", " ").strip()
    text = _SECRET_VALUE.sub(r"\1***", text)
    return text[:_MAX_ERROR_LENGTH] or "Sandbox runtime operation failed"


def _is_missing_runtime_error(detail: str) -> bool:
    return any(marker in detail.lower() for marker in _MISSING_RUNTIME_MARKERS)


class SandboxLifecycleService:
    """Coordinates acquire, task leases, release retries and reconciliation."""

    def __init__(
        self,
        *,
        idle_timeout_seconds: int | None = None,
        lease_seconds: int | None = None,
        scan_interval_seconds: int | None = None,
        max_active_containers: int | None = None,
        max_release_attempts: int | None = None,
        orphan_grace_seconds: int | None = None,
        auto_release_orphans: bool | None = None,
        manager_redis_url: str | None = None,
        manager_redis_db: int | None = None,
        manager_pool_key: str | None = None,
        manager_pool_size: int | None = None,
        config_version: str | None = None,
    ) -> None:
        self.idle_timeout = timedelta(
            seconds=idle_timeout_seconds or settings.SANDBOX_IDLE_TIMEOUT_SECONDS
        )
        self.lease_duration = timedelta(
            seconds=lease_seconds or settings.SANDBOX_LEASE_SECONDS
        )
        self.scan_interval_seconds = (
            scan_interval_seconds or settings.SANDBOX_CLEANUP_INTERVAL_SECONDS
        )
        self.max_active_containers = (
            max_active_containers or settings.SANDBOX_MAX_ACTIVE_CONTAINERS
        )
        self.max_release_attempts = (
            max_release_attempts or settings.SANDBOX_MAX_RELEASE_ATTEMPTS
        )
        self.orphan_grace = timedelta(
            seconds=orphan_grace_seconds or settings.SANDBOX_ORPHAN_GRACE_SECONDS
        )
        self.auto_release_orphans = (
            settings.SANDBOX_AUTO_RELEASE_ORPHANS
            if auto_release_orphans is None
            else auto_release_orphans
        )
        self.manager_redis_url = (
            settings.SANDBOX_MANAGER_REDIS_URL
            if manager_redis_url is None
            else manager_redis_url
        )
        self.manager_redis_db = (
            settings.SANDBOX_MANAGER_REDIS_DB
            if manager_redis_db is None
            else manager_redis_db
        )
        self.manager_pool_key = (
            settings.SANDBOX_MANAGER_POOL_KEY
            if manager_pool_key is None
            else manager_pool_key
        )
        self.manager_pool_size = (
            settings.SANDBOX_MANAGER_POOL_SIZE
            if manager_pool_size is None
            else manager_pool_size
        )
        self.config_version = config_version or settings.SANDBOX_CONFIG_VERSION
        self.sandbox_service: Any = None
        self.redis: Any = None
        self._manager_pool_redis: Any = None
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._local_locks: dict[str, asyncio.Lock] = {}

    def configure(self, sandbox_service: Any, redis_client: Any = None) -> None:
        """Attach process-local operational dependencies after service startup."""
        self.sandbox_service = sandbox_service
        self.redis = redis_client

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Startup recovery intentionally relies on persisted bindings; it does
        # not reconstruct liveness from this process's memory.
        await self.reconcile(read_only=not self.auto_release_orphans)
        self._task = asyncio.create_task(self._reconcile_loop())
        logger.info(
            "Sandbox lifecycle service started: idle_timeout=%s lease=%s scan=%ss",
            self.idle_timeout,
            self.lease_duration,
            self.scan_interval_seconds,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._manager_pool_redis is not None:
            try:
                await self._manager_pool_redis.aclose()
            except Exception as error:
                logger.warning(
                    "Failed to close Runtime pool Redis client: %s",
                    _safe_error(error),
                )
            finally:
                self._manager_pool_redis = None

    async def _reconcile_loop(self) -> None:
        while self._running:
            try:
                await self.reconcile(read_only=not self.auto_release_orphans)
            except Exception:
                logger.exception("Sandbox lifecycle reconciliation failed")
            await asyncio.sleep(self.scan_interval_seconds)

    @asynccontextmanager
    async def _session_guard(self, session_id: str) -> AsyncIterator[None]:
        """Serialize acquire/release per session across workers when Redis works.

        The local lock is always useful. Redis is best effort because it is
        not business state; if it is unavailable, the unique database binding
        still prevents a second durable binding and Runtime verification stays
        conservative.
        """
        lock = self._local_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            token: Optional[str] = None
            key = f"sandbox_lifecycle_lock:{session_id}"
            if self.redis is not None:
                candidate = uuid.uuid4().hex
                try:
                    for _ in range(60):
                        if await self.redis.set(key, candidate, nx=True, ex=60):
                            token = candidate
                            break
                        await asyncio.sleep(0.1)
                    if token is None:
                        raise SandboxUnavailableError("Sandbox lifecycle lock is busy")
                except SandboxLifecycleError:
                    raise
                except Exception as error:
                    # Do not fail open into an unsafe release; the database and
                    # Runtime checks below remain the durable protection.
                    logger.warning("Sandbox distributed lock unavailable: %s", _safe_error(error))
            try:
                yield
            finally:
                if token is not None and self.redis is not None:
                    try:
                        if await self.redis.get(key) == token:
                            await self.redis.delete(key)
                    except Exception:
                        logger.warning("Failed to release sandbox lifecycle lock")

    async def acquire(self, session_id: str, user_id: str) -> SandboxAcquireResult:
        """Acquire exactly one verified sandbox and persist its active lease."""
        self._require_runtime()
        async with self._session_guard(session_id):
            now = _utcnow()
            binding = await SandboxBindingRepository.get_by_session(session_id)
            if binding and str(binding.user_id) != str(user_id):
                raise SandboxLifecycleError("Sandbox binding belongs to another user")

            old_sandbox_id = binding.sandbox_id if binding else None
            old_mount_dir = binding.mount_dir if binding else None
            old_status = SandboxStatus(binding.status) if binding else None
            config_mismatch = bool(
                binding and binding.config_version != self.config_version
            )

            if binding and old_status in {SandboxStatus.ACTIVE, SandboxStatus.IDLE}:
                verified = await self._verify_runtime(binding.sandbox_id)
                if verified is True:
                    sandboxes = await asyncio.to_thread(
                        self.sandbox_service.connect,
                        session_id,
                        str(user_id),
                        ["data_analysis"],
                    )
                    if sandboxes:
                        sandbox = sandboxes[0]
                        mount_dir = await self._get_mount_dir(sandbox) or binding.mount_dir
                        await SandboxBindingRepository.update(
                            session_id,
                            sandbox_id=sandbox.sandbox_id,
                            mount_dir=mount_dir,
                            status=SandboxStatus.ACTIVE,
                            last_activity_at=now,
                            lease_expires_at=now + self.lease_duration,
                            runtime_seen_at=now,
                            clear_last_error=True,
                            clear_released_at=True,
                        )
                        refreshed = await SandboxBindingRepository.get_by_session(session_id)
                        assert refreshed is not None
                        return SandboxAcquireResult(
                            sandbox=sandbox,
                            binding=refreshed,
                            recreated=sandbox.sandbox_id != old_sandbox_id,
                            config_mismatch=config_mismatch,
                            previous_sandbox_id=old_sandbox_id,
                            previous_mount_dir=old_mount_dir,
                        )
                    verified = False

                if verified is False:
                    await SandboxBindingRepository.update(
                        session_id,
                        status=SandboxStatus.ORPHANED,
                        clear_lease=True,
                        last_error="Runtime sandbox is no longer reachable",
                    )
                    # Remove a stale Runtime mapping before creating a
                    # replacement. Release is idempotent in AgentScope.
                    await self._detach_stale_runtime(session_id, str(user_id))
                else:
                    raise SandboxUnavailableError(
                        "Sandbox runtime cannot be verified; retry shortly"
                    )
            elif binding and old_status is SandboxStatus.RELEASING:
                raise SandboxUnavailableError("Sandbox is being released")
            elif binding and old_status is SandboxStatus.FAILED:
                raise SandboxUnavailableError(
                    "Sandbox release failed and requires administrator retry"
                )
            elif binding and old_status is SandboxStatus.ORPHANED:
                await self._detach_stale_runtime(session_id, str(user_id))

            await self._ensure_capacity(session_id)
            sandboxes = await asyncio.to_thread(
                self.sandbox_service.connect,
                session_id,
                str(user_id),
                ["data_analysis"],
            )
            if not sandboxes:
                raise SandboxUnavailableError("Sandbox Runtime did not return a container")
            sandbox = sandboxes[0]
            mount_dir = await self._get_mount_dir(sandbox)
            if binding is None:
                try:
                    binding = await SandboxBindingRepository.create(
                        user_id=str(user_id),
                        session_id=session_id,
                        sandbox_id=sandbox.sandbox_id,
                        mount_dir=mount_dir,
                        status=SandboxStatus.ACTIVE,
                        last_activity_at=now,
                        lease_expires_at=now + self.lease_duration,
                        config_version=self.config_version,
                    )
                except Exception:
                    # A concurrent process may have won the unique session id
                    # race while Runtime was creating. Never silently retain a
                    # duplicate unbound container.
                    await self._detach_stale_runtime(session_id, str(user_id))
                    raise
            else:
                await SandboxBindingRepository.update(
                    session_id,
                    sandbox_id=sandbox.sandbox_id,
                    mount_dir=mount_dir,
                    status=SandboxStatus.ACTIVE,
                    last_activity_at=now,
                    lease_expires_at=now + self.lease_duration,
                    runtime_seen_at=now,
                    release_attempts=0,
                    config_version=self.config_version,
                    clear_last_error=True,
                    clear_released_at=True,
                )
                binding = await SandboxBindingRepository.get_by_session(session_id)
                assert binding is not None

            return SandboxAcquireResult(
                sandbox=sandbox,
                binding=binding,
                recreated=bool(old_sandbox_id and old_sandbox_id != sandbox.sandbox_id),
                config_mismatch=config_mismatch,
                previous_sandbox_id=old_sandbox_id,
                previous_mount_dir=old_mount_dir,
            )

    async def heartbeat(self, session_id: str) -> None:
        """Renew an active task lease without depending on Redis persistence."""
        now = _utcnow()
        await SandboxBindingRepository.update(
            session_id,
            status=SandboxStatus.ACTIVE,
            last_activity_at=now,
            lease_expires_at=now + self.lease_duration,
        )

    async def mark_idle(self, session_id: str) -> None:
        """Close a task lease and start durable idle timeout accounting."""
        binding = await SandboxBindingRepository.get_by_session(session_id)
        if not binding or binding.status not in {
            SandboxStatus.ACTIVE,
            SandboxStatus.IDLE,
        }:
            return
        await SandboxBindingRepository.update(
            session_id,
            status=SandboxStatus.IDLE,
            last_activity_at=_utcnow(),
            clear_lease=True,
        )

    async def record_configuration(self, session_id: str, success: bool) -> None:
        """Only claim a config version after injection has completed."""
        if success:
            await SandboxBindingRepository.update(
                session_id,
                config_version=self.config_version,
            )

    async def release(
        self,
        session_id: str,
        *,
        reason: str,
        force: bool = False,
        retry_failed: bool = False,
    ) -> Optional[SandboxBinding]:
        """Idempotently release one binding using the two-phase DB protocol."""
        self._require_runtime()
        async with self._session_guard(session_id):
            binding = await SandboxBindingRepository.get_by_session(session_id)
            if binding is None or binding.status == SandboxStatus.RELEASED:
                return binding
            if binding.status == SandboxStatus.FAILED and not retry_failed:
                return binding
            if not force and await self._has_active_task(session_id):
                raise SandboxUnavailableError("Sandbox still has an active task")
            if binding.status == SandboxStatus.FAILED and retry_failed:
                await SandboxBindingRepository.update(
                    session_id,
                    status=SandboxStatus.RELEASING,
                    release_attempts=0,
                    clear_last_error=True,
                )
                binding = await SandboxBindingRepository.get_by_session(session_id)
                assert binding is not None
            if binding.status != SandboxStatus.RELEASING:
                await SandboxBindingRepository.update(
                    session_id,
                    status=SandboxStatus.RELEASING,
                    clear_lease=True,
                )
                binding = await SandboxBindingRepository.get_by_session(session_id)
                assert binding is not None

            return await self._release_bound_runtime(binding, reason)

    async def _release_bound_runtime(
        self,
        binding: SandboxBinding,
        reason: str,
    ) -> SandboxBinding:
        session_id = binding.session_id
        try:
            result = await asyncio.to_thread(
                self.sandbox_service.release,
                session_id,
                str(binding.user_id),
            )
            if result is False:
                raise RuntimeError("Runtime rejected sandbox release")
            registered = await self._runtime_registration_exists(binding.sandbox_id)
            if registered is not False:
                raise RuntimeError("Runtime container remains registered after release")
        except Exception as error:
            attempts = binding.release_attempts + 1
            status = (
                SandboxStatus.FAILED
                if attempts >= self.max_release_attempts
                else SandboxStatus.RELEASING
            )
            await SandboxBindingRepository.update(
                session_id,
                status=status,
                release_attempts=attempts,
                last_error=_safe_error(error),
                clear_lease=True,
            )
            updated = await SandboxBindingRepository.get_by_session(session_id)
            assert updated is not None
            logger.warning(
                "Sandbox release failed: session=%s sandbox=%s reason=%s attempts=%s",
                session_id,
                binding.sandbox_id,
                reason,
                attempts,
            )
            return updated

        now = _utcnow()
        await SandboxBindingRepository.update(
            session_id,
            status=SandboxStatus.RELEASED,
            released_at=now,
            release_attempts=binding.release_attempts,
            runtime_seen_at=now,
            clear_lease=True,
            clear_last_error=True,
        )
        updated = await SandboxBindingRepository.get_by_session(session_id)
        assert updated is not None
        logger.info(
            "Sandbox released: session=%s sandbox=%s reason=%s",
            session_id,
            binding.sandbox_id,
            reason,
        )
        return updated

    async def reconcile(
        self,
        *,
        read_only: bool = True,
        force_orphan_release: bool = False,
    ) -> dict[str, int]:
        """Recover persisted facts, retry releases, and inspect safe orphan candidates."""
        summary = {
            "checked": 0,
            "orphaned_bindings": 0,
            "released": 0,
            "failed": 0,
            "orphan_candidates": 0,
            "orphan_released": 0,
            "orphan_pool_members": 0,
            "orphan_pool_excess": 0,
        }
        if self.sandbox_service is None:
            logger.warning("Sandbox lifecycle reconciliation skipped: Runtime is unavailable")
            return summary

        bindings = await SandboxBindingRepository.list_by_statuses(
            [
                SandboxStatus.ACTIVE,
                SandboxStatus.IDLE,
                SandboxStatus.RELEASING,
                SandboxStatus.FAILED,
            ]
        )
        now = _utcnow()
        for binding in bindings:
            summary["checked"] += 1
            status = SandboxStatus(binding.status)
            if status in {SandboxStatus.ACTIVE, SandboxStatus.IDLE}:
                verified = await self._verify_runtime(binding.sandbox_id)
                if verified is False:
                    await SandboxBindingRepository.update(
                        binding.session_id,
                        status=SandboxStatus.ORPHANED,
                        clear_lease=True,
                        last_error="Runtime sandbox is no longer reachable",
                    )
                    summary["orphaned_bindings"] += 1
                    continue
                if verified is None:
                    # Runtime ambiguity is never evidence of an orphan.
                    continue

                await SandboxBindingRepository.update(
                    binding.session_id,
                    runtime_seen_at=now,
                )
                expired_lease = (
                    status is SandboxStatus.ACTIVE
                    and binding.lease_expires_at is not None
                    and _as_utc_naive(binding.lease_expires_at) <= now
                )
                last_activity = _as_utc_naive(binding.last_activity_at) or _as_utc_naive(
                    binding.updated_at
                )
                idle_expired = (
                    status is SandboxStatus.IDLE
                    and last_activity is not None
                    and now - last_activity >= self.idle_timeout
                )
                if (expired_lease or idle_expired) and not await self._has_active_task(
                    binding.session_id
                ):
                    released = await self.release(
                        binding.session_id,
                        reason="lease_expired" if expired_lease else "idle_timeout",
                    )
                    if released and released.status == SandboxStatus.RELEASED:
                        summary["released"] += 1
                    elif released and released.status == SandboxStatus.FAILED:
                        summary["failed"] += 1
            elif status is SandboxStatus.RELEASING and self._release_retry_due(binding, now):
                if not await self._has_active_task(binding.session_id):
                    released = await self.release(
                        binding.session_id,
                        reason="retry",
                        retry_failed=False,
                    )
                    if released and released.status == SandboxStatus.RELEASED:
                        summary["released"] += 1
                    elif released and released.status == SandboxStatus.FAILED:
                        summary["failed"] += 1

        orphan_summary = await self._reconcile_runtime_orphans(
            bindings,
            read_only=read_only,
            allow_release=force_orphan_release or self.auto_release_orphans,
        )
        summary["orphan_candidates"] = orphan_summary["candidates"]
        summary["orphan_released"] = orphan_summary["released"]
        summary["orphan_pool_members"] = orphan_summary.get("pool_members", 0)
        summary["orphan_pool_excess"] = orphan_summary.get("pool_excess", 0)
        return summary

    def _release_retry_due(self, binding: SandboxBinding, now: datetime) -> bool:
        if binding.release_attempts >= self.max_release_attempts:
            return False
        last_change = _as_utc_naive(binding.updated_at) or now
        backoff_seconds = min(5 * (2 ** binding.release_attempts), self.scan_interval_seconds)
        return now >= last_change + timedelta(seconds=backoff_seconds)

    async def runtime_snapshot(self) -> list[dict[str, Any]]:
        """A safe admin-facing projection; it intentionally omits Runtime secrets."""
        bindings = await SandboxBindingRepository.list_by_statuses(
            [status.value for status in SandboxStatus]
        )
        result = []
        for binding in bindings:
            runtime_exists = await self._verify_runtime(binding.sandbox_id)
            result.append(
                {
                    "session_id": binding.session_id,
                    "user_id": str(binding.user_id),
                    "sandbox_id": binding.sandbox_id,
                    "status": binding.status,
                    "last_activity_at": binding.last_activity_at,
                    "lease_expires_at": binding.lease_expires_at,
                    "released_at": binding.released_at,
                    "release_attempts": binding.release_attempts,
                    "last_error": binding.last_error,
                    "runtime_seen_at": binding.runtime_seen_at,
                    "config_version": binding.config_version,
                    "runtime_exists": runtime_exists,
                }
            )
        return result

    async def _ensure_capacity(self, excluding_session_id: str) -> None:
        count = await self._runtime_container_count()
        if count is None:
            raise SandboxUnavailableError(
                "Cannot verify sandbox container capacity; refusing a new container"
            )
        while count >= self.max_active_containers:
            evicted = False
            for binding in await SandboxBindingRepository.list_idle_oldest():
                if binding.session_id == excluding_session_id:
                    continue
                if await self._has_active_task(binding.session_id):
                    continue
                released = await self.release(
                    binding.session_id,
                    reason="capacity_eviction",
                )
                if released and released.status == SandboxStatus.RELEASED:
                    evicted = True
                    break
            if not evicted:
                raise SandboxCapacityError(
                    "Sandbox capacity is full; no idle container can be safely released"
                )
            count = await self._runtime_container_count()
            if count is None:
                raise SandboxUnavailableError("Sandbox capacity changed but cannot be verified")

    async def _runtime_container_count(self) -> Optional[int]:
        try:
            output = await asyncio.to_thread(
                self._run_docker,
                [
                    "ps",
                    "-aq",
                    "--filter",
                    "name=data-sandbox-",
                ],
            )
        except Exception as error:
            logger.warning("Sandbox capacity query failed: %s", _safe_error(error))
            return None
        return len({line.strip() for line in output.splitlines() if line.strip()})

    async def _reconcile_runtime_orphans(
        self,
        bindings: list[SandboxBinding],
        *,
        read_only: bool,
        allow_release: bool,
    ) -> dict[str, int]:
        result = {
            "candidates": 0,
            "released": 0,
            "pool_members": 0,
            "pool_excess": 0,
        }
        if await self._has_any_active_task():
            return result

        pool_snapshot = await self._runtime_pool_snapshot()
        if pool_snapshot is None:
            logger.warning(
                "Sandbox orphan scan skipped: Runtime pool state is unverifiable"
            )
            return result
        result["pool_members"] = pool_snapshot.member_count
        result["pool_excess"] = max(
            0, pool_snapshot.member_count - self.manager_pool_size
        )
        if result["pool_excess"]:
            logger.warning(
                "Runtime pool contains %s excess container(s); they remain protected",
                result["pool_excess"],
            )
        try:
            output = await asyncio.to_thread(
                self._run_docker,
                [
                    "ps",
                    "-aq",
                    "--filter",
                    "label=app=dataagent",
                    "--filter",
                    "label=sandbox_type=data_analysis",
                ],
            )
        except Exception as error:
            logger.warning("Sandbox orphan scan skipped: %s", _safe_error(error))
            return result

        known_identities = await self._binding_runtime_identities(bindings)
        if known_identities is None:
            logger.warning(
                "Sandbox orphan scan skipped: binding Runtime state is unverifiable"
            )
            return result

        cutoff = _utcnow() - self.orphan_grace
        for container_id in {line.strip() for line in output.splitlines() if line.strip()}:
            metadata = await self._docker_metadata(container_id)
            if metadata is None:
                continue
            raw_id, name, created_at, labels = metadata
            identities = self._container_identities(raw_id, name)
            if (
                identities & known_identities
                or identities & pool_snapshot.identities
                or created_at >= cutoff
                or labels.get("app") != "dataagent"
                or labels.get("sandbox_type") != "data_analysis"
            ):
                continue
            result["candidates"] += 1
            logger.warning(
                "Detected unbound sandbox candidate: container=%s created=%s read_only=%s",
                raw_id,
                created_at.isoformat(),
                read_only or not allow_release,
            )
            if read_only or not allow_release:
                continue
            if await self._release_unbound_container(raw_id, name):
                result["released"] += 1
        return result

    async def _release_unbound_container(self, container_id: str, name: str) -> bool:
        """Release a candidate only after every authoritative state is rechecked."""
        if not await self._orphan_release_preflight(container_id, name):
            return False

        runtime_identity = name.removeprefix("/")
        registration = await self._runtime_registration_exists(runtime_identity)
        if registration is None:
            logger.warning(
                "Refusing orphan release for %s: Runtime registration is unknown",
                container_id,
            )
            return False

        if registration is True:
            try:
                await asyncio.to_thread(
                    self.sandbox_service.manager_api.release,
                    runtime_identity,
                )
            except Exception as error:
                logger.warning(
                    "Runtime refused orphan release for %s: %s",
                    container_id,
                    _safe_error(error),
                )
                return False
            try:
                remaining = await asyncio.to_thread(
                    self._run_docker,
                    ["ps", "-aq", "--filter", f"id={container_id}"],
                )
            except Exception as error:
                logger.warning(
                    "Cannot confirm Runtime orphan release for %s: %s",
                    container_id,
                    _safe_error(error),
                )
                return False
            if not remaining.strip():
                return True
            logger.warning(
                "Runtime reported release but container %s still exists; "
                "Docker fallback is disabled for registered containers",
                container_id,
            )
            return False

        # Runtime explicitly confirmed that it has no registration.  Recheck
        # every protection once more immediately before the Docker fallback.
        if not await self._orphan_release_preflight(container_id, name):
            return False
        try:
            await asyncio.to_thread(self._run_docker, ["rm", "-f", container_id])
            return True
        except Exception as error:
            logger.warning(
                "Failed to release labelled orphan %s: %s",
                container_id,
                _safe_error(error),
            )
            return False

    async def _orphan_release_preflight(self, container_id: str, name: str) -> bool:
        """Fail closed unless the candidate is still old, unbound and unpooled."""
        if await self._has_any_active_task():
            logger.warning(
                "Refusing orphan release for %s: task activity is present or unknown",
                container_id,
            )
            return False

        try:
            bindings = await SandboxBindingRepository.list_by_statuses(
                [
                    SandboxStatus.ACTIVE,
                    SandboxStatus.IDLE,
                    SandboxStatus.RELEASING,
                    SandboxStatus.FAILED,
                    SandboxStatus.ORPHANED,
                ]
            )
        except Exception as error:
            logger.warning(
                "Refusing orphan release for %s: binding lookup failed: %s",
                container_id,
                _safe_error(error),
            )
            return False

        known_identities = await self._binding_runtime_identities(bindings)
        if known_identities is None:
            return False

        pool_snapshot = await self._runtime_pool_snapshot()
        if pool_snapshot is None:
            return False

        metadata = await self._docker_metadata(container_id)
        if metadata is None:
            return False
        raw_id, current_name, created_at, labels = metadata
        identities = self._container_identities(raw_id, current_name)
        expected_name = name.removeprefix("/")
        if (
            raw_id != container_id
            or current_name.removeprefix("/") != expected_name
            or created_at >= _utcnow() - self.orphan_grace
            or labels.get("app") != "dataagent"
            or labels.get("sandbox_type") != "data_analysis"
            or identities & known_identities
            or identities & pool_snapshot.identities
        ):
            logger.warning(
                "Refusing orphan release for %s: candidate protection changed",
                container_id,
            )
            return False
        return True

    async def _binding_runtime_identities(
        self, bindings: list[SandboxBinding]
    ) -> Optional[set[str]]:
        identities: set[str] = set()
        for binding in bindings:
            sandbox_id = str(binding.sandbox_id)
            identities.update(self._container_identities(sandbox_id, sandbox_id))
            info = await self._runtime_info(sandbox_id)
            if info is None:
                return None
            if info is False:
                continue
            container_id = info.get("container_id")
            container_name = info.get("container_name") or info.get("name")
            if container_id:
                identities.add(str(container_id))
            if container_name:
                identities.update(
                    self._container_identities(str(container_id or ""), str(container_name))
                )
        return identities

    async def _runtime_pool_snapshot(self) -> Optional[RuntimePoolSnapshot]:
        """Read the manager's authoritative pool queue without changing Redis DB."""
        try:
            if self._manager_pool_redis is None:
                self._manager_pool_redis = aioredis.from_url(
                    self._manager_pool_connection_url(),
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
            raw_members = await self._manager_pool_redis.lrange(
                self.manager_pool_key, 0, -1
            )
            identities: set[str] = set()
            for raw_member in raw_members:
                if isinstance(raw_member, bytes):
                    raw_member = raw_member.decode("utf-8")
                member = json.loads(raw_member)
                if not isinstance(member, dict):
                    raise ValueError("Runtime pool entry is not an object")
                container_id = str(member.get("container_id") or "").strip()
                container_name = str(member.get("container_name") or "").strip()
                session_id = str(member.get("session_id") or "").strip()
                if not container_id or not container_name:
                    raise ValueError("Runtime pool entry has no container identity")
                identities.update(
                    self._container_identities(container_id, container_name)
                )
                if session_id:
                    identities.add(session_id)
            return RuntimePoolSnapshot(
                identities=frozenset(identities),
                member_count=len(raw_members),
            )
        except Exception as error:
            logger.warning(
                "Runtime pool snapshot is unavailable: %s",
                _safe_error(error),
            )
            return None

    def _manager_pool_connection_url(self) -> str:
        configured = self.manager_redis_url.strip()
        base_url = configured or settings.REDIS_URL
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"redis", "rediss"} or not parsed.netloc:
            raise ValueError("Runtime manager Redis URL is invalid")
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                f"/{self.manager_redis_db}",
                parsed.query,
                parsed.fragment,
            )
        )

    @staticmethod
    def _container_identities(container_id: str, name: str) -> set[str]:
        normalized_name = name.removeprefix("/")
        return {identity for identity in {container_id, name, normalized_name} if identity}

    async def _docker_metadata(
        self, container_id: str
    ) -> Optional[tuple[str, str, datetime, dict[str, str]]]:
        try:
            raw = await asyncio.to_thread(
                self._run_docker,
                [
                    "inspect",
                    "--format",
                    "{{.Id}}|{{.Name}}|{{.Created}}|{{json .Config.Labels}}",
                    container_id,
                ],
            )
            raw_id, name, created, raw_labels = raw.strip().split("|", 3)
            created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
            labels = json.loads(raw_labels) if raw_labels and raw_labels != "null" else {}
            return raw_id, name, _as_utc_naive(created_at) or _utcnow(), labels
        except Exception as error:
            logger.warning("Skipping unverifiable sandbox %s: %s", container_id, _safe_error(error))
            return None

    async def _has_active_task(self, session_id: str) -> bool:
        try:
            from app.services.agent_service import AgentService

            agent_service = AgentService.get_instance()
            if session_id in getattr(agent_service, "_active_agents", {}):
                return True
            redis_client = self.redis or getattr(agent_service, "_redis", None)
            if redis_client is None:
                return True
            return bool(await redis_client.get(f"session_task:{session_id}"))
        except Exception as error:
            # A Redis failure must retain rather than release a sandbox.
            logger.warning("Sandbox task liveness is unknown: %s", _safe_error(error))
            return True

    async def _has_any_active_task(self) -> bool:
        try:
            from app.services.agent_service import AgentService

            agent_service = AgentService.get_instance()
            if getattr(agent_service, "_active_agents", {}):
                return True
            redis_client = self.redis or getattr(agent_service, "_redis", None)
            if redis_client is None:
                return True
            _, keys = await redis_client.scan(0, match="session_task:*", count=1)
            return bool(keys)
        except Exception as error:
            logger.warning("Sandbox task scan is unknown: %s", _safe_error(error))
            return True

    async def _verify_runtime(self, sandbox_id: str) -> Optional[bool]:
        """Return True/False/None for present/missing/unverifiable Runtime state."""
        info = await self._runtime_info(sandbox_id)
        if info is None:
            return None
        if info is False:
            return False
        try:
            health = await asyncio.to_thread(
                self.sandbox_service.manager_api.check_health,
                sandbox_id,
            )
            return health is not False
        except Exception as error:
            detail = _safe_error(error).lower()
            if _is_missing_runtime_error(detail):
                return False
            return None

    async def _runtime_registration_exists(self, sandbox_id: str) -> Optional[bool]:
        info = await self._runtime_info(sandbox_id)
        if info is False:
            return False
        if info is None:
            return None
        return True

    async def _runtime_info(self, sandbox_id: str) -> dict[str, Any] | bool | None:
        try:
            info = await asyncio.to_thread(
                self.sandbox_service.manager_api.get_info,
                sandbox_id,
            )
            if isinstance(info, str):
                return False if _is_missing_runtime_error(info) else None
            if isinstance(info, dict) and not str(info.get("data", "")).startswith("Error:"):
                return info
            if isinstance(info, dict) and _is_missing_runtime_error(
                str(info.get("data", ""))
            ):
                return False
            return None
        except Exception as error:
            detail = _safe_error(error).lower()
            if _is_missing_runtime_error(detail):
                return False
            return None

    async def _get_mount_dir(self, sandbox: Any) -> Optional[str]:
        info = await self._runtime_info(sandbox.sandbox_id)
        return str(info["mount_dir"]) if isinstance(info, dict) and info.get("mount_dir") else None

    async def _detach_stale_runtime(self, session_id: str, user_id: str) -> None:
        try:
            await asyncio.to_thread(self.sandbox_service.release, session_id, user_id)
        except Exception as error:
            logger.warning("Failed to detach stale Runtime mapping: %s", _safe_error(error))

    def _require_runtime(self) -> None:
        if self.sandbox_service is None or getattr(self.sandbox_service, "manager_api", None) is None:
            raise SandboxUnavailableError("Sandbox Runtime is not available")

    @staticmethod
    def _run_docker(arguments: list[str]) -> str:
        result = subprocess.run(
            ["docker", *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "Docker command failed"
            raise RuntimeError(detail)
        return result.stdout


_lifecycle_service: Optional[SandboxLifecycleService] = None


def get_lifecycle_service() -> SandboxLifecycleService:
    global _lifecycle_service
    if _lifecycle_service is None:
        _lifecycle_service = SandboxLifecycleService()
    return _lifecycle_service
