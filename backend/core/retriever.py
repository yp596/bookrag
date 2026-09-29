# -*- coding: utf-8 -*-
"""中文检索：BM25 关键词 + 向量语义 + RRF 融合

为什么 BM25 要自己实现：
    fastembed 自带的 Qdrant/bm25 使用 SimpleTokenizer，分词逻辑等价于
    re.sub(r"[^\\w]", " ", text.lower()).split()。中文没有空格分隔，
    "本产品的保修期是三年" 会被整体切成 1 个 token，关键词检索完全失效。
    因此中文场景必须先用 jieba 分词，再交给 rank_bm25。

BM25 侧的三道相关度防线（解决首轮测试暴露的噪音污染问题）：
    1. 查询停用词过滤      去掉"的/吗/怎么"等无区分度的虚词
    2. 查询词覆盖率下限    解决"只命中一个词就入选"的误召回
                           （如"支持货到付款吗"误命中含"不支持"的发票条款）
    3. 得分双重阈值        绝对下限 + 相对最高分的比例

单靠 BM25 不够：它只看词面。实测「满多少钱包邮」会被 jieba 切成
「满/多少/钱包/邮」，真正的关键词「包邮」被吃掉，导致完全召回不到
文档里的「满九十九元包邮」条款——口语化提问是纯字面匹配的系统性短板。
因此引入向量一路做语义召回，两者用 RRF 融合，见 HybridRetriever。
"""

from dataclasses import dataclass, field
import math
import time

import jieba
from rank_bm25 import BM25Okapi

from core.config import (
    CANDIDATE_K,
    MIN_TERM_COVERAGE,
    RERANK_ENABLED,
    RERANK_PHRASE_BONUS,
    RERANK_W_BM25,
    RERANK_W_COVERAGE,
    RERANK_W_VECTOR,
    RRF_K,
    SCORE_THRESHOLD_ABS,
    SCORE_THRESHOLD_REL,
    TOP_K,
)
from core.splitter import Chunk

# 中文常用停用词（虚词与疑问词，不含可能成为检索目标的实词）
STOPWORDS: set[str] = {
    # 结构助词与语气词
    "的", "了", "是", "在", "和", "与", "及", "或", "把", "被", "给", "对", "从", "向",
    "吗", "呢", "吧", "啊", "呀", "嘛", "哦", "嗯", "哈", "着", "过", "得", "地",
    # 疑问与指代
    "什么", "怎么", "怎样", "如何", "哪些", "哪个", "哪", "多少", "几个", "多少",
    "这", "那", "这个", "那个", "这些", "那些", "哪个", "哪种",
    # 常见动词与助动词（无区分度）
    "有", "没有", "可以", "能否", "能", "会", "要", "想", "请", "请问", "一下",
    "是否", "需要", "应该", "可能",
    # 连词与副词
    "就", "都", "也", "还", "很", "非常", "关于", "对于", "以及", "并且",
    "但是", "因为", "所以", "如果", "那么", "而且", "并", "却", "则",
    # 人称代词
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "自己",
    # 标点与空白
    "，", "。", "？", "！", "、", "；", "：", "（", "）", "《", "》", " ",
}

# 停用词表可能不足以覆盖全部噪音，以下词仅在查询中出现时过滤（不影响文档分词）
QUERY_EXTRA_STOPWORDS: set[str] = {"支持", "介绍", "说明", "情况", "问题"}


@dataclass
class Hit:
    """一条检索结果"""

    chunk: Chunk
    score: float
    coverage: float
    metadata: dict = field(default_factory=dict)


def tokenize(text: str, drop_stopwords: bool = False) -> list[str]:
    """jieba 分词。

    Args:
        text: 待分词文本
        drop_stopwords: 是否过滤停用词。查询侧应过滤，文档侧保留原文完整性。
    """
    tokens = [t.strip() for t in jieba.cut(text)]
    tokens = [t for t in tokens if t]
    if drop_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS and t not in QUERY_EXTRA_STOPWORDS]
    return tokens


def _coverage(query_terms: set[str], doc_terms: set[str]) -> float:
    """查询词覆盖率：查询中有多少比例的词出现在该文档片段里"""
    if not query_terms:
        return 0.0
    hit = sum(1 for t in query_terms if t in doc_terms)
    return hit / len(query_terms)


