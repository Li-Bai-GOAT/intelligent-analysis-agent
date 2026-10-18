# -*- coding: utf-8 -*-
"""
KunCode SSE Streaming Router

提供 /run_kuncode 端点，支持流式输出 kuncode 执行结果。
参考 agentscope-runtime 代码风格实现。
"""

import asyncio
import ctypes
import json
import logging
import os
import signal
import time
import uuid
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["kuncode"])

_active_executions: dict[str, dict] = {}
_terminal_executions: dict[str, dict] = {}
_executions_lock = asyncio.Lock()
_TERMINAL_HISTORY_LIMIT = 128


def _enable_child_subreaper() -> None:
    """Make the runtime server reap orphaned KunCode descendants in Docker."""
    if os.name != "posix":
        return
    try:
        # Linux prctl(PR_SET_CHILD_SUBREAPER, 1). Descendants orphaned while a
        # process group is terminated are then re-parented here instead of to
        # a PID 1 that may not reap promptly inside a container.
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_CHILD_SUBREAPER) failed")
    except Exception:
        logger.exception("Unable to enable KunCode child subreaper")


_enable_child_subreaper()


def _kuncode_result_event(
    *,
    success: bool,
    exit_code: int | None = None,
    error_code: str | None = None,
    termination_reason: str | None = None,
    execution_id: str | None = None,
) -> str:
    """Emit a machine-readable terminal result before the SSE sentinel.

    KunCode can recover from a failed internal shell/script attempt and still
    exit successfully.  The caller must therefore receive the process result
    separately from the human-readable transcript instead of inferring it from
    every historical ``Traceback`` in that transcript.
    """
    payload = {
        "event": "kuncode_result",
        "success": success,
        "exit_code": exit_code,
        "error_code": error_code,
        "termination_reason": termination_reason,
        "execution_id": execution_id,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _normalize_model_name(model: Optional[str]) -> Optional[str]:
    if model == "mimo-v2.6-pro":
        return "mimo/mimo-v2.6-pro"
    return model


def _is_allowed_model(model: Optional[str]) -> bool:
    requested = _normalize_model_name(model or os.getenv("KUNCODE_MODEL", "mimo/mimo-v2.6-pro"))
    allowed = {
        item.strip()
        for item in os.getenv("ALLOWED_KUNCODE_MODELS", "mimo/mimo-v2.6-pro").split(",")
        if item.strip()
    }
    if requested not in allowed:
        return False
    return not (
        requested.lower().startswith("mimo/")
        and os.getenv("DISABLE_MIMO", "false").lower() in {"1", "true", "yes", "on"}
    )


def _normalize_agent_name(agent: Optional[str]) -> Optional[str]:
    if agent is None:
        return None
    normalized = str(agent).strip()
    if not normalized or normalized.lower() in {"none", "null", "undefined", "default"}:
        return None
    return normalized


class KunCodeRequest(BaseModel):
    """KunCode 执行请求参数"""
    prompt: str = Field(..., description="要执行的任务描述")
    agent: Optional[str] = Field(None, description="指定使用的智能体")
    model: Optional[str] = Field(None, description="覆盖默认模型")
    files: Optional[List[str]] = Field(None, description="附加的文件路径列表")
    continue_session: bool = Field(False, description="是否继续上次会话")
    session_id: Optional[str] = Field(None, description="指定会话 ID")
    output_format: str = Field("default", description="输出格式: default 或 json")
    execution_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="本次执行的幂等标识",
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    deadline_at_ms: Optional[int] = Field(
        None,
        description="顶层任务的 Unix epoch 毫秒 deadline",
    )
    trace_id: Optional[str] = Field(None, description="DataAgent trace ID")
    task_id: Optional[str] = Field(None, description="DataAgent task ID")
    dataagent_session_id: Optional[str] = Field(None, description="DataAgent session ID")
    dataagent_sandbox_id: Optional[str] = Field(None, description="DataAgent sandbox ID")


class KunCodeCancelRequest(BaseModel):
    execution_id: str = Field(
        ...,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    grace_seconds: float = Field(5.0, ge=0.1, le=30.0)
    termination_reason: str = Field("cancelled", pattern="^(cancelled|timeout)$")


async def _remember_terminal(execution_id: str, result: dict) -> None:
    async with _executions_lock:
        _active_executions.pop(execution_id, None)
        _terminal_executions[execution_id] = {
            **result,
            "execution_id": execution_id,
            "active": False,
        }
        while len(_terminal_executions) > _TERMINAL_HISTORY_LIMIT:
            _terminal_executions.pop(next(iter(_terminal_executions)))


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _reap_process_group(process_group_id: int) -> None:
    """Reap only orphaned descendants belonging to this execution group."""
    if os.name != "posix":
        return
    while True:
        try:
            pid, _ = os.waitpid(-process_group_id, os.WNOHANG)
        except ChildProcessError:
            return


def _execution_pids(execution_id: str) -> set[int]:
    """Find all live processes inheriting this execution's environment tag."""
    if os.name != "posix":
        return set()
    marker = f"DATAAGENT_EXECUTION_ID={execution_id}".encode()
    matches: set[int] = set()
    try:
        entries = os.scandir("/proc")
    except OSError:
        return matches
    with entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            try:
                with open(f"/proc/{pid}/environ", "rb") as environ_file:
                    environ = environ_file.read()
            except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
                continue
            if marker in environ.split(b"\0"):
                matches.add(pid)
    return matches


def _pid_exists(pid: int) -> bool:
    return os.path.exists(f"/proc/{pid}") if os.name == "posix" else False


def _signal_execution_pids(execution_id: str, sig: signal.Signals) -> set[int]:
    pids = _execution_pids(execution_id)
    for pid in sorted(pids, reverse=True):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
    return pids


def _reap_execution_pids(pids: set[int], leader_pid: int) -> None:
    if os.name != "posix":
        return
    for pid in pids:
        if pid == leader_pid:
            continue
        try:
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, ProcessLookupError):
            pass
        if pid == 0:
            return


async def _terminate_process_group(
    process: asyncio.subprocess.Process,
    *,
    grace_seconds: float,
    execution_id: str,
) -> dict:
    """Terminate every tagged descendant, including escaped process groups."""
    process_group_id = process.pid
    forced = False
    observed_pids = _signal_execution_pids(execution_id, signal.SIGTERM)
    if _process_group_exists(process_group_id):
        try:
            os.killpg(process_group_id, signal.SIGTERM)
        except ProcessLookupError:
            pass

    graceful_deadline = time.monotonic() + grace_seconds
    while time.monotonic() < graceful_deadline:
        current = _execution_pids(execution_id)
        observed_pids.update(current)
        _reap_execution_pids(observed_pids, process.pid)
        if not current and not _process_group_exists(process_group_id):
            break
        # Catch processes spawned during shutdown before their parent exits.
        _signal_execution_pids(execution_id, signal.SIGTERM)
        await asyncio.sleep(0.05)

    remaining_pids = _execution_pids(execution_id)
    if remaining_pids or _process_group_exists(process_group_id):
        forced = True
        observed_pids.update(_signal_execution_pids(execution_id, signal.SIGKILL))
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.returncode is None:
        try:
            await asyncio.wait_for(asyncio.shield(process.wait()), timeout=2.0)
        except asyncio.TimeoutError:
            pass

    confirm_deadline = time.monotonic() + 2.0
    while time.monotonic() < confirm_deadline:
        remaining_pids = _execution_pids(execution_id)
        observed_pids.update(remaining_pids)
        if remaining_pids:
            _signal_execution_pids(execution_id, signal.SIGKILL)
        _reap_execution_pids(observed_pids, process.pid)
        _reap_process_group(process_group_id)
        observed_alive = any(_pid_exists(pid) for pid in observed_pids)
        if (
            not remaining_pids
            and not _process_group_exists(process_group_id)
            and not observed_alive
        ):
            break
        await asyncio.sleep(0.05)
    _reap_execution_pids(observed_pids, process.pid)
    _reap_process_group(process_group_id)
    residual_pids = sorted(_execution_pids(execution_id))
    confirmed = (
        process.returncode is not None
        and not residual_pids
        and not _process_group_exists(process_group_id)
        and not any(_pid_exists(pid) for pid in observed_pids)
    )
    return {
        "termination_confirmed": confirmed,
        "forced": forced,
        "pid": process.pid,
        "observed_pids": sorted(observed_pids),
        "residual_pids": residual_pids,
        "exit_code": process.returncode,
    }


def _build_kuncode_command(request: KunCodeRequest) -> List[str]:
    """
    构建 kuncode 命令参数列表（安全方式，不经过 shell）
    
    Args:
        request: KunCode 请求参数
        
    Returns:
        命令参数列表，直接传给 subprocess，防止注入
    """
    cmd = ["kuncode", "run"]
    
    if request.continue_session:
        cmd.append("-c")
    
    if request.session_id:
        cmd.extend(["-s", request.session_id])
    
    agent = _normalize_agent_name(request.agent)
    if agent:
        cmd.extend(["--agent", agent])
    
    model = _normalize_model_name(request.model)
    if model:
        cmd.extend(["-m", model])
    
    if request.files:
        for file_path in request.files:
            cmd.extend(["-f", file_path])
    
    if request.output_format and request.output_format != "default":
        cmd.extend(["--format", request.output_format])
    
    # prompt 作为最后一个参数，作为独立参数传递，不经过 shell 解析
    cmd.append(request.prompt)
    
    return cmd


async def _stream_kuncode_output(cmd: List[str], request: KunCodeRequest):
    """
    异步流式执行 kuncode 命令并 yield SSE 格式输出
    
    真正的流式：每次解码出内容就立即发送 SSE 事件。
    使用 JSON 编码保留换行符等特殊字符。
    
    Args:
        cmd: 命令参数列表
        
    Yields:
        SSE 格式的输出
    """
    import codecs
    import json
    idle_timeout = float(os.getenv("KUNCODE_STREAM_IDLE_TIMEOUT", "300"))
    termination_grace = float(os.getenv("KUNCODE_TERMINATION_GRACE_SECONDS", "5"))
    process: asyncio.subprocess.Process | None = None
    terminal_recorded = False

    def remaining_seconds() -> float | None:
        if request.deadline_at_ms is None:
            return None
        return (request.deadline_at_ms - int(time.time() * 1000)) / 1000.0

    try:
        remaining = remaining_seconds()
        if remaining is not None and remaining <= 0:
            yield _kuncode_result_event(
                success=False,
                error_code="KUNCODE_DEADLINE_EXCEEDED",
                termination_reason="timeout",
                execution_id=request.execution_id,
            )
            yield "data: [DONE]\n\n"
            await _remember_terminal(request.execution_id, {
                "termination_reason": "timeout",
                "termination_confirmed": True,
                "exit_code": None,
            })
            terminal_recorded = True
            return
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
            env={
                **os.environ,
                "DATAAGENT_EXECUTION_ID": request.execution_id,
            },
        )
        async with _executions_lock:
            _active_executions[request.execution_id] = {
                "process": process,
                "pid": process.pid,
                "cancel_reason": None,
                "started_at_ms": int(time.time() * 1000),
            }
        started_message = "[KunCode] process started, waiting for model output...\n"
        yield f"data: {json.dumps(started_message)}\n\n"
        
        # 使用增量解码器，正确处理多字节 UTF-8 字符
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        
        while True:
            # 读取小块数据
            try:
                remaining = remaining_seconds()
                if remaining is not None and remaining <= 0:
                    raise asyncio.TimeoutError
                read_timeout = min(idle_timeout, remaining) if remaining is not None else idle_timeout
                chunk = await asyncio.wait_for(process.stdout.read(64), timeout=read_timeout)
            except asyncio.TimeoutError:
                remaining = remaining_seconds()
                deadline_exceeded = remaining is not None and remaining <= 0.05
                error_code = (
                    "KUNCODE_DEADLINE_EXCEEDED"
                    if deadline_exceeded
                    else "KUNCODE_IDLE_TIMEOUT"
                )
                termination = await _terminate_process_group(
                    process,
                    grace_seconds=termination_grace,
                    execution_id=request.execution_id,
                )
                message = (
                    "\n[ERROR] KunCode exceeded the task deadline and was stopped.\n"
                    if deadline_exceeded
                    else f"\n[ERROR] KunCode produced no output for {idle_timeout:g}s and was stopped.\n"
                )
                yield f"data: {json.dumps(message)}\n\n"
                yield _kuncode_result_event(
                    success=False,
                    exit_code=termination["exit_code"],
                    error_code=error_code,
                    termination_reason="timeout",
                    execution_id=request.execution_id,
                )
                yield "data: [DONE]\n\n"
                await _remember_terminal(request.execution_id, {
                    **termination,
                    "termination_reason": "timeout",
                    "error_code": error_code,
                })
                terminal_recorded = True
                return
            if not chunk:
                # 处理解码器中剩余的字节
                remaining = decoder.decode(b"", final=True)
                if remaining:
                    # JSON 编码保留换行符
                    yield f"data: {json.dumps(remaining)}\n\n"
                break
            
            # 增量解码后立即发送，JSON 编码保留特殊字符
            text = decoder.decode(chunk)
            if text:
                yield f"data: {json.dumps(text)}\n\n"
        
        return_code = await process.wait()
        cleanup = await _terminate_process_group(
            process,
            grace_seconds=min(termination_grace, 0.5),
            execution_id=request.execution_id,
        )
        async with _executions_lock:
            active = _active_executions.get(request.execution_id) or {}
            cancel_reason = active.get("cancel_reason")
        async with _executions_lock:
            terminal = _terminal_executions.get(request.execution_id) or {}
        cancel_reason = cancel_reason or terminal.get("termination_reason")
        if cancel_reason in {"cancelled", "timeout"}:
            error_code = (
                "KUNCODE_DEADLINE_EXCEEDED"
                if cancel_reason == "timeout"
                else "KUNCODE_CANCELLED"
            )
            yield _kuncode_result_event(
                success=False,
                exit_code=return_code,
                error_code=error_code,
                termination_reason=cancel_reason,
                execution_id=request.execution_id,
            )
            yield "data: [DONE]\n\n"
            await _remember_terminal(request.execution_id, {
                "termination_reason": cancel_reason,
                "termination_confirmed": cleanup["termination_confirmed"],
                "exit_code": return_code,
                "error_code": error_code,
            })
            terminal_recorded = True
            return
        if return_code != 0:
            message = f"\n[ERROR] KunCode exited with code {return_code}.\n"
            yield f"data: {json.dumps(message)}\n\n"
            yield _kuncode_result_event(
                success=False,
                exit_code=return_code,
                error_code="KUNCODE_NONZERO_EXIT",
                termination_reason="process_error",
                execution_id=request.execution_id,
            )
            yield "data: [DONE]\n\n"
            await _remember_terminal(request.execution_id, {
                "termination_reason": "process_error",
                "termination_confirmed": cleanup["termination_confirmed"],
                "exit_code": return_code,
                "error_code": "KUNCODE_NONZERO_EXIT",
            })
            terminal_recorded = True
            return

        yield _kuncode_result_event(
            success=True,
            exit_code=return_code,
            termination_reason="completed",
            execution_id=request.execution_id,
        )
        # 发送完成标记
        yield "data: [DONE]\n\n"
        await _remember_terminal(request.execution_id, {
            "termination_reason": "completed",
            "termination_confirmed": cleanup["termination_confirmed"],
            "observed_pids": cleanup["observed_pids"],
            "residual_pids": cleanup["residual_pids"],
            "exit_code": return_code,
        })
        terminal_recorded = True
    except asyncio.CancelledError:
        if process is not None:
            async with _executions_lock:
                active = _active_executions.get(request.execution_id)
                if active is not None:
                    active["cancel_reason"] = "cancelled"
            termination = await asyncio.shield(_terminate_process_group(
                process,
                grace_seconds=termination_grace,
                execution_id=request.execution_id,
            ))
            await asyncio.shield(_remember_terminal(request.execution_id, {
                **termination,
                "termination_reason": "cancelled",
                "error_code": "KUNCODE_CANCELLED",
            }))
            terminal_recorded = True
        raise
    except Exception as e:
        logger.exception("KunCode execution failed")
        termination = None
        if process is not None and process.returncode is None:
            termination = await _terminate_process_group(
                process,
                grace_seconds=termination_grace,
                execution_id=request.execution_id,
            )
        message = f"[ERROR] KunCode execution failed: {str(e)}"
        yield f"data: {json.dumps(message)}\n\n"
        yield _kuncode_result_event(
            success=False,
            error_code="KUNCODE_PROCESS_ERROR",
            termination_reason="process_error",
            execution_id=request.execution_id,
        )
        yield "data: [DONE]\n\n"
        await _remember_terminal(request.execution_id, {
            **(termination or {"termination_confirmed": True, "exit_code": None}),
            "termination_reason": "process_error",
            "error_code": "KUNCODE_PROCESS_ERROR",
        })
        terminal_recorded = True
    finally:
        if process is not None and process.returncode is None:
            termination = await asyncio.shield(_terminate_process_group(
                process,
                grace_seconds=termination_grace,
                execution_id=request.execution_id,
            ))
            if not terminal_recorded:
                await asyncio.shield(_remember_terminal(request.execution_id, {
                    **termination,
                    "termination_reason": "cancelled",
                    "error_code": "KUNCODE_CANCELLED",
                }))


