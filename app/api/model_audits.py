# -*- coding: utf-8 -*-
"""Protected model-call audit queries."""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_admin_user
from app.models.user import User
from app.observability.model_audit import read_audits

router = APIRouter(prefix="/admin", tags=["模型审计"])


@router.get("/model-audits", summary="查询模型调用审计")
async def list_model_audits(
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    source: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    result: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(get_admin_user),
):
    filters = {
        "start_time": start_time,
        "end_time": end_time,
        "provider": provider,
        "model": model,
        "source": source,
        "session_id": session_id,
        "parent_task_id": task_id,
        "request_id": request_id,
        "result": result,
    }
    items, total = read_audits(filters, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
