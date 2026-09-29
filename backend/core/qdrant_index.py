# -*- coding: utf-8 -*-
"""Qdrant 向量检索器（替代 Chroma）

使用 qdrant-client 的本地模式，无需独立服务。
支持向量存储、相似度检索、增量更新。
"""

from pathlib import Path

import numpy as np

from core.config import TOP_K, VECTOR_MIN_SCORE, VECTOR_MIN_SIMILARITY
from core.embedder import Embedder, get_embedder
from core.splitter import Chunk


class QdrantVectorRetriever:
    """Qdrant 向量检索器（本地模式）"""

    def __init__(self, kb_id: str, cache_dir: Path | str = None) -> None:
        self.kb_id = kb_id
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/qdrant")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._embedder = None
        self._collection_name = f"kb_{kb_id}"
        self._available = False

    @property
    def available(self) -> bool:
        """Qdrant 是否可用"""
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
                from qdrant_client.models import Distance, VectorParams

                self._client = QdrantClient(path=str(self.cache_dir / self.kb_id))
                # 检查集合是否存在
                collections = [c.name for c in self._client.get_collections().collections]
                if self._collection_name not in collections:
                    # 创建集合（向量维度将在首次插入时确定）
                    pass
                self._available = True
            except ImportError:
                self._available = False
            except Exception:
                self._available = False
        return self._available

    def build(self, chunks: list[Chunk]) -> None:
        """构建向量索引"""
        if not chunks:
            return

        if not self.available:
            return

        try:
            from qdrant_client.models import Distance, VectorParams, PointStruct

            # 获取嵌入模型
            if self._embedder is None:
                self._embedder = get_embedder()

            # 向量化所有 chunks
            texts = [c.text for c in chunks]
            embeddings = self._embedder.embed(texts)

            if not embeddings:
                return

            # 创建集合
            vector_size = len(embeddings[0])
            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

            # 插入向量
            points = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                points.append(
                    PointStruct(
                        id=i,
                        vector=embedding,
                        payload={
                            "doc_id": chunk.id,
                            "text": chunk.text,
                            "source": chunk.source,
                            "section": chunk.section,
                        },
                    )
                )

            self._client.upsert(
                collection_name=self._collection_name,
                points=points,
            )
        except Exception as e:
            print(f"[qdrant] 构建索引失败：{e}", file=sys.stderr)
            self._available = False

    def retrieve(self, query: str, top_k: int = TOP_K) -> list[tuple[Chunk, float]]:
        """向量检索"""
        if not self.available:
            return []

        try:
            # 获取嵌入模型
            if self._embedder is None:
                self._embedder = get_embedder()

            # 向量化查询
            query_embedding = self._embedder.embed([query])
            if not query_embedding:
                return []

            # 检索
            results = self._client.search(
                collection_name=self._collection_name,
                query_vector=query_embedding[0],
                limit=top_k,
            )

            # 转换为 Chunk 和相似度
            hits = []
            for result in results:
                payload = result.payload
                chunk = Chunk(
                    text=payload.get("text", ""),
                    source=payload.get("source", ""),
                    section=payload.get("section", ""),
                )
                hits.append((chunk, result.score))

            return hits
        except Exception as e:
            print(f"[qdrant] 检索失败：{e}", file=sys.stderr)
            return []

    def clear(self) -> None:
        """清空索引"""
        if self._client is not None:
            try:
                self._client.delete_collection(collection_name=self._collection_name)
            except Exception:
                pass
