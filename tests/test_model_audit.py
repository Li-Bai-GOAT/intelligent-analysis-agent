# -*- coding: utf-8 -*-
import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.config import settings
from app.observability import model_audit
from app.observability.model_audit import (
    AuditRequest,
    ModelAdmissionError,
    admission_check,
    audit_context,
    emit_event,
    extract_usage,
    read_audits,
    request_slot,
)
from app.services.model_factory import RetryingStreamingModel


class _Usage:
    input_tokens = 12
    output_tokens = 8
    total_tokens = 20


class _Response:
    usage = _Usage()
    model = "deepseek-v4-flash"


class ModelAuditTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original = {
            "MODEL_AUDIT_ENABLED": settings.MODEL_AUDIT_ENABLED,
            "MODEL_AUDIT_LOG_PATH": settings.MODEL_AUDIT_LOG_PATH,
            "MODEL_AUDIT_RETENTION_DAYS": settings.MODEL_AUDIT_RETENTION_DAYS,
            "ALLOWED_MODEL_PROVIDERS": settings.ALLOWED_MODEL_PROVIDERS,
            "ALLOWED_MODEL_NAMES": settings.ALLOWED_MODEL_NAMES,
            "DISABLE_MIMO": settings.DISABLE_MIMO,
            "MAX_REQUEST_TOKENS": settings.MAX_REQUEST_TOKENS,
            "MODEL_MAX_CONCURRENCY": settings.MODEL_MAX_CONCURRENCY,
        }
        settings.MODEL_AUDIT_ENABLED = True
        settings.MODEL_AUDIT_LOG_PATH = str(Path(self.tempdir.name) / "requests.log")
        settings.MODEL_AUDIT_RETENTION_DAYS = 90
        settings.ALLOWED_MODEL_PROVIDERS = "deepseek"
        settings.ALLOWED_MODEL_NAMES = "deepseek-v4-flash"
        settings.DISABLE_MIMO = True
        settings.MAX_REQUEST_TOKENS = 200000
        settings.MODEL_MAX_CONCURRENCY = 4
        model_audit._active_requests = 0
        model_audit._daily_usage.clear()

    def tearDown(self):
        for key, value in self.original.items():
            setattr(settings, key, value)
        model_audit._active_requests = 0
        self.tempdir.cleanup()

    def _events(self):
        path = Path(settings.MODEL_AUDIT_LOG_PATH)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_events_redact_sensitive_fields_and_keep_usage_fields(self):
        emit_event(
            "request_finished",
            request_id="req-1",
            prompt="do not persist this prompt",
            api_key="sk-secret",
            authorization="Bearer secret",
            headers={"Cookie": "session=secret"},
            total_tokens=20,
        )
        raw = Path(settings.MODEL_AUDIT_LOG_PATH).read_text(encoding="utf-8")
        self.assertNotIn("do not persist this prompt", raw)
        self.assertNotIn("sk-secret", raw)
        self.assertNotIn("Bearer secret", raw)
        event = self._events()[0]
        self.assertEqual(event["total_tokens"], 20)
        self.assertEqual(event["prompt"], "[REDACTED]")
        self.assertEqual(event["headers"], "[REDACTED]")

    def test_allowlist_and_mimo_admission(self):
        admission_check("deepseek", "deepseek-v4-flash", 10)
        with self.assertRaises(ModelAdmissionError):
            admission_check("openai", "gpt-4o", 10)
        with self.assertRaises(ModelAdmissionError):
            admission_check("mimo", "mimo-v2.5-pro", 10)

    def test_concurrency_slot_is_enforced_atomically(self):
        settings.MODEL_MAX_CONCURRENCY = 1

        async def scenario():
            first = request_slot()
            await first.__aenter__()
            second = request_slot()
            try:
                with self.assertRaises(ModelAdmissionError):
                    await second.__aenter__()
            finally:
                await first.__aexit__(None, None, None)

        asyncio.run(scenario())

    def test_extract_usage_accepts_agentscope_style_usage(self):
        self.assertEqual(
            extract_usage(_Response()),
            {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        )

    def test_query_filters_before_pagination(self):
        emit_event("request_started", request_id="req-a", provider="deepseek", requested_model="deepseek-v4-flash", source="backend", started_at="2026-10-08T00:00:00Z")
        emit_event("request_finished", request_id="req-a", provider="deepseek", requested_model="deepseek-v4-flash", source="backend", result="success", started_at="2026-10-08T00:00:00Z", finished_at="2026-10-08T00:00:01Z")
        emit_event("request_finished", request_id="req-b", provider="openai", requested_model="gpt-4o", source="backend", result="success", started_at="2026-10-08T00:00:02Z", finished_at="2026-10-08T00:00:03Z")
        items, total = read_audits({"model": "deepseek-v4-flash", "start_time": "2026-10-08T00:00:00Z"}, limit=1, offset=0)
        self.assertEqual(total, 2)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["request_id"], "req-a")

    def test_audit_log_rotates_daily_reads_rotated_files_and_cleans_expired_files(self):
        emit_event("request_finished", request_id="req-old", result="success")
        path = Path(settings.MODEL_AUDIT_LOG_PATH)
        old_timestamp = (datetime.now(timezone.utc) - timedelta(days=2)).timestamp()
        os.utime(path, (old_timestamp, old_timestamp))

        emit_event("request_finished", request_id="req-current", result="success")
        rotated = list(path.parent.glob("requests-*.log"))
        self.assertEqual(len(rotated), 1)
        items, total = read_audits({}, limit=10, offset=0)
        self.assertEqual(total, 2)
        self.assertEqual({item["request_id"] for item in items}, {"req-old", "req-current"})

        expired = path.with_name("requests-2020-01-01.log")
        expired.write_text("{}\n", encoding="utf-8")
        settings.MODEL_AUDIT_RETENTION_DAYS = 1
        emit_event("request_finished", request_id="req-cleanup", result="success")
        self.assertFalse(expired.exists())


