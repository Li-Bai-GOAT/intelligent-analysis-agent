"""Model-call audit trail and local admission controls."""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from app.config import settings

logger = logging.getLogger(__name__)


class ModelAdmissionError(RuntimeError):
    """Raised before an upstream model request is allowed to start."""


@dataclass(frozen=True)
class AuditContext:
    trace_id: str
    task_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    source: str = "backend"
    entrypoint: str = "conversation"
    sandbox_id: str | None = None
    container_id: str | None = None
    user_agent: str | None = None
    device_type: str | None = None
    os_version: str | None = None


_context: contextvars.ContextVar[AuditContext | None] = contextvars.ContextVar(
    "dataagent_model_audit_context", default=None
)
_write_lock = threading.Lock()
_quota_lock = threading.Lock()
_active_requests = 0
_daily_usage: dict[tuple[str, str], int] = {}
_SENSITIVE_FIELD = re.compile(
    r"^(?:api[_-]?key|authorization|cookie|prompt|response(?:[_-]?body)?|request[_-]?body|secret|token|headers)$",
    re.IGNORECASE,
)


def new_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex}"


def get_audit_context() -> AuditContext | None:
    return _context.get()


@asynccontextmanager
async def audit_context(**values: Any) -> AsyncIterator[AuditContext]:
    current = get_audit_context()
    context = AuditContext(
        trace_id=values.get("trace_id") or (current.trace_id if current else new_trace_id()),
        task_id=values.get("task_id", current.task_id if current else None),
        session_id=values.get("session_id", current.session_id if current else None),
        user_id=values.get("user_id", current.user_id if current else None),
        source=values.get("source", current.source if current else "backend"),
        entrypoint=values.get("entrypoint", current.entrypoint if current else "conversation"),
        sandbox_id=values.get("sandbox_id", current.sandbox_id if current else None),
        container_id=values.get("container_id", current.container_id if current else None),
        user_agent=values.get("user_agent", current.user_agent if current else None),
        device_type=values.get("device_type", current.device_type if current else None),
        os_version=values.get("os_version", current.os_version if current else None),
    )
    token = _context.set(context)
    try:
        yield context
    finally:
        _context.reset(token)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _host(base_url: str | None) -> str | None:
    return urlparse(base_url).hostname if base_url else None


def estimate_tokens(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    return max(0, int(len(text) * 0.35))


def _attr(source: Any, name: str) -> Any:
    """Read an attribute without leaking mapping-style lookups.

    AgentScope's ChatResponse/ChatUsage inherit from DictMixin(dict), whose
    ``__getattr__`` is ``dict.__getitem__``. ``getattr(obj, name, default)``
    only swallows AttributeError, so a missing key raises KeyError and would
    abort usage extraction — and with it the whole chat turn.
    """
    try:
        return getattr(source, name, None)
    except (KeyError, AttributeError):
        return None


def extract_usage(value: Any) -> dict[str, int] | None:
    candidates = [value]
    if isinstance(value, dict):
        candidates.extend([value.get("usage"), value.get("response_metadata"), value.get("metadata")])
    else:
        candidates.extend([
            _attr(value, "usage"),
            _attr(value, "response_metadata"),
            _attr(value, "metadata"),
        ])
    for candidate in candidates:
        if candidate is None:
            continue
        raw_candidate = candidate
        if not isinstance(candidate, dict):
            model_dump = _attr(candidate, "model_dump")
            dumped = model_dump() if callable(model_dump) else None
            candidate = dumped or _attr(candidate, "__dict__") or {}
        if not isinstance(candidate, dict):
            continue
        prompt = candidate.get("prompt_tokens", candidate.get("input_tokens"))
        completion = candidate.get("completion_tokens", candidate.get("output_tokens"))
        total = candidate.get("total_tokens")
        if prompt is None:
            prompt = _attr(raw_candidate, "prompt_tokens")
            if prompt is None:
                prompt = _attr(raw_candidate, "input_tokens")
        if completion is None:
            completion = _attr(raw_candidate, "completion_tokens")
            if completion is None:
                completion = _attr(raw_candidate, "output_tokens")
        if total is None:
            total = _attr(raw_candidate, "total_tokens")
        if prompt is not None or completion is not None or total is not None:
            try:
                prompt = int(prompt or 0)
                completion = int(completion or 0)
                total = int(total or prompt + completion)
            except (TypeError, ValueError):
                continue
            return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}
    return None


