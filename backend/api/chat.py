# -*- coding: utf-8 -*-
"""问答接口（SSE 流式）

事件协议（前端按 event 字段分派）：

    event: sources   data: [{title, source, score, coverage}, ...]   引用来源
    event: delta     data: {"text": "..."}                            回答增量
    event: done      data: {}                                         正常结束
    event: error     data: {"message": "..."}                         错误提示

引用来源在流开始前即可确定，因此率先推送，前端可先把引用区渲染出来。
"""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.deps import kb_manager, settings_store, storage
from core.llm import LLMClient
from core.pipeline import RAGPipeline, Answer

router = APIRouter(prefix="/api", tags=["问答"])


class ChatRequest(BaseModel):
    kb_id: str
    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


def _sources_payload(hits) -> list[dict]:
    """把检索结果转成前端可直接渲染的结构"""
    return [
        {
            "title": hit.chunk.title,
            "source": hit.chunk.source,
            "section": hit.chunk.section,
            "text": hit.chunk.text,
            "score": round(hit.score, 4),
            "coverage": round(hit.coverage, 2),
        }
        for hit in hits
    ]


def _build_pipeline(kb_id: str, top_k: int | None) -> RAGPipeline:
    """按当前配置组装流水线"""
    settings = settings_store.get()
    profile = settings_store.get_llm_profile()
    return RAGPipeline(
        retriever=kb_manager.get_retriever(kb_id),
        llm=LLMClient(
            mode=profile["mode"],
            base_url=profile["base_url"],
            api_key=profile["api_key"],
            model=profile["model"],
        ),
        top_k=top_k or settings.get("top_k", 3),
    )


@router.post("/chat")
async def chat(req: ChatRequest):
    """流式问答"""
    if not storage.get_kb(req.kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    pipeline = _build_pipeline(req.kb_id, req.top_k)
    stream, hits = pipeline.ask_stream(req.question)

    def event_generator():
        # 引用来源先于正文推送
        yield {
            "event": "sources",
            "data": json.dumps(_sources_payload(hits), ensure_ascii=False),
        }
        try:
            for piece in stream:
                yield {
                    "event": "delta",
                    "data": json.dumps({"text": piece}, ensure_ascii=False),
                }
            yield {"event": "done", "data": "{}"}
        except Exception as e:
            # LLMError 已带用户可读的提示；其余异常做兜底封装
            message = getattr(e, "args", [None])[0] or str(e)
            yield {
                "event": "error",
                "data": json.dumps({"message": str(message)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())


@router.post("/chat/sync")
def chat_sync(req: ChatRequest) -> dict:
    """非流式问答，便于调试与自动化测试"""
    if not storage.get_kb(req.kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    pipeline = _build_pipeline(req.kb_id, req.top_k)
    ans: Answer = pipeline.ask(req.question)
    return {
        "answer": ans.text,
        "sources": _sources_payload(ans.sources),
        "retrieved": ans.retrieved,
    }
