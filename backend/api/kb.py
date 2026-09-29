# -*- coding: utf-8 -*-
"""知识库管理接口

上传流程：接收文件 -> 落临时文件 -> 解析 -> 切片 -> 入库 -> 使检索索引失效
上传为同步处理：小文档毫秒级完成，大文档（数百页）可能需要数秒，
后续如需更好体验可改为后台任务 + 进度查询。
"""

import json
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from api.deps import kb_manager, settings_store, storage
from core.config import HISTORY_FETCH_DEFAULT
from core.loader import UnsupportedFormatError, fetch_url, load_document
from core.splitter import split_by_section
from core.storage import _now

router = APIRouter(prefix="/api/kb", tags=["知识库"])


class CreateKBRequest(BaseModel):
    name: str = Field(default="未命名知识库", max_length=64)


@router.get("/list")
def list_kbs() -> dict:
    """列出全部知识库（含文档数与切片数）"""
    return {"items": storage.list_kbs()}


@router.post("/create")
def create_kb(req: CreateKBRequest) -> dict:
    """新建知识库"""
    return storage.create_kb(req.name)


@router.delete("/{kb_id}")
def delete_kb(kb_id: str) -> dict:
    """删除知识库及其全部文档与切片"""
    if not storage.delete_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    kb_manager.invalidate(kb_id)
    return {"ok": True}


@router.post("/{kb_id}/upload")
async def upload_document(kb_id: str, file: UploadFile = File(...)) -> dict:
    """上传文档并建立索引"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    suffix = Path(file.filename).suffix.lower()
    # 解析器依赖扩展名判断格式，因此临时文件保留原后缀
    tmp_path = Path(tempfile.gettempdir()) / f"rag_upload_{uuid.uuid4().hex}{suffix}"
    try:
        tmp_path.write_bytes(await file.read())
        try:
            text = load_document(tmp_path)
        except UnsupportedFormatError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

        doc, chunk_count = _store_text(kb_id, file.filename, text)
    finally:
        tmp_path.unlink(missing_ok=True)

    return {"document": doc, "chunk_count": chunk_count}


def _store_text(kb_id: str, filename: str, text: str) -> tuple[dict, int]:
    """纯文本入库（上传与 URL 抓取共用）：切片 → 落库 → 索引失效"""
    # 切片参数取自用户配置（已钳制），仅对本次导入生效
    cfg = settings_store.get()
    chunks = split_by_section(
        text,
        source=filename,
        max_size=cfg["chunk_size"],
        overlap=cfg["chunk_overlap"],
    )
    if not chunks:
        raise HTTPException(status_code=422, detail="文档内容为空，未能生成切片")

    doc = storage.add_document(kb_id, filename, chunks)
    kb_manager.invalidate(kb_id)
    return doc, len(chunks)


class FetchRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


@router.post("/{kb_id}/fetch")
def fetch_document(kb_id: str, req: FetchRequest) -> dict:
    """抓取网页正文并入库。同步处理：超时或非 HTML 直接报错，不落半截数据"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    try:
        title, text = fetch_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        # 超时/断连/DNS 等网络问题：urllib 的异常名直给用户看不懂，统一转述
        raise HTTPException(status_code=502, detail=f"抓取失败：{e}") from e

    # 文档名取网页标题（截 64，与建库命名上限一致），无标题时回落到域名
    filename = (title or urlparse(req.url).netloc).strip()[:64] or "网页"
    doc, chunk_count = _store_text(kb_id, filename, text)
    return {"document": doc, "chunk_count": chunk_count}


@router.delete("/{kb_id}/docs")
def clear_documents(kb_id: str) -> dict:
    """清空知识库的全部文档与切片，保留空库"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    result = storage.clear_documents(kb_id)
    kb_manager.invalidate(kb_id)
    return {"ok": True, **result}


@router.get("/{kb_id}/docs")
def list_documents(kb_id: str) -> dict:
    """列出知识库内的文档"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"items": storage.list_documents(kb_id)}


@router.delete("/{kb_id}/docs/{doc_id}")
def delete_document(kb_id: str, doc_id: str) -> dict:
    """删除单个文档及其切片"""
    if not storage.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    kb_manager.invalidate(kb_id)
    return {"ok": True}


@router.get("/{kb_id}/messages")
def list_messages(
    kb_id: str, limit: int = HISTORY_FETCH_DEFAULT, session_id: str | None = None
) -> dict:
    """列出对话历史（按时间正序，前端重启后恢复展示用）。

    session_id 缺省时返回整库记录（兼容旧客户端）；多会话前端必传。
    """
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    items = []
    for row in storage.list_messages(kb_id, limit=min(max(limit, 1), 500), session_id=session_id):
        sources = []
        if row.get("sources"):
            try:
                sources = json.loads(row["sources"])
            except (ValueError, TypeError):
                sources = []
        items.append({
            "id": row["id"],
            "role": row["role"],
            "text": row["text"],
            "sources": sources,
            "created_at": row["created_at"],
        })
    return {"items": items}


