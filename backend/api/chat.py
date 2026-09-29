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
    session_id: str | None = None


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
        use_qdrant=settings.get("use_qdrant", False),
    )


@router.post("/chat")
async def chat(req: ChatRequest):
    """流式问答。问答双方落库：用户提问先存，助手回答在流正常结束时存。

    中断或报错时助手侧不落库——半截回答恢复出来会被误当完整答案，
    用户提问保留，用户重问一次即可。

    session_id 缺省时记入最近会话（老客户端兼容）；传错会话 id 报 404。
    """
    if not storage.get_kb(req.kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    if req.session_id and not storage.ensure_session(req.kb_id, req.session_id):
        raise HTTPException(status_code=404, detail="会话不存在")

    storage.add_message(req.kb_id, "user", req.question, session_id=req.session_id)

    pipeline = _build_pipeline(req.kb_id, req.top_k)
    stream, hits = pipeline.ask_stream(req.question)
    sources_json = json.dumps(_sources_payload(hits), ensure_ascii=False)

    def event_generator():
        # 引用来源先于正文推送
        yield {
            "event": "sources",
            "data": sources_json,
        }
        parts: list[str] = []
        try:
            for piece in stream:
                parts.append(piece)
                yield {
                    "event": "delta",
                    "data": json.dumps({"text": piece}, ensure_ascii=False),
                }
            text = "".join(parts)
            if text:
                storage.add_message(req.kb_id, "assistant", text, sources_json, session_id=req.session_id)
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
    if req.session_id and not storage.ensure_session(req.kb_id, req.session_id):
        raise HTTPException(status_code=404, detail="会话不存在")

    storage.add_message(req.kb_id, "user", req.question, session_id=req.session_id)

    pipeline = _build_pipeline(req.kb_id, req.top_k)
    ans: Answer = pipeline.ask(req.question)
    sources = _sources_payload(ans.sources)
    storage.add_message(req.kb_id, "assistant", ans.text, json.dumps(sources, ensure_ascii=False), session_id=req.session_id)
    return {
        "answer": ans.text,
        "sources": sources,
        "retrieved": ans.retrieved,
    }


class MultiTurnChatRequest(BaseModel):
    """多轮检索请求"""
    kb_id: str
    question: str = Field(min_length=1, max_length=2000)
    max_rounds: int = Field(default=3, ge=1, le=5)
    session_id: str | None = None


@router.post("/chat/multi-turn")
def chat_multi_turn(req: MultiTurnChatRequest) -> dict:
    """多轮检索问答（同步）

    流程：检索 → 判断是否充分 → 不充分则改写问题再检索 → 生成答案
    """
    if not storage.get_kb(req.kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    if req.session_id and not storage.ensure_session(req.kb_id, req.session_id):
        raise HTTPException(status_code=404, detail="会话不存在")

    storage.add_message(req.kb_id, "user", req.question, session_id=req.session_id)

    pipeline = _build_pipeline(req.kb_id, None)
    ans: Answer = pipeline.ask_multi_turn(req.question, max_rounds=req.max_rounds)
    sources = _sources_payload(ans.sources)
    storage.add_message(req.kb_id, "assistant", ans.text, json.dumps(sources, ensure_ascii=False), session_id=req.session_id)
    return {
        "answer": ans.text,
        "sources": sources,
        "retrieved": ans.retrieved,
        "had_context": ans.had_context,
    }


@router.post("/chat/debug")
def chat_debug(req: ChatRequest) -> dict:
    """检索调试：返回检索得分、命中片段、过滤原因

    用于诊断检索问题，帮助优化检索效果。
    """
    if not storage.get_kb(req.kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    pipeline = _build_pipeline(req.kb_id, req.top_k)

    # 执行检索
    hits = pipeline.retrieve(req.question)

    # 构建调试信息
    debug_info = {
        "query": req.question,
        "rewritten_query": pipeline._rewrite_query(req.question),
        "hits": [
            {
                "title": hit.chunk.title,
                "source": hit.chunk.source,
                "section": hit.chunk.section,
                "text": hit.chunk.text[:200] + "..." if len(hit.chunk.text) > 200 else hit.chunk.text,
                "score": round(hit.score, 4),
                "coverage": round(hit.coverage, 2),
            }
            for hit in hits
        ],
        "total_hits": len(hits),
        "had_context": len(hits) > 0,
    }

    return debug_info


@router.get("/chat/export/{session_id}")
def export_chat(session_id: str, kb_id: str) -> dict:
    """导出对话为 Markdown 格式

    用于保存对话记录，便于分享和归档。
    """
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    session = storage.get_session(kb_id, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = storage.get_messages(kb_id, session_id)

    # 构建 Markdown 内容
    md_lines = [
        f"# {session['name']}",
        "",
        f"**知识库**: {storage.get_kb(kb_id)['name']}",
        f"**创建时间**: {session['created_at']}",
        "",
        "---",
        "",
    ]

    for msg in messages:
        role_label = "**我**" if msg["role"] == "user" else "**AI**"
        md_lines.append(f"{role_label}: {msg['text']}")
        md_lines.append("")

    md_content = "\n".join(md_lines)

    return {
        "ok": True,
        "content": md_content,
        "filename": f"{session['name']}.md",
    }


@router.post("/chat/recommend")
def chat_recommend(req: ChatRequest) -> dict:
    """主动推荐：根据对话内容推荐相关问题

    用于引导用户深入探索知识库，提升用户体验。
    """
    if not storage.get_kb(req.kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 获取最近的消息
    messages = storage.get_messages(req.kb_id, req.session_id, limit=10)

    # 构建对话上下文
    context = "\n".join([f"{m['role']}: {m['text']}" for m in messages])

    # 用 LLM 生成推荐问题
    pipeline = _build_pipeline(req.kb_id, None)
    try:
        # 生成推荐问题
        system_prompt = (
            "你是问题推荐助手。任务是根据对话内容推荐相关问题。\n"
            "规则：\n"
            "1. 推荐的问题应该与对话内容相关；\n"
            "2. 推荐的问题应该有深度，引导用户进一步探索；\n"
            "3. 只输出推荐问题列表，每行一个，不输出其他内容。"
        )
        messages_for_llm = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]
        resp = pipeline.llm._client.chat.completions.create(
            model=pipeline.llm.model,
            messages=messages_for_llm,
            temperature=0.0,
            max_tokens=200,
        )
        content = (resp.choices[0].message.content or "").strip()
        questions = [q.strip() for q in content.split("\n") if q.strip()]
        return {"ok": True, "questions": questions}
    except Exception as e:
        return {"ok": True, "questions": [], "error": str(e)}


@router.post("/chat/feedback/{msg_id}")
def message_feedback(msg_id: int, data: dict) -> dict:
    """消息反馈：点赞/点踩

    用于收集用户对回答质量的反馈，帮助优化回答效果。
    """
    feedback = data.get("type")
    if feedback not in ("up", "down", None):
        raise HTTPException(status_code=400, detail="无效的反馈类型")

    success = storage.update_message_feedback(msg_id, feedback)
    if not success:
        raise HTTPException(status_code=404, detail="消息不存在")

    return {"ok": True, "feedback": feedback}
