"""OS-level integration coverage for KunCode process-group cancellation.

This test is intentionally skipped on Windows because the production router
runs inside the Linux sandbox image where POSIX process groups are available.
Run it in the image/CI Linux environment with:

    python -m unittest tests.test_kuncode_process_integration -v
"""

import asyncio
import contextlib
import importlib.util
import os
import time
import unittest
from pathlib import Path


def _load_router():
    path = Path(os.getenv(
        "DATAAGENT_KUNCODE_ROUTER_PATH",
        str(
            Path(__file__).resolve().parents[1]
            / "sandbox_image"
            / "routers"
            / "kuncode_stream.py"
        ),
    ))
    spec = importlib.util.spec_from_file_location("integration_kuncode_router", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(os.name == "posix", "production process groups require Linux/POSIX")
class KunCodeProcessIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_interrupt_leaves_no_process_group(self):
        router = _load_router()
        execution_id = "integration-no-residual"
        request = router.KunCodeRequest(
            prompt="unused",
            execution_id=execution_id,
            deadline_at_ms=int((time.time() + 60) * 1000),
        )

        async def consume():
            return [
                event
                async for event in router._stream_kuncode_output(
                    ["sh", "-c", "setsid sh -c 'sleep 120' & wait"],
                    request,
                )
            ]

        consumer = asyncio.create_task(consume())
        pid = None
        try:
            for _ in range(100):
                status = await router.kuncode_process_status(execution_id)
                if status.get("active"):
                    pid = status["pid"]
                    break
                await asyncio.sleep(0.05)
            self.assertIsNotNone(pid, "test subprocess never became active")

            result = await router.cancel_kuncode(router.KunCodeCancelRequest(
                execution_id=execution_id,
                grace_seconds=0.2,
                termination_reason="cancelled",
            ))
            self.assertTrue(result["termination_confirmed"])
            self.assertFalse(result["active"])

            events = await asyncio.wait_for(consumer, timeout=5.0)
            self.assertIn('"termination_reason": "cancelled"', "".join(events))
            with self.assertRaises(ProcessLookupError):
                os.killpg(pid, 0)

            status = await router.kuncode_process_status(execution_id)
            self.assertFalse(status["active"])
            self.assertTrue(status["termination_confirmed"])
        finally:
            if not consumer.done():
                await router.cancel_kuncode(router.KunCodeCancelRequest(
                    execution_id=execution_id,
                    grace_seconds=0.1,
                ))
                consumer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await consumer

    async def test_deadline_timeout_kills_escaped_process_group(self):
        router = _load_router()
        execution_id = "integration-timeout"
        request = router.KunCodeRequest(
            prompt="unused",
            execution_id=execution_id,
            deadline_at_ms=int((time.time() + 0.4) * 1000),
        )
        events = await asyncio.wait_for(
            _collect(router, request, [
                "sh",
                "-c",
                "setsid sh -c 'sleep 120' & wait",
            ]),
            timeout=10.0,
        )

        rendered = "".join(events)
        self.assertIn('"termination_reason": "timeout"', rendered)
        status = await router.kuncode_process_status(execution_id)
        self.assertFalse(status["active"])
        self.assertTrue(status["termination_confirmed"])
        self.assertEqual(status["residual_pids"], [])

    async def test_nonzero_exit_is_process_error(self):
        router = _load_router()
        execution_id = "integration-process-error"
        request = router.KunCodeRequest(
            prompt="unused",
            execution_id=execution_id,
            deadline_at_ms=int((time.time() + 10) * 1000),
        )
        events = await _collect(router, request, ["sh", "-c", "exit 7"])

        rendered = "".join(events)
        self.assertIn('"termination_reason": "process_error"', rendered)
        self.assertIn('"exit_code": 7', rendered)
        status = await router.kuncode_process_status(execution_id)
        self.assertFalse(status["active"])
        self.assertTrue(status["termination_confirmed"])


async def _collect(router, request, command):
    return [
        event
        async for event in router._stream_kuncode_output(command, request)
    ]
