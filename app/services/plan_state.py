# -*- coding: utf-8 -*-
"""Canonical plan state helpers shared by AgentScope and the plans API."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal


PlanState = Literal["todo", "in_progress", "done", "abandoned"]
TERMINAL_PLAN_STATES: frozenset[str] = frozenset({"done", "abandoned"})

# Older UI and stream terminology leaked into persisted AgentScope state.
# Keep read compatibility while writing only AgentScope's canonical values.
_PLAN_STATE_ALIASES = {
    "pending": "todo",
    "running": "in_progress",
    "completed": "done",
    "failed": "abandoned",
    "cancelled": "abandoned",
}
_VALID_PLAN_STATES = frozenset({"todo", "in_progress", "done", "abandoned"})


def normalize_plan_state(value: object, *, default: PlanState = "todo") -> PlanState:
    """Return an AgentScope-compatible plan or subtask state."""
    candidate = str(value or "").strip().lower()
    candidate = _PLAN_STATE_ALIASES.get(candidate, candidate)
    if candidate in _VALID_PLAN_STATES:
        return candidate  # type: ignore[return-value]
    return default


def normalize_terminal_plan_state(
    value: object,
    *,
    default: Literal["done", "abandoned"] = "done",
) -> Literal["done", "abandoned"]:
    """Normalize a ``finish_plan`` state to one of its two valid outcomes."""
    normalized = normalize_plan_state(value, default=default)
    return normalized if normalized in TERMINAL_PLAN_STATES else default


def normalize_plan_snapshot(plan: dict[str, Any]) -> dict[str, Any]:
    """Copy a serialized plan and normalize its own and subtask states."""
    normalized = deepcopy(plan)
    if "state" in normalized:
        normalized["state"] = normalize_plan_state(normalized["state"])

    subtasks = normalized.get("subtasks")
    if isinstance(subtasks, list):
        for subtask in subtasks:
            if isinstance(subtask, dict) and "state" in subtask:
                subtask["state"] = normalize_plan_state(subtask["state"])
    return normalized


def normalize_plan_notebook_state(state: dict[str, Any]) -> dict[str, Any]:
    """Migrate persisted AgentScope plan state without mutating its input.

    A completed plan must live in history, not in ``current_plan``.  Keeping
    it active makes the next turn attempt to restore an already finished plan
    and prevents the user from starting a new one.
    """
    normalized = deepcopy(state)
    notebook = normalized.get("plan_notebook")
    if not isinstance(notebook, dict):
        return normalized

    current_plan = notebook.get("current_plan")
    if isinstance(current_plan, dict):
        current_plan = normalize_plan_snapshot(current_plan)
        if current_plan.get("state") in TERMINAL_PLAN_STATES:
            notebook["last_finished_plan"] = current_plan
            notebook["current_plan"] = None
        else:
            notebook["current_plan"] = current_plan

    last_finished_plan = notebook.get("last_finished_plan")
    if isinstance(last_finished_plan, dict):
        notebook["last_finished_plan"] = normalize_plan_snapshot(last_finished_plan)

    storage = notebook.get("storage")
    plans = storage.get("plans") if isinstance(storage, dict) else None
    if isinstance(plans, dict):
        for plan_id, stored_plan in plans.items():
            if isinstance(stored_plan, dict):
                plans[plan_id] = normalize_plan_snapshot(stored_plan)
    elif isinstance(plans, list):
        for index, stored_plan in enumerate(plans):
            if isinstance(stored_plan, dict):
                plans[index] = normalize_plan_snapshot(stored_plan)

    return normalized
