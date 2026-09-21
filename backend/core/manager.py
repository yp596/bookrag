# -*- coding: utf-8 -*-
"""知识库运行时管理

职责：按需加载各知识库的检索索引并缓存，避免每次问答都重建索引。

索引形态为 HybridRetriever（BM25 + 向量 + RRF 融合）。向量模型缺失时会
自动降级为 BM25 单路，不需要在这里做分支判断。

内存策略：知识库数量通常不多，全量缓存可接受。
若将来单个知识库规模很大，可改为 LRU 淘汰。
"""

from core.embedder import get_embedder
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

    def vector_status(self) -> dict:
        """向量检索的可用状态（供健康检查上报，不触发模型加载）。

        直接读全局 Embedder 单例，而不是遍历已加载的检索器——
        用户想知道的是「这个应用现在能不能做语义检索」，
        这跟「某个知识库的索引是否已构建」无关：刚启动、还没提过问时
        索引是懒加载的，遍历 `_index` 只会永远报 idle。
        """
        embedder = get_embedder()
        return {"state": embedder.state, "error": embedder.error}