@router.post("/run_kuncode")
async def run_kuncode_stream(request: KunCodeRequest):
    """
    流式执行 KunCode 命令
    
    使用 Server-Sent Events (SSE) 实时返回 kuncode 输出。
    
    Args:
        request: KunCode 执行请求参数
        
    Returns:
        StreamingResponse: SSE 格式的流式响应
    """
    if not _is_allowed_model(request.model):
        raise HTTPException(status_code=403, detail="KunCode 模型未获准")
    # 构建安全的命令参数列表
    cmd = _build_kuncode_command(request)
    
    logger.info(f"Starting KunCode stream: {' '.join(cmd[:3])}...")
    
    return StreamingResponse(
        _stream_kuncode_output(cmd, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )


@router.post("/cancel_kuncode")
async def cancel_kuncode(request: KunCodeCancelRequest):
    """Idempotently stop one KunCode process group and confirm termination."""
    async with _executions_lock:
        active = _active_executions.get(request.execution_id)
        terminal = _terminal_executions.get(request.execution_id)
        if active is not None:
            active["cancel_reason"] = request.termination_reason
    if active is None:
        return terminal or {
            "execution_id": request.execution_id,
            "active": False,
            "termination_reason": request.termination_reason,
            "termination_confirmed": True,
            "already_stopped": True,
        }

    termination = await _terminate_process_group(
        active["process"],
        grace_seconds=request.grace_seconds,
        execution_id=request.execution_id,
    )
    result = {
        **termination,
        "execution_id": request.execution_id,
        "active": False,
        "termination_reason": request.termination_reason,
        "error_code": (
            "KUNCODE_DEADLINE_EXCEEDED"
            if request.termination_reason == "timeout"
            else "KUNCODE_CANCELLED"
        ),
    }
    await _remember_terminal(request.execution_id, result)
    return result


@router.get("/kuncode/process/{execution_id}")
async def kuncode_process_status(execution_id: str):
    """Return authoritative active/terminal state for integration checks."""
    async with _executions_lock:
        active = _active_executions.get(execution_id)
        terminal = _terminal_executions.get(execution_id)
    if active is not None:
        process = active["process"]
        tagged_pids = sorted(_execution_pids(execution_id))
        return {
            "execution_id": execution_id,
            "active": bool(tagged_pids) or _process_group_exists(process.pid),
            "pid": process.pid,
            "tagged_pids": tagged_pids,
            "termination_confirmed": False,
        }
    return terminal or {
        "execution_id": execution_id,
        "active": False,
        "termination_confirmed": True,
        "not_found": True,
    }


@router.get("/kuncode/health")
async def kuncode_health():
    """检查 kuncode 是否可用"""
    try:
        process = await asyncio.create_subprocess_exec(
            "kuncode", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        version = stdout.decode().strip()
        return {"status": "ok", "version": version}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"KunCode not available: {e}")
