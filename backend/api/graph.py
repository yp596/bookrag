# -*- coding: utf-8 -*-
"""知识图谱与任务面板接口"""

from fastapi import APIRouter
from pydantic import BaseModel

from api.deps import kb_manager, storage
from core.graph import build_graph, create_task, list_tasks, run_task

router = APIRouter(prefix="/api/kb", tags=["图谱与任务"])


@router.get("/{kb_id}/graph")
def kb_graph(kb_id: str, top_n: int = 30) -> dict:
    chunks = storage.get_chunks(kb_id)
    return build_graph(chunks, top_n=max(5, min(top_n, 100)))


class TaskIn(BaseModel):
    kind: str = "rebuild"
    payload: dict = {}


@router.get("/{kb_id}/tasks")
def tasks(kb_id: str) -> dict:
    _ = kb_id
    return {"tasks": list_tasks()}


@router.post("/{kb_id}/tasks")
def new_task(kb_id: str, req: TaskIn) -> dict:
    task = create_task(req.kind, {"kb_id": kb_id, **req.payload})

    def _do(payload: dict):
        kid = payload.get("kb_id", kb_id)
        if req.kind == "rebuild":
            kb_manager.get_retriever(kid)
            return "索引重建完成"
        return f"任务 {req.kind} 已记录"

    return run_task(task["id"], _do)