@router.delete("/{kb_id}/messages")
def clear_messages(kb_id: str, session_id: str | None = None) -> dict:
    """清空对话历史（不删知识库与文档）。

    传 session_id 只清该会话，缺省清整库（兼容旧语义）。
    """
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"deleted": storage.clear_messages(kb_id, session_id=session_id)}


class CreateSessionRequest(BaseModel):
    name: str | None = Field(default=None, max_length=32)


class RenameSessionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32)


@router.get("/{kb_id}/sessions")
def list_sessions(kb_id: str) -> dict:
    """列出某库的会话（最近活跃在前）"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"items": storage.list_sessions(kb_id)}


@router.post("/{kb_id}/sessions")
def create_session(kb_id: str, req: CreateSessionRequest) -> dict:
    """新建会话"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    return storage.create_session(kb_id, req.name)


@router.patch("/{kb_id}/sessions/{session_id}")
def rename_session(kb_id: str, session_id: str, req: RenameSessionRequest) -> dict:
    """重命名会话"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not (req.name or "").strip():
        raise HTTPException(status_code=400, detail="会话名称不能为空")
    if not storage.rename_session(kb_id, session_id, req.name):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.delete("/{kb_id}/sessions/{session_id}")
def delete_session(kb_id: str, session_id: str) -> dict:
    """删除会话及其全部消息"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not storage.delete_session(kb_id, session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.get("/{kb_id}/search")
def search_documents(kb_id: str, q: str = "", limit: int = 20) -> dict:
    """搜索知识库内文档内容，返回匹配的片段（含上下文）"""
    if not q.strip():
        return {"items": []}
    items = storage.search_chunks(kb_id, q.strip(), limit=limit)
    return {"items": items}


@router.get("/{kb_id}/docs/{doc_id}/preview")
def preview_document(kb_id: str, doc_id: str) -> dict:
    """返回文档内容预览（前 2000 字）"""
    doc = storage.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    chunks = storage.list_chunks_by_doc(doc_id, limit=100)
    text = "\n\n".join(c["text"] for c in chunks)
    return {
        "document": doc,
        "text": text[:2000],
        "total_chars": len(text),
        "truncated": len(text) > 2000,
    }


@router.get("/backup")
def backup_all() -> dict:
    """导出全部数据为 JSON（知识库、文档、切片、会话、消息）"""
    kbs = storage.list_kbs()
    docs = []
    chunks = []
    sessions = []
    messages = []
    for kb in kbs:
        kb_id = kb["id"]
        docs.extend(storage.list_documents(kb_id))
        sessions.extend(storage.list_sessions(kb_id))
        messages.extend(storage.list_messages(kb_id, limit=10000))
    for doc in docs:
        chunks.extend(storage.list_chunks_by_doc(doc["id"], limit=10000))
    return {
        "version": "1.0",
        "exported_at": _now(),
        "kbs": kbs,
        "docs": docs,
        "chunks": chunks,
        "sessions": sessions,
        "messages": messages,
    }


@router.post("/restore")
def restore_all(data: dict) -> dict:
    """从 JSON 恢复全部数据（覆盖式，保留原始 ID）"""
    # 清空现有数据
    for kb in storage.list_kbs():
        storage.delete_kb(kb["id"])
    # 恢复知识库（保留原始 ID）
    for kb_data in data.get("kbs", []):
        storage.restore_kb(kb_data["id"], kb_data["name"], kb_data["created_at"])
    # 恢复文档和切片（保留原始 ID）
    for doc_data in data.get("docs", []):
        storage.restore_document(
            doc_data["id"], doc_data["kb_id"], doc_data["filename"],
            doc_data["chunk_count"], doc_data["created_at"]
        )
        chunks = [c for c in data.get("chunks", []) if c["doc_id"] == doc_data["id"]]
        for c in chunks:
            storage.restore_chunk(
                doc_data["id"], doc_data["kb_id"], c["idx"],
                c.get("section", ""), c["text"]
            )
    # 恢复会话和消息（保留原始 ID）
    for sess_data in data.get("sessions", []):
        storage.restore_session(
            sess_data["id"], sess_data["kb_id"], sess_data.get("doc_id"),
            sess_data["name"], sess_data["created_at"]
        )
    for msg_data in data.get("messages", []):
        storage.restore_message(
            msg_data["kb_id"], msg_data.get("session_id"),
            msg_data["role"], msg_data["text"],
            msg_data.get("sources"), msg_data["created_at"]
        )
    return {"ok": True, "restored": {
        "kbs": len(data.get("kbs", [])),
        "docs": len(data.get("docs", [])),
        "sessions": len(data.get("sessions", [])),
        "messages": len(data.get("messages", [])),
    }}


