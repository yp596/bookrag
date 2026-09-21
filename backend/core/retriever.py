# -*- coding: utf-8 -*-
"""中文关键词检索（BM25）

为什么不用现成方案的 BM25：
    fastembed 自带的 Qdrant/bm25 使用 SimpleTokenizer，分词逻辑等价于
    re.sub(r"[^\\w]", " ", text.lower()).split()。中文没有空格分隔，
    "本产品的保修期是三年" 会被整体切成 1 个 token，关键词检索完全失效。
    因此中文场景必须先用 jieba 分词，再交给 rank_bm25。

三道相关度防线（解决首轮测试暴露的噪音污染问题）：
    1. 查询停用词过滤      去掉"的/吗/怎么"等无区分度的虚词
    2. 查询词覆盖率下限    解决"只命中一个词就入选"的误召回
                           （如"支持货到付款吗"误命中含"不支持"的发票条款）
    3. 得分双重阈值        绝对下限 + 相对最高分的比例
"""

from dataclasses import dataclass, field

import jieba
from rank_bm25 import BM25Okapi

from core.config import (
    MIN_TERM_COVERAGE,
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

            hits.append(Hit(chunk=self._chunks[i], score=float(score), coverage=cov))

        return hits[:top_k]
