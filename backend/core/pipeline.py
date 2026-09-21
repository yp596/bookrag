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
from core.retriever import BM25Retriever, Hit
from core.splitter import Chunk, split_by_section


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
        retriever: BM25Retriever | None = None,
        llm: LLMClient | None = None,
        llm_config: dict | None = None,
    ) -> None:
        if llm is not None:
            self.llm = llm
        elif llm_config is not None:
            self.llm = LLMClient(**llm_config)
        else:
            self.llm = LLMClient(mode=llm_mode)

        self.retriever = retriever if retriever is not None else BM25Retriever()
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

    def retrieve(self, question: str) -> list[Hit]:
        return self.retriever.retrieve(question, top_k=self.top_k)

    # ---------- 问答 ----------
    def ask(self, question: str) -> Answer:
        """同步问答，返回回答与引用来源"""
        hits = self.retrieve(question)
        if not hits:
            # 无命中直接短路，不调用模型，避免其补充推测性内容
            return Answer(text=NO_CONTEXT_REPLY, sources=[], retrieved=0, had_context=False)
        context = self._build_context(hits)
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
        hits = self.retrieve(question)
        if not hits:
            # 与 ask 一致：无命中时不调用模型，直接给出固定答复
            return iter([NO_CONTEXT_REPLY]), hits
        context = self._build_context(hits)
        return self.llm.chat_stream(question, context), hits
