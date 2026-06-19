# -*- coding: utf-8 -*-
"""
沙箱空闲超时清理服务

由于 AgentScope Runtime (Docker 后端) 没有内置心跳超时机制，
这里实现一个定时任务来清理空闲超过指定时间的沙箱。
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


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
        self._task: Optional[asyncio.Task] = None
        self._running = False
    
    def touch(self, session_id: str) -> None:
        """更新会话最后活跃时间（每次调用沙箱工具时调用此方法）"""
        self._last_activity[session_id] = datetime.now()
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
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info(
            f"Sandbox cleanup service started: "
            f"idle_timeout={self.idle_timeout}, scan_interval={self.scan_interval}s"
        )
    
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
                sessions_to_cleanup.append(session_id)
                logger.info(
                    f"Session {session_id} idle for {idle_time}, "
                    f"exceeds timeout {self.idle_timeout}"
                )
        
        for session_id in sessions_to_cleanup:
            try:
                await self._release_session(session_id)
                del self._last_activity[session_id]
                logger.info(f"Session {session_id} released due to idle timeout")
            except Exception as e:
                logger.error(f"Failed to release session {session_id}: {e}")
    
    async def _release_session(self, session_id: str) -> None:
        """释放会话的沙箱资源"""
        from app.services.agent_service import AgentService
        
        agent_service = AgentService.get_instance()
        if agent_service and agent_service.sandbox_service:
            # 释放沙箱
            agent_service.sandbox_service.release(session_id)


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
