# -*- coding: utf-8 -*-
"""向量语义检索

与 BM25 的分工：
    BM25 管词面匹配（「九十九元包邮」这类能对上词的查询），
    向量管语义匹配（「满多少钱包邮」这类口语化、字面无交集的查询）。
    单用 BM25 会漏掉后者，单用向量会漏掉型号、条款号这类精确串。

相关度过滤为什么不照搬 BM25 那三道：
    余弦相似度的分布与 BM25 得分完全不同——中文句子对之间普遍有 0.3 以上的
    基础相似度（同一个模型、同一领域语料），用绝对阈值会把大量正确结果误杀。
    这里只用「相对最高分」做粗筛，把绝对判断交给融合后的排序。
"""

import numpy as np

from core.config import TOP_K, VECTOR_MIN_SCORE, VECTOR_MIN_SIMILARITY
from core.embedder import Embedder
from core.splitter import Chunk


class VectorRetriever:
    """向量检索器（内存索引，惰性向量化）

    向量在 build 时一次性算好并常驻内存：单条 512 维 float32 约 2 KB，
    一万个切片也只有 20 MB，远小于反复推理的开销。
    """

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or Embedder()
        self._chunks: list[Chunk] = []
        self._matrix: np.ndarray | None = None   # (N, dim)，已归一化

    @property
    def size(self) -> int:
        return len(self._chunks)

    @property
    def available(self) -> bool:
        """索引是否可用（模型加载成功且已建好向量）"""
        return self._matrix is not None and len(self._chunks) > 0

    def build(self, chunks: list[Chunk]) -> None:
        """重建索引。模型不可用时静默降级为空索引，不影响 BM25 工作"""
        self._chunks = list(chunks)
        if not chunks:
            self._matrix = None
            return

        vectors = self.embedder.embed([c.text for c in chunks])
        if not vectors:
            # 模型缺失：保持 _matrix 为 None，检索时自动跳过向量一路
            self._matrix = None
            return

        matrix = np.asarray(vectors, dtype=np.float32)
        # 预先归一化，检索时点积即余弦相似度，省掉每轮重复求模
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._matrix = matrix / norms

    def retrieve(self, query: str, top_k: int = TOP_K) -> list[tuple[Chunk, float]]:
        """返回 (切片, 余弦相似度) 列表，按相似度降序"""
        if not self.available:
            return []

        qvec = self.embedder.embed([query])
        if not qvec:
            return []

        q = np.asarray(qvec[0], dtype=np.float32)
        norm = float(np.linalg.norm(q)) or 1.0
        q = q / norm

        sims = self._matrix @ q                      # 归一化后点积 = 余弦
        order = np.argsort(-sims)

        top = float(sims[order[0]]) if len(order) else 0.0

        # 绝对下限：最高分都达不到阈值，说明整个知识库与问题无关。
        # 没有这道判断，任何查询（哪怕问天气）都能找出"相对最像"的片段，
        # 进而污染上下文、诱导模型硬答。
        if top < VECTOR_MIN_SCORE:
            return []

        # 相对阈值粗筛：低于最高分该比例的丢弃，滤掉明显跑题的片段
        floor = max(top * VECTOR_MIN_SIMILARITY, VECTOR_MIN_SCORE)

        out: list[tuple[Chunk, float]] = []
        for i in order[: max(top_k * 4, top_k)]:
            sim = float(sims[i])
            if sim < floor:
                break                                 # 已降序，后面只会更低
            out.append((self._chunks[i], sim))
            if len(out) >= top_k:
                break
        return out