def key_fingerprint(api_key: str | None) -> str | None:
    if not api_key:
        return None
    return "sha256:" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _write(event: dict[str, Any]) -> None:
    if not settings.MODEL_AUDIT_ENABLED:
        return
    path = Path(settings.MODEL_AUDIT_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        _rotate_and_cleanup(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def _rotated_path(path: Path, date_key: str) -> Path:
    return path.with_name(f"{path.stem}-{date_key}{path.suffix}")


def _audit_files(path: Path) -> list[Path]:
    rotated = sorted(
        path.parent.glob(f"{path.stem}-*{path.suffix}"),
        key=lambda item: item.name,
    )
    return [item for item in rotated if item.is_file()] + ([path] if path.is_file() else [])


def _rotate_and_cleanup(path: Path) -> None:
    """Keep the configured path active while rotating completed UTC days."""
    if path.exists() and path.stat().st_size > 0:
        file_date = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date().isoformat()
        today = _date_key()
        if file_date != today:
            destination = _rotated_path(path, file_date)
            if destination.exists():
                destination = path.with_name(
                    f"{path.stem}-{file_date}-{int(time.time())}{path.suffix}"
                )
            path.replace(destination)

    retention_days = max(0, int(settings.MODEL_AUDIT_RETENTION_DAYS))
    cutoff = datetime.now(timezone.utc).date().toordinal() - retention_days
    for candidate in _audit_files(path):
        if candidate == path:
            continue
        match = re.search(r"-(\d{4}-\d{2}-\d{2})(?:-\d+)?" + re.escape(path.suffix) + r"$", candidate.name)
        if not match:
            continue
        try:
            candidate_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if candidate_date.toordinal() < cutoff:
            try:
                candidate.unlink()
            except OSError:
                logger.warning("Unable to remove expired model audit log: %s", candidate)


def _redact_payload(value: Any, *, field_name: str = "") -> Any:
    if _SENSITIVE_FIELD.search(field_name):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {key: _redact_payload(item, field_name=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item, field_name=field_name) for item in value]
    return value


def emit_event(event: str, **fields: Any) -> None:
    context = get_audit_context()
    payload = {
        "event": event,
        "request_id": fields.pop("request_id", None) or f"req_{uuid.uuid4().hex}",
        "trace_id": fields.pop("trace_id", None) or (context.trace_id if context else None),
        **fields,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    payload = _redact_payload(payload)
    try:
        _write(payload)
    except Exception:
        logger.exception("Unable to write model audit event")


def _date_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def admission_check(provider: str, model: str, estimated_tokens: int = 0) -> None:
    if provider.lower() not in settings.allowed_model_providers:
        raise ModelAdmissionError(f"模型提供商未获准: {provider}")
    if provider.lower() == "mimo" and settings.DISABLE_MIMO:
        raise ModelAdmissionError("Mimo 已禁用")
    if settings.allowed_model_names and model not in settings.allowed_model_names:
        raise ModelAdmissionError(f"模型未获准: {model}")
    if estimated_tokens > settings.MAX_REQUEST_TOKENS:
        raise ModelAdmissionError("单次模型请求超过 Token 上限")
    with _quota_lock:
        context = get_audit_context()
        if context and context.user_id and settings.DAILY_USER_TOKEN_LIMIT > 0:
            used = _daily_usage.get((context.user_id, _date_key()), 0)
            if used + estimated_tokens > settings.DAILY_USER_TOKEN_LIMIT:
                raise ModelAdmissionError("用户当日模型 Token 额度已用尽")


@asynccontextmanager
async def request_slot() -> AsyncIterator[None]:
    global _active_requests
    with _quota_lock:
        if settings.MODEL_MAX_CONCURRENCY > 0 and _active_requests >= settings.MODEL_MAX_CONCURRENCY:
            raise ModelAdmissionError("模型并发请求数已达上限")
        _active_requests += 1
    try:
        yield
    finally:
        with _quota_lock:
            _active_requests = max(0, _active_requests - 1)


def record_usage(tokens: int) -> None:
    context = get_audit_context()
    if not context or not context.user_id or tokens <= 0:
        return
    with _quota_lock:
        key = (context.user_id, _date_key())
        _daily_usage[key] = _daily_usage.get(key, 0) + tokens


def read_audits(filters: dict[str, str | None], limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    path = Path(settings.MODEL_AUDIT_LOG_PATH)
    files = _audit_files(path)
    if not files:
        return [], 0
    matched: list[dict[str, Any]] = []
    for audit_file in files:
        try:
            with audit_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if _matches_audit(item, filters):
                        matched.append(item)
        except OSError:
            logger.warning("Unable to read model audit log: %s", audit_file)
    matched.sort(key=lambda item: str(item.get("started_at", item.get("finished_at", ""))))
    return matched[offset:offset + limit], len(matched)


def _matches_audit(item: dict[str, Any], filters: dict[str, str | None]) -> bool:
    for key, value in filters.items():
        if not value:
            continue
        if key == "model":
            if value not in {str(item.get("requested_model", "")), str(item.get("actual_model", ""))}:
                return False
        elif key == "start_time":
            if str(item.get("finished_at", item.get("started_at", ""))) < value:
                return False
        elif key == "end_time":
            if str(item.get("started_at", "")) > value:
                return False
        elif str(item.get(key, "")) != value:
            return False
    return True


@dataclass
class AuditRequest:
    provider: str
    requested_model: str
    base_url: str | None
    request_type: str = "chat_completion"
    stream: bool = True
    request_id: str = field(default_factory=lambda: f"req_{uuid.uuid4().hex}")
    started_at: str = field(default_factory=_now)
    started_monotonic: float = field(default_factory=time.monotonic)
    attempt: int = 1
    usage: dict[str, int] | None = None
    chunks: int = 0
    estimated_prompt_tokens: int = 0

    def start(self) -> None:
        context = get_audit_context()
        emit_event(
            "request_started", request_id=self.request_id,
            parent_task_id=context.task_id if context else None,
            session_id=context.session_id if context else None,
            source=context.source if context else "backend",
            entrypoint=context.entrypoint if context else "conversation",
            sandbox_id=context.sandbox_id if context else None,
            container_id=context.container_id if context else None,
            provider=self.provider, requested_model=self.requested_model,
            actual_model=self.requested_model, base_url_host=_host(self.base_url),
            request_type=self.request_type, stream=self.stream, attempt=self.attempt,
            started_at=self.started_at,
            user_agent=context.user_agent if context else None,
            device_type=context.device_type if context else None,
            os_version=context.os_version if context else None,
        )

    def finish(self, result: str, *, error: Exception | None = None, response: Any = None) -> None:
        usage = extract_usage(response) or self.usage
        usage_source = "provider" if usage else "estimated"
        usage = usage or {"prompt_tokens": self.estimated_prompt_tokens, "completion_tokens": 0, "total_tokens": self.estimated_prompt_tokens}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
        context = get_audit_context()
        event = "request_cancelled" if result == "cancelled" else ("request_failed" if result in {"failed", "partial"} else "request_finished")
        emit_event(
            event, request_id=self.request_id,
            parent_task_id=context.task_id if context else None,
            session_id=context.session_id if context else None,
            source=context.source if context else "backend",
            entrypoint=context.entrypoint if context else "conversation",
            provider=self.provider, requested_model=self.requested_model,
            actual_model=(
                _attr(response, "model")
                or (response.get("model") if isinstance(response, dict) else None)
                or self.requested_model
            ),
            base_url_host=_host(self.base_url), request_type=self.request_type,
            stream=self.stream, attempt=self.attempt, started_at=self.started_at,
            finished_at=_now(), latency_ms=round((time.monotonic() - self.started_monotonic) * 1000),
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=total_tokens, usage_source=usage_source, result=result,
            error_type=type(error).__name__ if error else None,
        )
        record_usage(total_tokens)
