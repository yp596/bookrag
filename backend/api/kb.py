# -*- coding: utf-8 -*-
"""知识库管理接口

上传流程：接收文件 -> 落临时文件 -> 解析 -> 切片 -> 入库 -> 使检索索引失效
上传为同步处理：小文档毫秒级完成，大文档（数百页）可能需要数秒，
后续如需更好体验可改为后台任务 + 进度查询。
"""

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from api.deps import kb_manager, storage
from core.loader import UnsupportedFormatError, load_document
from core.splitter import split_by_section

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

        chunks = split_by_section(text, source=file.filename)
        if not chunks:
            raise HTTPException(status_code=422, detail="文档内容为空，未能生成切片")

        doc = storage.add_document(kb_id, file.filename, chunks)
    finally:
        tmp_path.unlink(missing_ok=True)

    kb_manager.invalidate(kb_id)
    return {"document": doc, "chunk_count": len(chunks)}


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