class DictMixinUsageTests(unittest.TestCase):
    """AgentScope's ChatResponse/ChatUsage subclass dict via DictMixin.

    DictMixin.__getattr__ is dict.__getitem__, so getattr(obj, name, default)
    raises KeyError instead of returning the default. These tests pin the real
    provider types, which the plain-object mocks above cannot cover.
    """

    def test_extract_usage_accepts_agentscope_chat_response(self):
        from agentscope.model._model_response import ChatResponse
        from agentscope.model._model_usage import ChatUsage

        response = ChatResponse(
            content=[{"type": "text", "text": "hi"}],
            usage=ChatUsage(input_tokens=12, output_tokens=8, time=0.5),
        )
        self.assertEqual(
            extract_usage(response),
            {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        )

    def test_extract_usage_accepts_chat_usage_without_total(self):
        from agentscope.model._model_usage import ChatUsage

        self.assertEqual(
            extract_usage(ChatUsage(input_tokens=3, output_tokens=4, time=0.1)),
            {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        )

    def test_extract_usage_returns_none_for_response_without_usage(self):
        from agentscope.model._model_response import ChatResponse

        self.assertIsNone(
            extract_usage(ChatResponse(content=[{"type": "text", "text": "hi"}], usage=None))
        )

    def test_finish_survives_agentscope_response(self):
        from agentscope.model._model_response import ChatResponse
        from agentscope.model._model_usage import ChatUsage

        with tempfile.TemporaryDirectory() as directory:
            previous_path = settings.MODEL_AUDIT_LOG_PATH
            settings.MODEL_AUDIT_LOG_PATH = str(Path(directory) / "requests.log")
            try:
                audit = AuditRequest(
                    provider="mimo",
                    requested_model="mimo-v2.6-pro",
                    base_url="https://api.example.com/v1",
                    stream=False,
                    estimated_prompt_tokens=99,
                )
                audit.start()
                audit.finish(
                    "success",
                    response=ChatResponse(
                        content=[{"type": "text", "text": "hi"}],
                        usage=ChatUsage(input_tokens=12, output_tokens=8, time=0.5),
                    ),
                )
                events = [
                    json.loads(line)
                    for line in Path(settings.MODEL_AUDIT_LOG_PATH).read_text(encoding="utf-8").splitlines()
                ]
                finished = [event for event in events if event["event"] == "request_finished"]
                self.assertEqual(len(finished), 1)
                self.assertEqual(finished[0]["prompt_tokens"], 12)
                self.assertEqual(finished[0]["completion_tokens"], 8)
                self.assertEqual(finished[0]["total_tokens"], 20)
                self.assertEqual(finished[0]["usage_source"], "provider")
            finally:
                settings.MODEL_AUDIT_LOG_PATH = previous_path

    def test_finish_falls_back_to_estimate_without_usage(self):
        from agentscope.model._model_response import ChatResponse

        with tempfile.TemporaryDirectory() as directory:
            previous_path = settings.MODEL_AUDIT_LOG_PATH
            settings.MODEL_AUDIT_LOG_PATH = str(Path(directory) / "requests.log")
            try:
                audit = AuditRequest(
                    provider="mimo",
                    requested_model="mimo-v2.6-pro",
                    base_url="https://api.example.com/v1",
                    stream=False,
                    estimated_prompt_tokens=99,
                )
                audit.finish(
                    "success",
                    response=ChatResponse(content=[{"type": "text", "text": "hi"}], usage=None),
                )
                finished = [
                    json.loads(line)
                    for line in Path(settings.MODEL_AUDIT_LOG_PATH).read_text(encoding="utf-8").splitlines()
                    if json.loads(line)["event"] == "request_finished"
                ]
                self.assertEqual(finished[0]["prompt_tokens"], 99)
                self.assertEqual(finished[0]["usage_source"], "estimated")
            finally:
                settings.MODEL_AUDIT_LOG_PATH = previous_path


class RetryingModelAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_retries_keep_one_logical_request_id_and_increment_attempt(self):
        settings.MODEL_AUDIT_ENABLED = True
        with tempfile.TemporaryDirectory() as directory:
            previous_path = settings.MODEL_AUDIT_LOG_PATH
            previous_provider = settings.ALLOWED_MODEL_PROVIDERS
            previous_names = settings.ALLOWED_MODEL_NAMES
            settings.MODEL_AUDIT_LOG_PATH = str(Path(directory) / "requests.log")
            settings.ALLOWED_MODEL_PROVIDERS = "deepseek"
            settings.ALLOWED_MODEL_NAMES = "deepseek-v4-flash"

            class FakeModel:
                stream = True

                def __init__(self):
                    self.calls = 0

                async def __call__(self, *_args, **_kwargs):
                    self.calls += 1
                    if self.calls == 1:
                        async def broken():
                            yield {"text": "partial"}
                            raise httpx.ReadError("connection closed")
                        return broken()

                    async def healthy():
                        yield {"text": "done", "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}}
                    return healthy()

            try:
                async with audit_context(trace_id="trace-test", user_id="user-test"):
                    model = RetryingStreamingModel(
                        FakeModel(),
                        max_retries=1,
                        provider="deepseek",
                        requested_model="deepseek-v4-flash",
                    )
                    response = await model([{"role": "user", "content": "hello"}])
                    chunks = [chunk async for chunk in response]
                events = [json.loads(line) for line in Path(settings.MODEL_AUDIT_LOG_PATH).read_text(encoding="utf-8").splitlines()]
                starts = [event for event in events if event["event"] == "request_started"]
                self.assertEqual(len(chunks), 2)
                self.assertEqual(len(starts), 2)
                self.assertEqual({event["request_id"] for event in starts}, {starts[0]["request_id"]})
                self.assertEqual([event["attempt"] for event in starts], [1, 2])
                self.assertEqual([event["event"] for event in events].count("request_failed"), 1)
                self.assertEqual([event["event"] for event in events].count("request_finished"), 1)
            finally:
                settings.MODEL_AUDIT_LOG_PATH = previous_path
                settings.ALLOWED_MODEL_PROVIDERS = previous_provider
                settings.ALLOWED_MODEL_NAMES = previous_names


if __name__ == "__main__":
    unittest.main()
