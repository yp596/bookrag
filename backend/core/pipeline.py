# -*- coding: utf-8 -*-
"""RAG 问答链路

把解析、切片、检索、生成串成一条完整链路：

    文档 -> loader -> splitter -> Chunk[]
                                    |
    用户提问 -> retriever.retrieve -> Hit[]
                                    |
              拼接上下文 -> llm.chat -> 回答 + 引用来源

后续接入向量检索与 RRF 融合时，只需在 retrieve 环节增加一路结果并融合，
上下游接口保持不变。
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from core.config import MIN_TERM_COVERAGE, NO_CONTEXT_REPLY, TOP_K
from core.llm import LLMClient
from core.loader import load_document
from core.retriever import HybridRetriever, Hit
from core.splitter import Chunk, split_by_section
from core.gguf_model import GGUFLocalModel


@dataclass
class Answer:
    """一次问答的完整结果"""

    text: str
    sources: list[Hit] = field(default_factory=list)
    retrieved: int = 0          # 命中片段数
    had_context: bool = True    # 是否检索到了可用资料

    def source_summary(self) -> str:
        """引用来源的简要描述，供日志或调试使用"""
        if not self.sources:
            return "（无引用来源）"
        lines = []
        for i, hit in enumerate(self.sources, 1):
            origin = f"{hit.chunk.source} " if hit.chunk.source else ""
            lines.append(
                f"{i}. {origin}{hit.chunk.title} | 相关度 {hit.score:.3f} | 覆盖率 {hit.coverage:.2f}"
            )
        return "\n".join(lines)


class RAGPipeline:
    """RAG 问答流水线

    检索器与 LLM 均可注入：桌面端按知识库切换检索器，
    切换模型模式时换一个 LLMClient 即可，编排逻辑不变。
    """

    def __init__(
        self,
        llm_mode: str = "local",
        top_k: int = TOP_K,
        retriever: HybridRetriever | None = None,
        llm: LLMClient | None = None,
        llm_config: dict | None = None,
        use_gguf: bool = False,
        gguf_model_path: str | None = None,
    ) -> None:
        if use_gguf:
            self.llm = GGUFLocalModel(model_path=gguf_model_path or "models/MiniCPM5-1B-F16.gguf")
        elif llm is not None:
            self.llm = llm
        elif llm_config is not None:
            self.llm = LLMClient(**llm_config)
        else:
            self.llm = LLMClient(mode=llm_mode)
        self.retriever = retriever if retriever is not None else HybridRetriever()
        self.top_k = top_k
        self._chunks: list[Chunk] = []

    # ---------- 知识库构建 ----------
    def add_document(self, path: str) -> int:
        """导入一个文档文件，返回新增切片数"""
        text = load_document(path)
        return self.add_text(text, source=Path(path).name)

    def add_text(self, text: str, source: str = "") -> int:
        """导入一段文本，返回新增切片数"""
        chunks = split_by_section(text, source=source)
        self._chunks.extend(chunks)
        self.retriever.build(self._chunks)      # 重建索引（文档量增大后可改增量）
        return len(chunks)

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def clear(self) -> None:
        self._chunks.clear()
        self.retriever.build([])

    # ---------- 检索 ----------
    def _build_context(self, hits: list[Hit]) -> str:
        """把命中片段拼成上下文。

        刻意不使用 [资料N] 这类编号标注：实测发现编号格式会诱导小模型
        模仿格式并编造出不存在的「资料2、资料3」，因此改为中性分隔符，
        同时在开头显式声明片段总数。
        """
        if not hits:
            return "（无相关资料）"
        header = f"以下是从知识库中检索到的 {len(hits)} 个资料片段：\n\n"
        return header + "\n\n---\n\n".join(hit.chunk.text for hit in hits)

    def _rewrite_query(self, query: str, history: list[dict] | None = None) -> str:
        """查询改写：用 LLM 将用户查询改写成更适合检索的形式"""
        try:
            return self.llm.rewrite_query(query, history)
        except Exception:
            return query  # 改写失败时回退到原始查询

    def _is_sufficient(self, hits: list[Hit], query: str) -> bool:
        """判断检索结果是否充分

        策略：
        - 命中数 >= top_k 且平均覆盖率 > 0.3 → 充分
        - 否则不充分，需要多轮检索
        """
        if not hits:
            return False
        if len(hits) < self.top_k:
            return False
        avg_coverage = sum(h.coverage for h in hits) / len(hits)
        return avg_coverage > 0.3

    def retrieve(self, question: str, history: list[dict] | None = None) -> list[Hit]:
        """检索，支持查询改写和自动多轮检索

        自动多轮检索：如果普通检索结果不充分，自动执行多轮检索。
        """
        rewritten = self._rewrite_query(question, history)
        hits = self.retriever.retrieve(rewritten, top_k=self.top_k)

        # 自动多轮检索：如果结果不充分，执行多轮检索
        if not self._is_sufficient(hits, question):
            multi_hits = self.retrieve_multi(question, history)
            if len(multi_hits) > len(hits):
                return multi_hits

        return hits

    def _classify_query(self, query: str) -> str:
        """查询分类：根据问题类型选择检索策略

        策略：
        - simple: 简单问题（事实查询、定义查询）→ 普通检索
        - complex: 复杂问题（推理、创作、多步骤）→ 多轮检索
        - semantic: 语义问题（口语化、上下文依赖）→ HyDE 检索
        """
        # 复杂问题关键词
        complex_keywords = ["为什么", "如何", "分析", "比较", "设计", "实现", "优化", "推理"]
        # 语义问题关键词
        semantic_keywords = ["意思", "含义", "解释", "理解", "描述", "介绍"]

        query_lower = query.lower()

        # 检查复杂问题关键词
        for kw in complex_keywords:
            if kw in query_lower:
                return "complex"

        # 检查语义问题关键词
        for kw in semantic_keywords:
            if kw in query_lower:
                return "semantic"

        # 默认简单问题
        return "simple"

    def route_retrieve(self, question: str, history: list[dict] | None = None) -> list[Hit]:
        """查询路由：根据问题类型选择检索策略"""
        query_type = self._classify_query(question)

        if query_type == "complex":
            # 复杂问题 → 多轮检索
            return self.retrieve_multi(question, history)
        elif query_type == "semantic":
            # 语义问题 → HyDE 检索
            return self.retrieve_hyde(question, history)
        else:
            # 简单问题 → 普通检索
            return self.retrieve(question, history)

    def _generate_hypothesis(self, query: str) -> str:
        """HyDE 假设文档：让 LLM 先生成假设答案，用答案检索"""
        try:
            return self.llm.generate_hypothesis(query)
        except Exception:
            return query  # 生成失败时回退到原始查询

    def retrieve_hyde(self, question: str, history: list[dict] | None = None) -> list[Hit]:
        """HyDE 检索：用假设答案作为查询进行检索"""
        hypothesis = self._generate_hypothesis(question)
        return self.retriever.retrieve(hypothesis, top_k=self.top_k)

    def _split_queries(self, query: str) -> list[str]:
        """多查询检索：将一个问题拆成多个子查询"""
        try:
            return self.llm.split_queries(query)
        except Exception:
            return [query]  # 拆分失败时回退到原始查询

    def retrieve_multi(self, question: str, history: list[dict] | None = None) -> list[Hit]:
        """多查询检索：对每个子查询分别检索，合并结果"""
        queries = self._split_queries(question)
        all_hits: list[Hit] = []
        seen_texts: set[str] = set()

        for q in queries:
            hits = self.retriever.retrieve(q, top_k=self.top_k)
            for hit in hits:
                # 按文本去重
                if hit.chunk.text not in seen_texts:
                    seen_texts.add(hit.chunk.text)
                    all_hits.append(hit)

        return all_hits[:self.top_k]

    # ---------- 问答 ----------
    def ask(self, question: str) -> Answer:
        """同步问答，返回回答与引用来源"""
        hits = self.retrieve(question, history=None)
        if not hits:
            # 无命中直接短路，不调用模型，避免其补充推测性内容
            return Answer(text=NO_CONTEXT_REPLY, sources=[], retrieved=0, had_context=False)
        context = self._build_context(hits)
        # 模型自动切换：根据问题类型选择本地/云端模型
        selected_model = self.llm.select_model(question)
        if selected_model == "cloud" and self.llm.mode != "cloud":
            # 临时切换到云端模型
            original_llm = self.llm
            self.llm = LLMClient(mode="cloud")
            text = self.llm.chat(question, context)
            self.llm = original_llm
        else:
            text = self.llm.chat(question, context)
        return Answer(
            text=text,
            sources=hits,
            retrieved=len(hits),
            had_context=True,
        )

    def ask_stream(self, question: str) -> tuple[Iterator[str], list[Hit]]:
        """流式问答。

        Returns:
            (文本增量迭代器, 命中的引用来源列表)
            引用来源在流开始前即可确定，因此一次性返回，便于前端先渲染引用区。
        """
        hits = self.retrieve(question, history=None)
        if not hits:
            # 与 ask 一致：无命中时不调用模型，直接给出固定答复
            return iter([NO_CONTEXT_REPLY]), hits
        context = self._build_context(hits)
        return self.llm.chat_stream(question, context), hits

    # ---------- 多轮检索 ----------
    def ask_multi_turn(self, question: str, max_rounds: int = 3) -> Answer:
        """多轮检索：检索 → 判断是否充分 → 不充分则改写问题再检索"""
        current_q = question
        all_hits: list[Hit] = []
        seen_ids: set[str] = set()

        for round_idx in range(max_rounds):
            hits = self.retrieve(current_q)
            # 去重
            new_hits = [h for h in hits if h.chunk.id not in seen_ids]
            for h in new_hits:
                seen_ids.add(h.chunk.id)
            all_hits.extend(new_hits)

            if self._is_sufficient(all_hits, question):
                break

            if round_idx < max_rounds - 1:
                current_q = self._rewrite_question(question, all_hits)

        if not all_hits:
            return Answer(text=NO_CONTEXT_REPLY, sources=[], retrieved=0, had_context=False)

        # 按相关度排序，取 top_k
        all_hits.sort(key=lambda h: h.score, reverse=True)
        final_hits = all_hits[:self.top_k]
        context = self._build_context(final_hits)
        text = self.llm.chat(question, context)
        return Answer(
            text=text,
            sources=final_hits,
            retrieved=len(final_hits),
            had_context=True,
        )

    def _is_sufficient(self, hits: list[Hit], question: str) -> bool:
        """判断检索结果是否充分"""
        if not hits:
            return False
        # 简单判断：命中数 >= 3 且最高分 > 0.5
        return len(hits) >= 3 and hits[0].score > 0.5

    def _rewrite_question(self, question: str, hits: list[Hit]) -> str:
        """基于已检索内容改写问题，提高召回率"""
        # 简单策略：提取已检索片段的关键词，拼接到问题中
        keywords = []
        for hit in hits[:3]:
            text = hit.chunk.text[:100]
            # 提取前 100 字符作为关键词
            keywords.append(text)
        if keywords:
            return f"{question}（参考：{' '.join(keywords[:2])}）"
        return question

    # ---------- 断点续传 ----------
    def save_checkpoint(self, session_id: str, question: str, round_idx: int, hits: list[Hit]) -> None:
        """保存检索断点状态"""
        # 简化实现：保存到内存中，实际应用可持久化到文件/数据库
        if not hasattr(self, '_checkpoints'):
            self._checkpoints = {}
        self._checkpoints[session_id] = {
            'question': question,
            'round_idx': round_idx,
            'hits': hits,
        }

    def load_checkpoint(self, session_id: str) -> dict | None:
        """加载检索断点状态"""
        if not hasattr(self, '_checkpoints'):
            return None
        return self._checkpoints.get(session_id)

    def clear_checkpoint(self, session_id: str) -> None:
        """清除检索断点状态"""
        if hasattr(self, '_checkpoints') and session_id in self._checkpoints:
            del self._checkpoints[session_id]