@router.get("/{kb_id}/export")
def export_kb(kb_id: str) -> dict:
    """导出单个知识库（含文档、切片、会话、消息）"""
    kb = storage.get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    docs = storage.list_documents(kb_id)
    chunks = []
    for doc in docs:
        chunks.extend(storage.list_chunks_by_doc(doc["id"], limit=10000))
    sessions = storage.list_sessions(kb_id)
    messages = storage.list_messages(kb_id, limit=10000)
    return {
        "version": "1.0",
        "exported_at": _now(),
        "kbs": [kb],
        "docs": docs,
        "chunks": chunks,
        "sessions": sessions,
        "messages": messages,
    }


@router.post("/{kb_id}/import")
def import_kb(kb_id: str, data: dict) -> dict:
    """导入知识库数据（追加式，保留原始 ID）"""
    # 恢复知识库（保留原始 ID）
    for kb_data in data.get("kbs", []):
        storage.restore_kb(kb_data["id"], kb_data["name"], kb_data["created_at"])
    # 恢复文档和切片（保留原始 ID）
    for doc_data in data.get("docs", []):
        storage.restore_document(
            doc_data["id"], doc_data["kb_id"], doc_data["filename"],
            doc_data["chunk_count"], doc_data["created_at"]
        )
        chunks = [c for c in data.get("chunks", []) if c["doc_id"] == doc_data["id"]]
        for c in chunks:
            storage.restore_chunk(
                doc_data["id"], doc_data["kb_id"], c["idx"],
                c.get("section", ""), c["text"]
            )
    # 恢复会话和消息（保留原始 ID）
    for sess_data in data.get("sessions", []):
        storage.restore_session(
            sess_data["id"], sess_data["kb_id"], sess_data.get("doc_id"),
            sess_data["name"], sess_data["created_at"]
        )
    for msg_data in data.get("messages", []):
        storage.restore_message(
            msg_data["kb_id"], msg_data.get("session_id"),
            msg_data["role"], msg_data["text"],
            msg_data.get("sources"), msg_data["created_at"]
        )
    return {"ok": True, "imported": {
        "kbs": len(data.get("kbs", [])),
        "docs": len(data.get("docs", [])),
        "sessions": len(data.get("sessions", [])),
        "messages": len(data.get("messages", [])),
    }}


@router.post("/{kb_id}/batch-import")
def batch_import_folder(kb_id: str, data: dict) -> dict:
    """批量导入文件夹

    递归扫描文件夹，导入所有支持的文档。
    """
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    folder_path = data.get("path", "")
    if not folder_path:
        raise HTTPException(status_code=400, detail="缺少文件夹路径")

    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail="文件夹不存在")

    # 支持的文件格式
    supported_suffixes = {".pdf", ".txt", ".md", ".docx", ".pptx", ".xlsx",
                          ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif",
                          ".doc", ".xls", ".ppt"}

    # 递归扫描文件夹
    files = [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in supported_suffixes]

    imported = 0
    failed = 0
    errors = []

    for file_path in files:
        try:
            text = load_document(file_path)
            _store_text(kb_id, file_path.name, text)
            imported += 1
        except Exception as e:
            failed += 1
            errors.append(f"{file_path.name}: {e}")

    return {
        "ok": True,
        "imported": imported,
        "failed": failed,
        "errors": errors,
    }


