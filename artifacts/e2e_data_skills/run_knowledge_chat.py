from __future__ import annotations

import json
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8090/api"
auth = json.loads(Path(r"C:\tmp\dataagent-e2e-auth.json").read_text(encoding="utf-8"))
headers = {"Authorization": f"Bearer {auth['access_token']}", "Accept": "text/event-stream"}

with httpx.Client(headers=headers, timeout=30) as client:
    response = client.post(f"{BASE}/conversation/sessions")
    response.raise_for_status()
    session_id = response.json()["session_id"]

payload = {
    "session_id": session_id,
    "message": "请必须调用 search_knowledge 工具检索 E2E-WEIGHT-ZERO-731，然后回答加权平均公式以及权重合计为零时如何处理。不要调用 KunCode。",
    "file_ids": [],
    "execution_mode": "auto",
}
events: list[dict] = []
with httpx.Client(headers=headers, timeout=httpx.Timeout(300, connect=30)) as client:
    with client.stream("POST", f"{BASE}/conversation/chat", json=payload) as response:
        response.raise_for_status()
        data_lines: list[str] = []
        for line in response.iter_lines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif not line and data_lines:
                event = json.loads("\n".join(data_lines))
                data_lines = []
                events.append(event)
                if event.get("type") == "end":
                    break

tool_calls = [event for event in events if event.get("type") == "tool_call"]
tool_results = [event for event in events if event.get("type") == "tool_result"]
texts = "\n".join(str(event.get("content", "")) for event in events)
result = {
    "session_id": session_id,
    "event_types": [event.get("type") for event in events],
    "tool_names": [event.get("content") or event.get("name") for event in tool_calls],
    "has_search_call": any("search_knowledge" in json.dumps(event, ensure_ascii=False) for event in tool_calls),
    "has_matching_result": any("[E2E] 加权平均公式" in json.dumps(event, ensure_ascii=False) for event in tool_results),
    "answer_mentions_zero_weight": "零" in texts and ("未定义" in texts or "不能" in texts),
    "has_end": bool(events and events[-1].get("type") == "end"),
    "errors": [event.get("content") for event in events if event.get("type") == "error"],
}
assert result["has_search_call"] and result["has_matching_result"] and result["answer_mentions_zero_weight"] and result["has_end"] and not result["errors"], result
(ROOT / "knowledge_chat_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
(ROOT / "knowledge_chat_events.jsonl").write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
