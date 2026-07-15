from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.utils.milvus_client import milvus_client


ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8090/api"
auth = json.loads(Path(r"C:\tmp\dataagent-e2e-auth.json").read_text(encoding="utf-8"))
state = json.loads((ROOT / "api_state.json").read_text(encoding="utf-8"))
headers = {"Authorization": f"Bearer {auth['access_token']}"}


def get(client: httpx.Client, path: str):
    response = client.get(f"{BASE}{path}")
    response.raise_for_status()
    return response.json()


checks: dict[str, object] = {}
with httpx.Client(headers=headers, timeout=30) as client:
    for name, skill_id in state["skill_ids"].items():
        skill = get(client, f"/sandbox/skills/{skill_id}")
        tree = get(client, f"/sandbox/skills/{skill_id}/files")
        permission = next((item for item in skill["agent_permissions"] if item["agent_id"] == state["agent"]["id"]), None)
        file_paths: list[str] = []

        def walk(nodes):
            for node in nodes:
                if node["type"] == "file":
                    file_paths.append(node["path"].replace("\\", "/"))
                else:
                    walk(node.get("children", []))

        walk(tree["children"])
        checks[name] = {
            "enabled": skill["enabled"],
            "permission": permission["permission"] if permission else None,
            "has_skill_md": "SKILL.md" in file_paths,
            "has_script": any(path.startswith("scripts/") and path.endswith(".py") for path in file_paths),
            "files": file_paths,
        }

queries = {
    "weighted": "E2E-WEIGHT-ZERO-731 权重合计为零",
    "duplicates": "E2E-DUPLICATE-731 业务主键重复",
    "margin": "E2E-MARGIN-731 毛利率",
}
checks["milvus"] = {}
for key, query in queries.items():
    results = milvus_client.search(settings.MILVUS_COLLECTION, query, top_k=3)
    checks["milvus"][key] = [item["title"] for item in results]

for name in ("tabular-data-cleaning", "business-metric-formulas"):
    item = checks[name]
    assert item["enabled"] is True
    assert item["permission"] == "allow"
    assert item["has_skill_md"] and item["has_script"]
assert any("加权平均" in title for title in checks["milvus"]["weighted"])
assert any("重复记录" in title for title in checks["milvus"]["duplicates"])
assert any("毛利" in title for title in checks["milvus"]["margin"])
print(json.dumps({"status": "ok", "checks": checks}, ensure_ascii=False))