class BM25Retriever:
    """BM25 关键词检索器（内存索引）"""

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._doc_tokens: list[set[str]] = []       # 用于覆盖率计算（去重集合）
        self._bm25: BM25Okapi | None = None

    # ---------- 索引构建 ----------
    def build(self, chunks: list[Chunk]) -> None:
        """用给定切片重建索引"""
        self._chunks = list(chunks)
        # BM25 用完整分词（保留词频），覆盖率用去重集合
        corpus = [tokenize(c.text) for c in chunks]
        self._doc_tokens = [set(tokens) for tokens in corpus]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    @property
    def size(self) -> int:
        return len(self._chunks)

    # ---------- 检索 ----------
    def retrieve(self, query: str, top_k: int = TOP_K) -> list[Hit]:
        """检索并做相关度过滤，返回按得分降序的命中列表"""
        if not self._bm25 or not self._chunks:
            return []

        # 查询侧过滤停用词；若全被过滤则回退用原始分词，避免空查询
        terms = tokenize(query, drop_stopwords=True)
        if not terms:
            terms = tokenize(query)
        if not terms:
            return []

        query_terms = set(terms)
        scores = self._bm25.get_scores(terms)

        # 先按得分粗排取候选，再做过滤
        candidates = sorted(range(len(self._chunks)), key=lambda i: -scores[i])[:max(top_k * 4, top_k)]
        if not candidates or scores[candidates[0]] <= 0:
            return []

        top_score = scores[candidates[0]]

        hits: list[Hit] = []
        for i in candidates:
            score = scores[i]
            cov = _coverage(query_terms, self._doc_tokens[i])

            # 三道防线依次过滤
            if score < SCORE_THRESHOLD_ABS:
                continue
            if score < top_score * SCORE_THRESHOLD_REL:
                continue
            if cov < MIN_TERM_COVERAGE:
                continue

            # 时间衰减：新文档权重更高，旧文档逐渐降权
            import time
            current_time = time.time()
            chunk_time = self._chunks[i].timestamp or current_time
            time_diff = current_time - chunk_time
            # 衰减因子：每 30 天衰减 10%
            time_decay = math.exp(-0.1 * time_diff / (30 * 24 * 3600))
            score = score * time_decay

            hits.append(Hit(chunk=self._chunks[i], score=float(score), coverage=cov))

        return hits[:top_k]


