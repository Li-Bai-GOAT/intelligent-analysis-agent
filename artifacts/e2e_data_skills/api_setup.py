from __future__ import annotations

import json
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8090/api"
AUTH_PATH = Path(r"C:\tmp\dataagent-e2e-auth.json")
STATE_PATH = ROOT / "api_state.json"


KNOWLEDGE = [
    {
        "title": "[E2E] 缺失值处理决策表",
        "category": "分析流程",
        "content": "缺失值处理标记 E2E-MISSING-731：先区分随机缺失、业务上不适用和采集失败。默认保留并报告；仅在明确必填且说明影响时删除；填充必须记录方法并尽量增加填充标记列。",
        "metadata": {"e2e": True, "source": "https://pandas.pydata.org/docs/user_guide/missing_data.html"},
    },
    {
        "title": "[E2E] 重复记录与业务主键",
        "category": "概念定义",
        "content": "重复判定标记 E2E-DUPLICATE-731：完全重复是规范化后所有字段相同；业务主键重复仅表示标识重复，字段可能冲突，不能在没有胜出规则时自动删除。",
        "metadata": {"e2e": True, "source": "https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.duplicated.html"},
    },
    {
        "title": "[E2E] 字段类型标准化",
        "category": "分析方法",
        "content": "类型标准化标记 E2E-TYPE-731：订单号和客户 ID 先按字符串读取以保留前导零；金额显式转数值；日期按约定格式解析；非法值转为缺失并单独计数。",
        "metadata": {"e2e": True, "source": "https://pandas.pydata.org/docs/reference/api/pandas.to_numeric.html"},
    },
    {
        "title": "[E2E] IQR 异常值候选规则",
        "category": "分析方法",
        "content": "异常值标记 E2E-IQR-731：IQR=Q3-Q1，低于 Q1-1.5*IQR 或高于 Q3+1.5*IQR 的值只标为复核候选，不自动当作错误或删除。",
        "metadata": {"e2e": True, "source": "https://numpy.org/doc/stable/reference/generated/numpy.percentile.html"},
    },
    {
        "title": "[E2E] 加权平均公式",
        "category": "计算公式",
        "content": "加权平均标记 E2E-WEIGHT-ZERO-731：加权平均=sum(value*weight)/sum(weight)。值或权重缺失的配对要报告并排除；权重合计为零时结果未定义，不得返回无穷或伪造为零。",
        "metadata": {"e2e": True, "source": "https://numpy.org/doc/stable/reference/generated/numpy.average.html"},
    },
    {
        "title": "[E2E] 同比与环比增长率",
        "category": "计算公式",
        "content": "增长率标记 E2E-GROWTH-731：(本期-基期)/基期。必须说明同比或环比、时间窗口和单位；基期为零时标为未定义并展示本期与基期原值。",
        "metadata": {"e2e": True, "source": "original example contract"},
    },
    {
        "title": "[E2E] 毛利额与毛利率",
        "category": "计算公式",
        "content": "毛利标记 E2E-MARGIN-731：示例口径毛利额=sum(收入)-sum(成本)，毛利率=毛利额/sum(收入)。必须先确认退货、税费和成本范围；收入为零时毛利率未定义。",
        "metadata": {"e2e": True, "source": "original example contract"},
    },
    {
        "title": "[E2E] 比率指标聚合原则",
        "category": "分析流程",
        "content": "比率聚合标记 E2E-RATIO-731：整体转化率应使用 sum(订单量)/sum(访问量)，不能无说明地平均各行转化率。输出分子、分母、过滤条件和零分母数量以便勾稽。",
        "metadata": {"e2e": True, "source": "original example contract"},
    },
]


def request(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, f"{BASE}{path}", **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:500]}")
    return response.json() if response.content else None


def main() -> None:
    auth = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    state = {"knowledge_ids": [], "skill_ids": {}, "agent": None, "ui_verified": False}
    with httpx.Client(headers=headers, timeout=60) as client:
        existing_knowledge = request(client, "GET", "/knowledge?limit=500&offset=0")["items"]
        by_title = {item["title"]: item for item in existing_knowledge}
        for item in KNOWLEDGE:
            existing = by_title.get(item["title"])
            if existing:
                created = existing
            else:
                created = request(client, "POST", "/knowledge", json=item)
            state["knowledge_ids"].append(created["id"])

        agents = request(client, "GET", "/sandbox/agents")
        candidates = [agent for agent in agents if agent["enabled"] and not agent["hidden"] and agent["mode"] in {"primary", "all"}]
        if not candidates:
            agent = request(
                client,
                "POST",
                "/sandbox/agents",
                json={
                    "name": "e2e-data-analyst",
                    "description": "用于验证 DataAgent 数据清洗、经营指标公式与文件交付链路的主 Agent。",
                    "mode": "primary",
                    "tools": {},
                    "permission": {},
                    "temperature": 0.1,
                    "max_steps": 30,
                    "hidden": False,
                    "content": "执行数据分析时优先使用获准的 Skill。保留原始文件，输出计算公式、中间汇总、质量报告和可复核结果文件。",
                    "enabled": True,
                },
            )
            agents = [agent]
            candidates = [agent]
        agent = candidates[0]
        state["agent"] = {"id": agent["id"], "name": agent["name"], "mode": agent["mode"]}

        existing_skills = {item["name"]: item for item in request(client, "GET", "/sandbox/skills")}
        for name in ("tabular-data-cleaning", "business-metric-formulas"):
            skill = existing_skills.get(name)
            if not skill:
                zip_path = ROOT / f"{name}.zip"
                with zip_path.open("rb") as handle:
                    skill = request(client, "POST", "/sandbox/skills/upload", files={"file": (zip_path.name, handle, "application/zip")})
            if not skill["enabled"]:
                request(client, "PATCH", f"/sandbox/skills/{skill['id']}/toggle")
            request(
                client,
                "PUT",
                f"/sandbox/skills/{skill['id']}/permissions",
                json=[{"agent_id": agent["id"], "permission": "allow"}],
            )
            refreshed = request(client, "GET", f"/sandbox/skills/{skill['id']}")
            state["skill_ids"][name] = refreshed["id"]

        state["counts"] = {
            "knowledge": len(request(client, "GET", "/knowledge?limit=500&offset=0")["items"]),
            "skills": len(request(client, "GET", "/sandbox/skills")),
            "agents": len(agents),
        }
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "knowledge_created_or_reused": len(state["knowledge_ids"]), "skills_configured": len(state["skill_ids"]), "agent": state["agent"], "counts": state["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
