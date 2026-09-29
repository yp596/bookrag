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

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

from core.config import TOP_K, VECTOR_DIR, VECTOR_MIN_SCORE, VECTOR_MIN_SIMILARITY, VECTOR_QUANTIZE
from core.embedder import Embedder, get_embedder
from core.splitter import Chunk


def cache_path(kb_id: str, cache_dir: Path | str = VECTOR_DIR) -> Path:
    """某知识库的向量缓存文件路径"""
    return Path(cache_dir) / f"{kb_id}.npz"


def drop_vector_cache(kb_id: str, cache_dir: Path | str = VECTOR_DIR) -> None:
    """删除某库的向量缓存（内容变更或删库后调用）。

    删文件是最省事的失效方式：指纹对不上本来也会重建，
    但删库后不清理会留下永久垃圾。
    """
    try:
        cache_path(kb_id, cache_dir).unlink(missing_ok=True)
    except OSError:
        pass


def _normalize(matrix: np.ndarray) -> np.ndarray:
    """行归一化：检索时点积即余弦相似度，省掉每轮重复求模"""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms

# ====================== int8 量化 ======================
# 归一化后向量各维度值域 [-1, 1]，int8 量化：q = round(x * 127)
# 反量化：x ≈ q / 127，点积缩放：cosine ≈ (q1 · q2) / (127 * 127)
_QUANT_SCALE = 127.0


def _quantize(matrix: np.ndarray) -> np.ndarray:
    """float32 归一化矩阵 → int8 量化矩阵"""
    return np.clip(np.rint(matrix * _QUANT_SCALE), -127, 127).astype(np.int8)


def _dequantize(qmatrix: np.ndarray) -> np.ndarray:
    """int8 量化矩阵 → float32 近似矩阵"""
    return qmatrix.astype(np.float32) / _QUANT_SCALE


def _quantized_similarity(qmatrix: np.ndarray, q: np.ndarray) -> np.ndarray:
    """量化矩阵与量化查询向量的相似度（等效余弦）

    点积后除以 127^2 还原为 [-1, 1] 范围的余弦近似值。
    """
    dots = qmatrix.astype(np.float32) @ q.astype(np.float32)
    return dots / (_QUANT_SCALE * _QUANT_SCALE)


class VectorRetriever:
    """向量检索器（内存索引，惰性向量化）

    向量在 build 时一次性算好并常驻内存：单条 512 维 float32 约 2 KB，
    一万个切片也只有 20 MB，远小于反复推理的开销。

    向量矩阵同时落盘（VECTOR_DIR/<kb_id>.npz）：重启后指纹命中则直接加载，
    不再逐条过 embedding 模型。指纹 = 模型名 + 切片文本序列，
    内容、顺序、模型任一变化都自动重建，不会读到过期矩阵。
    """

    def __init__(
        self,
        embedder: Embedder | None = None,
        kb_id: str | None = None,
        cache_dir: Path | str = VECTOR_DIR,
    ) -> None:
        # 默认取全局单例：模型权重只加载一份，N 个知识库不重复占用内存
        self.embedder = embedder or get_embedder()
        self.kb_id = kb_id
        self.cache_dir = Path(cache_dir)
        self._chunks: list[Chunk] = []
        self._matrix: np.ndarray | None = None   # (N, dim)，已归一化
        self._qmatrix: np.ndarray | None = None  # (N, dim)，int8 量化
        self._quantized: bool = False

    @property
    def size(self) -> int:
        return len(self._chunks)

    @property
    def available(self) -> bool:
        """索引是否可用（模型加载成功且已建好向量）"""
        return (self._matrix is not None or self._qmatrix is not None) and len(self._chunks) > 0

    def build(self, chunks: list[Chunk]) -> None:
        """重建索引。模型不可用时静默降级为空索引，不影响 BM25 工作"""
        self._chunks = list(chunks)
        if not chunks:
            self._matrix = None
            if self.kb_id is not None:
                drop_vector_cache(self.kb_id, self.cache_dir)
            return

        if self.kb_id is not None and self._load_cache():
            return

        vectors = self.embedder.embed([c.text for c in chunks])
        if not vectors:
            # 模型缺失：保持 _matrix 为 None，检索时自动跳过向量一路
            self._matrix = None
            return

        self._matrix = _normalize(np.asarray(vectors, dtype=np.float32))
        if VECTOR_QUANTIZE:
            self._qmatrix = _quantize(self._matrix)
            self._quantized = True
            # 释放 float32 矩阵，只保留 int8（内存降 75%）
            self._matrix = None
        else:
            self._qmatrix = None
            self._quantized = False
        if self.kb_id is not None:
            self._save_cache()

    def _fingerprint(self) -> str:
        """缓存指纹：模型名 + 切片文本序列。任一变化都必须重建"""
        h = hashlib.sha256()
        h.update(str(getattr(self.embedder, "model_name", "?")).encode("utf-8"))
        for c in self._chunks:
            h.update(b"\0")
            h.update(c.text.encode("utf-8"))
        return h.hexdigest()

    def _load_cache(self) -> bool:
        """指纹命中则加载矩阵。任何异常都返回 False，调用方回退到重算"""
        try:
            data = np.load(cache_path(self.kb_id, self.cache_dir), allow_pickle=False)
            meta = json.loads(str(data["meta"]))
            matrix = data["matrix"]
            if meta.get("fp") != self._fingerprint():
                return False
            if matrix.shape[0] != len(self._chunks):
                return False
            if meta.get("quantized", False):
                self._qmatrix = np.asarray(matrix, dtype=np.int8)
                self._quantized = True
                self._matrix = None
            else:
                self._matrix = np.asarray(matrix, dtype=np.float32)
                self._qmatrix = None
                self._quantized = False
            return True
        except (OSError, ValueError, KeyError):
            return False

    def _save_cache(self) -> None:
        """矩阵落盘。失败只打日志，绝不能影响检索主链路"""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = cache_path(self.kb_id, self.cache_dir)
            tmp = path.with_name(path.name + ".tmp")
            meta = json.dumps({"fp": self._fingerprint(), "quantized": VECTOR_QUANTIZE})
            with open(tmp, "wb") as f:
                if VECTOR_QUANTIZE:
                    np.savez(f, matrix=self._qmatrix, meta=meta)
                else:
                    np.savez(f, matrix=self._matrix, meta=meta)
            os.replace(tmp, path)
        except OSError as e:
            print(f"[vector] 缓存落盘失败（已忽略）：{e}", file=sys.stderr)

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

        if self._quantized:
            q = np.clip(np.rint(q * _QUANT_SCALE), -127, 127).astype(np.int8)
            sims = _quantized_similarity(self._qmatrix, q)
        else:
            sims = self._matrix @ q
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
