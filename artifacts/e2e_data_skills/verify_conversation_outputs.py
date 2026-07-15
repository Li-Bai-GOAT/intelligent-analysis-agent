from __future__ import annotations

import json
import math
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8090/api"
auth = json.loads(Path(r"C:\tmp\dataagent-e2e-auth.json").read_text(encoding="utf-8"))
run = json.loads((ROOT / "conversation_run.json").read_text(encoding="utf-8"))
expected = json.loads((ROOT / "expected_results.json").read_text(encoding="utf-8"))
events = [json.loads(line) for line in (ROOT / "conversation_events.jsonl").read_text(encoding="utf-8").splitlines()]
headers = {"Authorization": f"Bearer {auth['access_token']}"}


def get(client: httpx.Client, path: str, **kwargs):
    response = client.get(f"{BASE}{path}", **kwargs)
    response.raise_for_status()
    return response.json()


with httpx.Client(headers=headers, timeout=30) as client:
    binding = get(client, f"/files/sandbox/{run['session_id']}/binding")
    cleaning = json.loads(
        get(
            client,
            f"/files/sandbox/{run['session_id']}/workspace/content",
            params={"path": "e2e_results/cleaning/data_quality_summary.json"},
        )["content"]
    )
    metrics = json.loads(
        get(
            client,
            f"/files/sandbox/{run['session_id']}/workspace/content",
            params={"path": "e2e_results/metrics/metric_results.json"},
        )["content"]
    )["overall"]
    session = get(client, f"/sessions/{run['session_id']}")
    task = get(client, f"/conversation/session/{run['session_id']}/task")

last_tool_output = next(event["content"] for event in reversed(events) if event["type"] == "tool_result")
checks = {
    "has_end": run["has_end"],
    "tool_ids_match": run["tool_ids_match"],
    "no_error_events": not run["errors"],
    "generated_file_count": len(run["generated_files"]) == 5,
    "normal_injected_paths": "scripts\\profile_and_clean.py" not in last_tool_output and "scripts\\calculate_metrics.py" not in last_tool_output,
    "cleaned_rows": cleaning["cleaned_rows"] == expected["cleaned_rows"],
    "duplicates": cleaning["exact_duplicate_rows_found"] == expected["exact_duplicate_rows_found"],
    "gross_profit": math.isclose(metrics["gross_profit"]["value"], expected["gross_profit"]),
    "gross_margin": math.isclose(metrics["gross_margin"]["value"], expected["gross_margin"]),
    "conversion_rate": math.isclose(metrics["conversion_rate"]["value"], expected["conversion_rate"]),
    "weighted_average": math.isclose(metrics["weighted_average"]["value"], expected["weighted_average"]),
    "session_history_persisted": len(session["messages"]) >= 4,
    "task_not_running": task["has_active_task"] is False,
    "binding_active": binding["is_active"] is True,
}
assert all(value is True for value in checks.values()), checks
result = {"status": "ok", "checks": checks, "sandbox_id": binding["sandbox_id"], "session_id": run["session_id"], "generated_files": run["generated_files"]}
(ROOT / "verification_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