class HybridRetriever:
    """双路检索 + RRF 融合。

    分工：
        向量一路负责语义——「满多少钱包邮」这类口语化提问，字面与文档无交集，
        BM25 会完全落空；
        BM25 一路负责词面——型号、编号、专有名词这类精确串，向量反而不敏感。

    RRF（Reciprocal Rank Fusion）为什么比分数加权好：
        BM25 得分是无上界的正数、余弦相似度落在 [0,1]，两者量纲完全不同，
        加权前必须归一化，而归一化方式本身就很主观、依赖语料。
        RRF 只看「名次」不看分数，天然免疫量纲差异——

            score(doc) = Σ  1 / (RRF_K + rank_i(doc))

        代价是丢掉了分数强弱的信息，但对召回阶段来说名次比绝对值可靠。

    降级策略：
        向量模型缺失时（例如首次运行尚未下载），自动退化为 BM25 单路，
        不报错、不影响可用性。
    """

    def __init__(
        self,
        bm25: BM25Retriever | None = None,
        vector: "VectorRetriever | None" = None,
        kb_id: str | None = None,
        cache_dir=None,
    ) -> None:
        self.bm25 = bm25 or BM25Retriever()
        if vector is None:
            from core.vector_index import VectorRetriever

            kwargs = {} if cache_dir is None else {"cache_dir": cache_dir}
            vector = VectorRetriever(kb_id=kb_id, **kwargs)
        self.vector = vector
        self._cache: dict[str, list[Hit]] = {}
        self._cache_enabled = True

    def clear_cache(self) -> None:
        """清空缓存"""
        self._cache.clear()

    def _cache_key(self, query: str) -> str:
        """生成缓存键（归一化查询）"""
        return " ".join(query.lower().split())

    def _get_cache(self, query: str) -> list[Hit] | None:
        """获取缓存结果"""
        if not self._cache_enabled:
            return None
        key = self._cache_key(query)
        return self._cache.get(key)

    def _set_cache(self, query: str, hits: list[Hit]) -> None:
        """设置缓存结果"""
        if not self._cache_enabled:
            return
        key = self._cache_key(query)
        # 限制缓存大小
        if len(self._cache) > 1000:
            self._cache.clear()
        self._cache[key] = hits

    def retrieve(self, query: str, top_k: int = TOP_K) -> list[Hit]:
        """双路检索、融合、精排，支持语义缓存"""
        # 检查缓存
        cached = self._get_cache(query)
        if cached is not None:
            return cached[:top_k]

        # 执行检索
        bm25_hits = self.bm25.retrieve(query, top_k=max(top_k, CANDIDATE_K))

        if not self.vector.available:
            result = self._final(query, rerank_hits(query, bm25_hits, top_k=top_k), top_k)
            self._set_cache(query, result)
            return result

        vec_hits = self.vector.retrieve(query, top_k=max(top_k, CANDIDATE_K))

        if not bm25_hits and not vec_hits:
            return []

        if not bm25_hits:
            result = self._final(query, rerank_hits(query, self._to_hits(vec_hits), top_k=top_k), top_k)
        elif not vec_hits:
            result = self._final(query, rerank_hits(query, bm25_hits, top_k=top_k), top_k)
        else:
            fused = self._fuse(bm25_hits, vec_hits)
            result = self._final(query, rerank_hits(query, fused, top_k=top_k), top_k)

        # 写入缓存
        self._set_cache(query, result)
        return result

    def build(self, chunks: list[Chunk]) -> None:
        self.bm25.build(chunks)
        self.vector.build(chunks)

    @property
    def size(self) -> int:
        return self.bm25.size


    @staticmethod
    def _final(query: str, hits: list[Hit], top_k: int) -> list[Hit]:
        """可选 CrossEncoder 第二阶段：关闭/不可用时原样返回"""
        try:
            from core.cross_reranker import apply_cross_rerank

            return apply_cross_rerank(query, hits, top_k=top_k)
        except Exception:
            return hits

    @staticmethod
    def _to_hits(vec_hits: list[tuple[Chunk, float]]) -> list[Hit]:
        """向量结果转成统一的 Hit，coverage 记为相似度以便展示"""
        return [Hit(chunk=c, score=s, coverage=s) for c, s in vec_hits]

    @staticmethod
    def _fuse(bm25_hits: list[Hit], vec_hits: list[tuple[Chunk, float]]) -> list[Hit]:
        """RRF 融合两路结果，按切片文本去重（切片无稳定 id 字段）

        融合只做粗排：保留两路原始信号（bm25_score / vector_score）进 metadata，
        供后续精排使用。score 字段仍是 RRF 值，仅作展示与调试。
        """
        rrf: dict[str, float] = {}
        keep: dict[str, Hit] = {}
        bm25_score: dict[str, float] = {}
        vector_score: dict[str, float] = {}

        for rank, hit in enumerate(bm25_hits):
            key = hit.chunk.text
            rrf[key] = rrf.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
            keep.setdefault(key, hit)
            bm25_score[key] = hit.score

        for rank, (chunk, sim) in enumerate(vec_hits):
            key = chunk.text
            rrf[key] = rrf.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
            vector_score[key] = sim
            if key not in keep:
                keep[key] = Hit(chunk=chunk, score=sim, coverage=sim)

        # 按融合分降序；score 取 RRF 值，仅作展示与调试
        ordered = sorted(rrf.items(), key=lambda kv: -kv[1])
        out: list[Hit] = []
        for key, fused in ordered:
            hit = keep[key]
            out.append(
                Hit(
                    chunk=hit.chunk,
                    score=fused,
                    coverage=hit.coverage,
                    metadata={
                        **hit.metadata,
                        "bm25_score": bm25_score.get(key, 0.0),
                        "vector_score": vector_score.get(key, 0.0),
                        "rrf": fused,
                    },
                )
            )
        return out


