# -*- coding: utf-8 -*-
"""知识库运行时管理

职责：按需加载各知识库的检索索引并缓存，避免每次问答都重建索引。

索引形态为 HybridRetriever（BM25 + 向量 + RRF 融合）。向量模型缺失时会
自动降级为 BM25 单路，不需要在这里做分支判断。

内存策略：知识库数量通常不多，全量缓存可接受。
若将来单个知识库规模很大，可改为 LRU 淘汰。
"""

from core.retriever import HybridRetriever
from core.storage import Storage


class KBManager:
    """知识库检索索引的懒加载与缓存"""

    def __init__(self, storage: Storage | None = None) -> None:
        self.storage = storage or Storage()
        self._index: dict[str, HybridRetriever] = {}

    def get_retriever(self, kb_id: str) -> HybridRetriever:
        """获取知识库的检索器，未加载则从持久化数据重建"""
        if kb_id not in self._index:
            chunks = self.storage.get_chunks(kb_id)
            retriever = HybridRetriever()
            retriever.build(chunks)
            self._index[kb_id] = retriever
        return self._index[kb_id]

    def invalidate(self, kb_id: str) -> None:
        """知识库内容变化后调用，强制下次访问时重建索引"""
        self._index.pop(kb_id, None)

    def chunk_count(self, kb_id: str) -> int:
        return self.get_retriever(kb_id).size
