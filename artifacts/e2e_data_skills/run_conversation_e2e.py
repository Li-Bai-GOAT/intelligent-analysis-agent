from __future__ import annotations

import json
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8090/api"
AUTH_PATH = Path(r"C:\tmp\dataagent-e2e-auth.json")
RUN_PATH = ROOT / "conversation_run.json"
EVENTS_PATH = ROOT / "conversation_events.jsonl"


def require(response: httpx.Response):
    if response.status_code >= 400:
        raise RuntimeError(f"{response.request.method} {response.request.url.path} -> {response.status_code}: {response.text[:500]}")
    return response


def main() -> None:
    auth = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    events: list[dict] = []
    with httpx.Client(headers=headers, timeout=60) as client:
        session = require(client.post(f"{BASE}/conversation/sessions")).json()
        session_id = session["session_id"]
        source = ROOT / "e2e_dirty_sales.csv"
        with source.open("rb") as handle:
            uploaded = require(
                client.post(
                    f"{BASE}/files/upload",
                    params={"session_id": session_id},
                    files={"files": (source.name, handle, "text/csv")},
                )
            ).json()
        file_id = str(uploaded[0]["id"])

    prompt = """
这是端到端验收任务。必须实际使用已注入的 tabular-data-cleaning 和 business-metric-formulas Skill，不要只口头说明。

输入文件：/workspace/data/uploads/e2e_dirty_sales.csv

步骤：
1. 按 tabular-data-cleaning Skill 运行 scripts/profile_and_clean.py，业务键 order_id，日期列 order_date，数值列 revenue,cost,visits,orders,score,weight，分类列 region，删除完全重复；输出到 /workspace/e2e_results/cleaning。
2. 使用清洗后的 CSV，按 business-metric-formulas Skill 运行 scripts/calculate_metrics.py，按 region 分组；输出到 /workspace/e2e_results/metrics。
3. 核对整体收入 12800、成本 4720、毛利 8080、毛利率 0.63125、转化率约 0.0977777778、加权平均约 4.2307692308。
4. 最终明确列出所有生成文件的 /workspace 相对路径，并说明是否全部核对通过。不得覆盖输入文件。
""".strip()

    payload = {
        "session_id": session_id,
        "message": prompt,
        "file_ids": [file_id],
        "execution_mode": "kuncode",
    }
    with httpx.Client(headers={**headers, "Accept": "text/event-stream"}, timeout=httpx.Timeout(900, connect=30)) as client:
        with client.stream("POST", f"{BASE}/conversation/chat", json=payload) as response:
            require(response)
            data_lines: list[str] = []
            for line in response.iter_lines():
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif not line and data_lines:
                    raw = "\n".join(data_lines)
                    data_lines = []
                    event = json.loads(raw)
                    events.append(event)
                    if event.get("type") == "end":
                        break

    EVENTS_PATH.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events), encoding="utf-8")
    event_types = [event.get("type") for event in events]
    tool_calls = [event for event in events if event.get("type") == "tool_call"]
    tool_results = [event for event in events if event.get("type") == "tool_result"]
    calls = {event.get("tool_id") for event in tool_calls}
    results = {event.get("tool_id") for event in tool_results}
    generated = []
    for event in events:
        generated.extend(event.get("generated_files") or [])
    run = {
        "session_id": session_id,
        "file_id": file_id,
        "event_types": event_types,
        "has_end": bool(event_types and event_types[-1] == "end"),
        "tool_ids_match": bool(calls) and calls.issubset(results),
        "tool_ids": sorted(str(item) for item in calls if item),
        "generated_files": sorted(set(generated)),
        "errors": [event.get("content") for event in events if event.get("type") == "error"],
    }
    RUN_PATH.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(run, ensure_ascii=False))


if __name__ == "__main__":
    main()