def rerank_hits(query: str, hits: list[Hit], top_k: int = TOP_K) -> list[Hit]:
    """加权精排：把 RRF 丢掉的分数强弱信息取回来。

    RRF 只看名次——BM25 第一名 10 分、第二名 2 分，与向量 0.75 vs 0.70
    会被抹成同样的名次差。这里用三路原始信号重新打分：

        final = W_BM25 * norm_bm25 + W_VEC * vec_sim
                + W_COV * coverage + phrase_bonus

    - norm_bm25：候选集内 min-max 归一化（BM25 无上界，必须先归一才能加权）
    - vec_sim：余弦相似度天然在 [0,1]，直接用；缺失（单路时）记 0
    - coverage：统一重算（查询词在片段中的覆盖率），不用上游残留值——
      向量单路的 Hit 把 coverage 记成了相似度，混用会重复计算向量
    - phrase_bonus：查询原短语逐字出现在片段中则加分，精确串优先

    开关关闭（RERANK_ENABLED=False）时保持原 RRF 顺序直接截断。
    无命中时返回空列表，不硬凑（拒答逻辑依赖这个约定）。
    """
    if not hits:
        return []
    if not RERANK_ENABLED:
        return list(hits)

    terms = tokenize(query, drop_stopwords=True)
    if not terms:
        terms = tokenize(query)
    query_terms = set(terms)

    # 查询原短语：去标点空白后长度不足 2 不做短语判断，避免单字到处命中
    phrase = "".join(ch for ch in query.strip() if ch.strip() and ch not in "，。？！、；：（）《》，。？！,.;:!?()[]\"' ")
    use_phrase = len(phrase) >= 2

    bm25_vals = [float(h.metadata.get("bm25_score", h.score)) for h in hits]
    lo, hi = min(bm25_vals), max(bm25_vals)
    span = hi - lo

    scored: list[tuple[float, Hit]] = []
    for hit, raw in zip(hits, bm25_vals):
        norm_bm25 = (raw - lo) / span if span > 0 else (1.0 if raw > 0 else 0.0)
        vec_sim = float(hit.metadata.get("vector_score", 0.0) or 0.0)
        # 单路 Hit 可能没带 vector_score：向量单路的 score 本身就是相似度
        if vec_sim == 0.0 and "vector_score" not in hit.metadata and hit.coverage > 0 and raw == 0.0:
            vec_sim = min(max(float(hit.score), 0.0), 1.0)

        doc_terms = set(tokenize(hit.chunk.text))
        cov = _coverage(query_terms, doc_terms)

        bonus = 0.0
        if use_phrase and phrase in hit.chunk.text.replace(" ", ""):
            bonus = RERANK_PHRASE_BONUS

        final = RERANK_W_BM25 * norm_bm25 + RERANK_W_VECTOR * vec_sim + RERANK_W_COVERAGE * cov + bonus
        scored.append((
            final,
            Hit(
                chunk=hit.chunk,
                score=final,
                coverage=cov,
                metadata={
                    **hit.metadata,
                    "bm25_score": raw,
                    "vector_score": vec_sim,
                    "rerank": final,
                    "phrase_hit": bool(bonus),
                },
            ),
        ))

    scored.sort(key=lambda kv: -kv[0])
    return [h for _, h in scored[:top_k]] if top_k > 0 else [h for _, h in scored]


def multi_kb_retrieve(
    retrievers: dict[str, HybridRetriever],
    query: str,
    top_k: int = TOP_K,
) -> list[Hit]:
    """联邦检索：多知识库联合检索

    对每个知识库分别检索，合并结果后统一排序。

    Args:
        retrievers: 知识库 ID 到检索器的映射
        query: 用户查询
        top_k: 最终返回的片段数

    Returns:
        合并后的检索结果
    """
    all_hits: list[Hit] = []
    seen_texts: set[str] = set()

    for kb_id, retriever in retrievers.items():
        hits = retriever.retrieve(query, top_k=top_k)
        for hit in hits:
            # 按文本去重
            if hit.chunk.text not in seen_texts:
                seen_texts.add(hit.chunk.text)
                # 标记来源知识库
                hit.metadata["kb_id"] = kb_id
                all_hits.append(hit)

    # 按得分排序，返回前 top_k 个
    all_hits.sort(key=lambda h: -h.score)
    return all_hits[:top_k]