@router.post("/preview")
def preview_document(data: dict) -> dict:
    """文档预览：返回文档前 N 个字符

    用于导入前预览文档内容。
    """
    file_path = data.get("path", "")
    if not file_path:
        raise HTTPException(status_code=400, detail="缺少文件路径")

    path = Path(file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        text = load_document(path)
        # 返回前 2000 个字符的预览
        preview = text[:2000]
        return {
            "ok": True,
            "preview": preview,
            "total_length": len(text),
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


class BatchFetchRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=50)


@router.post("/{kb_id}/batch-fetch")
def batch_fetch_documents(kb_id: str, req: BatchFetchRequest) -> dict:
    """批量抓取 URL 并入库

    一次导入多个 URL，逐个抓取，返回导入进度。
    """
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    imported = 0
    failed = 0
    errors = []
    documents = []

    for url in req.urls:
        try:
            title, text = fetch_url(url)
            filename = (title or urlparse(url).netloc).strip()[:64] or "网页"
            doc, chunk_count = _store_text(kb_id, filename, text)
            documents.append(doc)
            imported += 1
        except Exception as e:
            failed += 1
            errors.append(f"{url}: {e}")

    return {
        "ok": True,
        "imported": imported,
        "failed": failed,
        "errors": errors,
        "documents": documents,
    }


class RecursiveFetchRequest(BaseModel):
    url: str
    max_depth: int = Field(default=2, ge=1, le=5)
    max_pages: int = Field(default=50, ge=1, le=200)
    exclude_patterns: list[str] = Field(default_factory=list)


@router.post("/{kb_id}/recursive-fetch")
def recursive_fetch_documents(kb_id: str, req: RecursiveFetchRequest) -> dict:
    """递归爬取网页及其链接并入库

    支持配置爬取深度、最大页面数、排除路径。
    """
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    from core.loader import recursive_fetch

    imported = 0
    failed = 0
    errors = []
    documents = []

    try:
        results = recursive_fetch(
            url=req.url,
            max_depth=req.max_depth,
            max_pages=req.max_pages,
        )

        for url, title, text in results:
            try:
                filename = (title or urlparse(url).netloc).strip()[:64] or "网页"
                doc, chunk_count = _store_text(kb_id, filename, text)
                documents.append(doc)
                imported += 1
            except Exception as e:
                failed += 1
                errors.append(f"{url}: {e}")

        return {
            "ok": True,
            "imported": imported,
            "failed": failed,
            "errors": errors,
            "documents": documents,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"爬取失败：{e}") from e


class CrawlScheduleRequest(BaseModel):
    url: str
    frequency: str = Field(pattern="^(hourly|daily|weekly)$")
    max_depth: int = Field(default=2, ge=1, le=5)
    max_pages: int = Field(default=50, ge=1, le=200)


@router.post("/{kb_id}/crawl-schedule")
def create_crawl_schedule(kb_id: str, req: CrawlScheduleRequest) -> dict:
    """创建定时爬取任务"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    schedule = storage.create_crawl_schedule(
        kb_id=kb_id,
        url=req.url,
        frequency=req.frequency,
        max_depth=req.max_depth,
        max_pages=req.max_pages,
    )
    return {"ok": True, "schedule": schedule}


@router.get("/{kb_id}/crawl-schedules")
def list_crawl_schedules(kb_id: str) -> dict:
    """列出知识库的所有定时爬取任务"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    schedules = storage.list_crawl_schedules(kb_id)
    return {"ok": True, "schedules": schedules}


@router.delete("/{kb_id}/crawl-schedules/{schedule_id}")
def delete_crawl_schedule(kb_id: str, schedule_id: str) -> dict:
    """删除定时爬取任务"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not storage.delete_crawl_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True}


@router.get("/{kb_id}/crawl-history")
def list_crawl_history(kb_id: str, limit: int = 50) -> dict:
    """列出知识库的爬取历史"""
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    history = storage.list_crawl_history(kb_id, limit)
    return {"ok": True, "history": history}


@router.post("/{kb_id}/incremental-fetch")
def incremental_fetch(kb_id: str, data: dict) -> dict:
    """增量爬取：只抓取新增或修改的页面

    通过对比上次爬取时间，只抓取新增或修改的页面。
    """
    if not storage.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    url = data.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="缺少 URL")

    from core.loader import recursive_fetch

    imported = 0
    failed = 0
    errors = []
    documents = []

    try:
        results = recursive_fetch(
            url=url,
            max_depth=data.get("max_depth", 2),
            max_pages=data.get("max_pages", 50),
        )

        for url, title, text in results:
            try:
                filename = (title or urlparse(url).netloc).strip()[:64] or "网页"
                # 检查是否已存在相同内容的文档
                doc, chunk_count = _store_text(kb_id, filename, text)
                documents.append(doc)
                imported += 1
            except Exception as e:
                failed += 1
                errors.append(f"{url}: {e}")

        # 记录爬取历史
        storage.add_crawl_history(
            kb_id=kb_id,
            url=url,
            title="增量爬取",
            status="success" if imported > 0 else "failed",
            page_count=imported,
        )

        return {
            "ok": True,
            "imported": imported,
            "failed": failed,
            "errors": errors,
            "documents": documents,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"爬取失败：{e}") from e


@router.post("/compare")
def compare_documents(data: dict) -> dict:
    """文档对比：返回多个文档的内容

    用于并排对比多个文档内容。
    """
    doc_ids = data.get("doc_ids", [])
    if not doc_ids:
        raise HTTPException(status_code=400, detail="缺少文档 ID")

    documents = []
    for doc_id in doc_ids:
        doc = storage.get_document(doc_id)
        if not doc:
            continue

        # 获取文档的切片
        chunks = storage.get_chunks(doc_id)
        content = "\n\n".join([c.text for c in chunks])

        documents.append({
            "id": doc_id,
            "filename": doc["filename"],
            "content": content,
            "chunk_count": len(chunks),
        })

    return {
        "ok": True,
        "documents": documents,
    }
