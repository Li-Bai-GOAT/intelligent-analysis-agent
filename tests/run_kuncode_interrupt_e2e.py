"""Live DataAgent E2E: interrupt a real KunCode run and prove no residue.

Requires the main API, SandboxManager, PostgreSQL, Redis, and Docker Desktop.
The script creates and removes its own user/session/container.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


BASE_URL = "http://127.0.0.1:8090/api"


def _docker(*arguments: str) -> str:
    completed = subprocess.run(
        ["docker", *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout


def _sandbox_containers() -> list[tuple[str, str, str]]:
    output = _docker(
        "ps",
        "--filter",
        "name=data-sandbox-",
        "--format",
        "{{.ID}}|{{.Image}}|{{.Names}}",
    )
    return [tuple(line.split("|", 2)) for line in output.splitlines() if line]


async def _delete_test_user(username: str) -> None:
    from app.database import close_db, init_db
    from app.models.user import User

    await init_db()
    await User.filter(username=username).delete()
    await close_db()


async def _run(username: str, password: str) -> None:
    session_id: str | None = None
    container_id: str | None = None
    stream_events: list[dict] = []
    process_started = asyncio.Event()

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
        register = await client.post(
            f"{BASE_URL}/auth/register",
            json={"username": username, "password": password},
        )
        register.raise_for_status()
        login = await client.post(
            f"{BASE_URL}/auth/login",
            json={"username": username, "password": password},
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(f"{BASE_URL}/conversation/sessions", headers=headers)
        create.raise_for_status()
        session_id = create.json()["session_id"]

        async def consume_chat() -> None:
            async with httpx.AsyncClient(timeout=None) as stream_client:
                async with stream_client.stream(
                    "POST",
                    f"{BASE_URL}/conversation/chat",
                    headers=headers,
                    json={
                        "session_id": session_id,
                        "execution_mode": "kuncode",
                        "message": (
                            "Use the shell tool immediately to execute exactly `sleep 120`, "
                            "wait for it to finish, and do not replace it with an explanation."
                        ),
                    },
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        event = json.loads(line[6:])
                        stream_events.append(event)
                        if "[KunCode] process started" in str(event.get("content", "")):
                            process_started.set()

        chat_task = asyncio.create_task(consume_chat())
        cleanup_error: Exception | None = None
        try:
            await asyncio.wait_for(process_started.wait(), timeout=120.0)

            before = ""
            container_name = None
            for _ in range(100):
                for candidate_id, _, candidate_name in _sandbox_containers():
                    candidate_top = _docker(
                        "top",
                        candidate_id,
                        "-eo",
                        "pid,ppid,pgid,stat,args",
                    )
                    if "kuncode" in candidate_top.lower():
                        container_id = candidate_id
                        container_name = candidate_name
                        before = candidate_top
                        break
                if container_id:
                    break
                await asyncio.sleep(0.1)
            if container_id is None:
                raise AssertionError("KunCode started but no container had a KunCode process")
            container_image_id = _docker(
                "inspect",
                container_id,
                "--format",
                "{{.Image}}",
            ).strip()
            latest_image_id = _docker(
                "image",
                "inspect",
                "agentscope/runtime-sandbox-data_analysis:latest",
                "--format",
                "{{.Id}}",
            ).strip()
            if container_image_id != latest_image_id:
                raise AssertionError(
                    f"sandbox did not use latest image: container={container_image_id} "
                    f"latest={latest_image_id}"
                )

            # Give the real model a short window to spawn its requested shell
            # command, then capture the authoritative container process tree.
            await asyncio.sleep(5.0)
            before = _docker(
                "top",
                container_id,
                "-eo",
                "pid,ppid,pgid,stat,args",
            )
            if "kuncode" not in before.lower():
                raise AssertionError(f"KunCode process missing before interrupt:\n{before}")

            interrupt = await client.post(
                f"{BASE_URL}/conversation/session/{session_id}/interrupt",
                headers=headers,
            )
            interrupt.raise_for_status()
            interrupt_result = interrupt.json()
            if not interrupt_result.get("termination_confirmed"):
                raise AssertionError(f"termination was not confirmed: {interrupt_result}")
            execution_id = interrupt_result.get("execution_id")
            if not execution_id:
                raise AssertionError(f"interrupt response omitted execution_id: {interrupt_result}")
            sandbox_id = interrupt_result.get("sandbox_id")
            if not sandbox_id or sandbox_id != container_name:
                raise AssertionError(
                    f"interrupt response sandbox mismatch: response={sandbox_id} docker={container_name}"
                )

            await asyncio.wait_for(chat_task, timeout=30.0)

            from app.config import settings

            manager_headers = (
                {"Authorization": f"Bearer {settings.SANDBOX_BEARER_TOKEN}"}
                if settings.SANDBOX_BEARER_TOKEN
                else {}
            )
            status = await client.get(
                f"{settings.SANDBOX_BASE_URL}/sandbox/{sandbox_id}/fastapi/"
                f"kuncode/process/{execution_id}",
                headers=manager_headers,
            )
            status.raise_for_status()
            process_status = status.json()
            if process_status.get("active") or not process_status.get("termination_confirmed"):
                raise AssertionError(f"sandbox still reports an active process: {process_status}")

            after = _docker(
                "top",
                container_id,
                "-eo",
                "pid,ppid,pgid,stat,args",
            )
            residual = [
                line
                for line in after.splitlines()[1:]
                if "kuncode" in line.lower() or "sleep 120" in line.lower()
            ]
            if residual:
                raise AssertionError(f"residual KunCode process found: {residual}")

            reasons = {
                event.get("termination_reason")
                for event in stream_events
                if event.get("termination_reason")
            }
            if "cancelled" not in reasons:
                raise AssertionError(f"stream did not preserve cancelled reason: {reasons}")

            print(json.dumps({
                "success": True,
                "session_id": session_id,
                "container_id": container_id,
                "container_image_id": container_image_id,
                "execution_id": execution_id,
                "interrupt": interrupt_result,
                "process_status": process_status,
                "before_had_kuncode": True,
                "residual_processes": residual,
                "stream_termination_reasons": sorted(reasons),
            }, ensure_ascii=False, indent=2))
        finally:
            if not chat_task.done():
                chat_task.cancel()
                try:
                    await chat_task
                except asyncio.CancelledError:
                    pass
            if session_id:
                try:
                    cleanup = await client.delete(
                        f"{BASE_URL}/sessions/{session_id}",
                        headers=headers,
                    )
                    cleanup.raise_for_status()
                except Exception as exc:
                    cleanup_error = exc
            if cleanup_error is not None:
                raise cleanup_error



async def main() -> None:
    username = f"e2e_interrupt_{uuid.uuid4().hex[:12]}"
    password = f"T3st-{uuid.uuid4().hex}!"
    try:
        await _run(username, password)
    finally:
        await _delete_test_user(username)


if __name__ == "__main__":
    started = time.monotonic()
    asyncio.run(main())
    print(f"elapsed_seconds={time.monotonic() - started:.2f}")
