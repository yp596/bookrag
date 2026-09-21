# -*- coding: utf-8 -*-
"""RAG 核心模块

面向桌面端 RAG 知识库的检索与生成能力：

    loader     文档解析（PDF / TXT / docx）
    splitter   按小节标题切片
    retriever  中文 BM25 关键词检索
    llm        本地 / 云端双模式 LLM 调用
    pipeline   串起完整问答链路

向量检索（bge ONNX）与 RRF 融合为后续增量，接入时只需扩展 retriever。
"""

from core.llm import LLMClient, LLMError
from core.loader import UnsupportedFormatError, load_document
from core.pipeline import Answer, RAGPipeline
from core.retriever import BM25Retriever, Hit
from core.splitter import Chunk, split_by_section

__all__ = [
    "Answer",
    "BM25Retriever",
    "Chunk",
    "Hit",
    "LLMClient",
    "LLMError",
    "RAGPipeline",
    "UnsupportedFormatError",
    "load_document",
    "split_by_section",
]
