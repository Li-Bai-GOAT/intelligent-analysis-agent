# -*- coding: utf-8 -*-
"""
沙箱空闲超时清理服务

由于 AgentScope Runtime (Docker 后端) 没有内置心跳超时机制，
这里实现一个定时任务来清理空闲超过指定时间的沙箱。
"""
import asyncio
import json
import logging
import subprocess
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_SANDBOX_MAINTAINER_LABEL = "kuncode-data-analysis-sandbox"
_SANDBOX_DESCRIPTION_LABEL = "Data Analysis Sandbox with KunCode AI"


class SandboxCleanupService:
    """沙箱空闲清理服务"""
    
    def __init__(
        self,
        idle_timeout_seconds: int = 7200,  # 空闲超时时间，默认 2 小时
        scan_interval_seconds: int = 300,   # 扫描间隔，默认 5 分钟
    ):
        self.idle_timeout = timedelta(seconds=idle_timeout_seconds)
        self.scan_interval = scan_interval_seconds
        self._last_activity: dict[str, datetime] = {}  # session_id -> last_activity_time
        self._session_users: dict[str, str] = {}  # session_id -> user_id
        self._session_sandbox_ids: dict[str, str] = {}  # session_id -> sandbox_id
        self._task: Optional[asyncio.Task] = None
        self._running = False
    
    def touch(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        sandbox_id: Optional[str] = None,
    ) -> None:
        """更新会话最后活跃时间（每次调用沙箱工具时调用此方法）"""
        self._last_activity[session_id] = datetime.now()
        if user_id:
            self._session_users[session_id] = str(user_id)
        if sandbox_id:
            self._session_sandbox_ids[session_id] = sandbox_id
        logger.debug(f"Session {session_id} activity updated")
    
    def get_idle_time(self, session_id: str) -> Optional[timedelta]:
        """获取会话空闲时间"""
        if session_id not in self._last_activity:
            return None
        return datetime.now() - self._last_activity[session_id]
    
    async def start(self) -> None:
        """启动后台清理任务"""
        if self._running:
            return
        
        self._running = True
        await self._restore_from_persisted_bindings()
        # 服务重启会清空内存中的活动记录。后台循环会在应用就绪后立即
        # 清理已过期且没有活跃任务的运行时沙箱，避免大量历史绑定让
        # FastAPI 生命周期和启动脚本的健康检查长时间阻塞。
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info(
            f"Sandbox cleanup service started: "
            f"idle_timeout={self.idle_timeout}, scan_interval={self.scan_interval}s"
        )

    @staticmethod
    def _as_local_naive(value: datetime) -> datetime:
        """将 ORM 时间统一为可与本地 now() 比较的无时区时间。"""
        if value.tzinfo is None:
            return value
        return value.astimezone().replace(tzinfo=None)

    async def _restore_from_persisted_bindings(self) -> None:
        """从数据库恢复重启前仍占用沙箱的会话及其最后活跃时间。"""
        from app.repositories.file_repo import SandboxBindingRepository
        from app.repositories.session_repo import SessionRepository

        try:
            bindings = await SandboxBindingRepository.list_active()
            sessions = await SessionRepository.list_by_session_ids(
                [binding.session_id for binding in bindings]
            )
        except Exception as error:
            # 无法可靠读取状态时不做自动释放，避免数据库暂时不可用时
            # 把仍在运行的会话误判为空闲。
            logger.warning("Sandbox cleanup state restore skipped: %s", error)
            return

        session_updated_at = {
            (str(session.user_id), session.session_id): self._as_local_naive(session.updated_at)
            for session in sessions
            if session.updated_at is not None
        }

        for binding in bindings:
            binding_updated_at = self._as_local_naive(binding.updated_at)
            session_updated = session_updated_at.get(
                (str(binding.user_id), binding.session_id)
            )
            self._last_activity[binding.session_id] = max(
                timestamp
                for timestamp in (binding_updated_at, session_updated)
                if timestamp is not None
            )
            self._session_users[binding.session_id] = str(binding.user_id)
            self._session_sandbox_ids[binding.session_id] = binding.sandbox_id

        if bindings:
            logger.info("Restored sandbox cleanup state for %d active bindings", len(bindings))
    
    async def stop(self) -> None:
        """停止后台清理任务"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Sandbox cleanup service stopped")
    
    async def _cleanup_loop(self) -> None:
        """后台清理循环"""
        while self._running:
            try:
                await self._cleanup_idle_sessions()
                await self._cleanup_orphan_runtime_containers()
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
            
            await asyncio.sleep(self.scan_interval)
    
    async def _cleanup_idle_sessions(self) -> None:
        """清理空闲超时的会话"""
        now = datetime.now()
        sessions_to_cleanup = []
        
        for session_id, last_activity in list(self._last_activity.items()):
            idle_time = now - last_activity
            if idle_time > self.idle_timeout:
                if await self._has_active_task(session_id):
                    # 正在运行或 Redis 状态未知时保守保留容器；将此次检查
                    # 视为活动，避免任务刚结束就被立即释放。
                    self.touch(session_id, self._session_users.get(session_id))
                    continue
                sessions_to_cleanup.append(session_id)
                logger.info(
                    f"Session {session_id} idle for {idle_time}, "
                    f"exceeds timeout {self.idle_timeout}"
                )
        
        for session_id in sessions_to_cleanup:
            try:
                await self._release_session(session_id)
                del self._last_activity[session_id]
                self._session_users.pop(session_id, None)
                self._session_sandbox_ids.pop(session_id, None)
                logger.info(f"Session {session_id} released due to idle timeout")
            except Exception as e:
                logger.error(f"Failed to release session {session_id}: {e}")

    async def _has_active_task(self, session_id: str) -> bool:
        """任务仍在运行或状态未知时，均不自动释放沙箱。"""
        from app.services.agent_service import AgentService

        agent_service = AgentService.get_instance()
        if session_id in getattr(agent_service, "_active_agents", {}):
            return True

        redis_client = getattr(agent_service, "_redis", None)
        if redis_client is None:
            logger.warning("Skip sandbox cleanup because Redis is unavailable")
            return True

        try:
            return bool(await redis_client.get(f"session_task:{session_id}"))
        except Exception as error:
            logger.warning("Skip sandbox cleanup because task state is unavailable: %s", error)
            return True

    async def _has_any_active_task(self) -> bool:
        """未知归属的容器只有在系统没有活跃任务时才能回收。"""
        from app.services.agent_service import AgentService

        agent_service = AgentService.get_instance()
        if getattr(agent_service, "_active_agents", {}):
            return True

        redis_client = getattr(agent_service, "_redis", None)
        if redis_client is None:
            logger.warning("Skip orphan sandbox cleanup because Redis is unavailable")
            return True

        try:
            _, keys = await redis_client.scan(0, match="session_task:*", count=1)
            return bool(keys)
        except Exception as error:
            logger.warning("Skip orphan sandbox cleanup because task scan failed: %s", error)
            return True

    @staticmethod
    def _run_docker(arguments: list[str]) -> str:
        """运行受限的 Docker 查询或运行时容器删除命令。"""
        result = subprocess.run(
            ["docker", *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown Docker error"
            raise RuntimeError(detail)
        return result.stdout

    async def _cleanup_orphan_runtime_containers(self) -> None:
        """清理没有活动数据库绑定的过期 DataAgent 运行时容器。"""
        if await self._has_any_active_task():
            return

        try:
            output = await asyncio.to_thread(
                self._run_docker,
                [
                    "ps",
                    "-aq",
                    "--filter",
                    f"label=maintainer={_SANDBOX_MAINTAINER_LABEL}",
                    "--filter",
                    "name=data-sandbox-",
                ],
            )
        except Exception as error:
            logger.warning("Orphan sandbox cleanup skipped: %s", error)
            return

        protected_ids = set(self._session_sandbox_ids.values())
        cutoff = datetime.now() - self.idle_timeout
        orphan_ids: list[str] = []

        for container_id in filter(None, output.splitlines()):
            try:
                metadata = await asyncio.to_thread(
                    self._run_docker,
                    [
                        "inspect",
                        "--format",
                        "{{.Id}}|{{.Name}}|{{.Created}}|{{json .Config.Labels}}",
                        container_id,
                    ],
                )
                raw_id, name, created_at, raw_labels = metadata.strip().split("|", 3)
                labels = json.loads(raw_labels)
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                created_local = created.astimezone().replace(tzinfo=None)
            except Exception as error:
                logger.warning("Skip unverifiable sandbox container %s: %s", container_id, error)
                continue

            is_protected = raw_id in protected_ids or name.removeprefix("/") in protected_ids
            if (
                not is_protected
                and name.startswith("/data-sandbox-")
                and labels.get("maintainer") == _SANDBOX_MAINTAINER_LABEL
                and labels.get("description") == _SANDBOX_DESCRIPTION_LABEL
                and created_local < cutoff
            ):
                orphan_ids.append(raw_id)

        if not orphan_ids:
            return

        try:
            await asyncio.to_thread(self._run_docker, ["rm", "-f", *orphan_ids])
            logger.info("Released %d orphan sandbox containers", len(orphan_ids))
        except Exception as error:
            logger.warning("Failed to release orphan sandbox containers: %s", error)
    
    async def _release_session(self, session_id: str) -> None:
        """释放会话的沙箱资源"""
        from app.services.agent_service import AgentService
        from app.repositories.file_repo import SandboxBindingRepository
        
        agent_service = AgentService.get_instance()
        user_id = self._session_users.get(session_id)
        if not user_id:
            binding = await SandboxBindingRepository.get_by_session(session_id)
            user_id = str(binding.user_id) if binding else None

        if not user_id:
            raise RuntimeError("sandbox binding owner is missing")

        if agent_service and agent_service.sandbox_service:
            # Runtime 以 session_id_user_id 映射容器；漏传 user_id 会导致
            # release 找不到容器，Docker 容器会一直保留。
            await asyncio.to_thread(
                agent_service.sandbox_service.release,
                session_id,
                user_id,
            )
            await SandboxBindingRepository.update(session_id, is_active=False)


# 全局单例
_cleanup_service: Optional[SandboxCleanupService] = None


def get_cleanup_service(
    idle_timeout_seconds: int = 7200,
    scan_interval_seconds: int = 300,
) -> SandboxCleanupService:
    """获取清理服务单例"""
    global _cleanup_service
    if _cleanup_service is None:
        _cleanup_service = SandboxCleanupService(
            idle_timeout_seconds=idle_timeout_seconds,
            scan_interval_seconds=scan_interval_seconds,
        )
    return _cleanup_service
