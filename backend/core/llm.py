# -*- coding: utf-8 -*-
"""LLM 调用（本地 / 云端双模式）

设计要点：llama-server 与云端 API 都提供 OpenAI 兼容协议，
因此两种模式共用同一套调用代码，只在 base_url 上做区分。

模式对比：
    本地  http://127.0.0.1:8080/v1     llama-server + GGUF 模型，离线可用
    云端  https://.../v1               百炼 / DeepSeek 等，质量更高但需联网
"""

from collections.abc import Iterator

from openai import APIConnectionError, APIStatusError, OpenAI

from core.config import DEFAULT_LLM_MODE, LLM_PROFILES, RAG_SYSTEM_PROMPT


class LLMError(Exception):
    """LLM 调用异常，携带可直接展示给用户的提示"""


class LLMClient:
    """OpenAI 兼容协议的 LLM 客户端"""

    def __init__(
        self,
        mode: str = DEFAULT_LLM_MODE,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        if mode not in LLM_PROFILES:
            raise ValueError(f"未知模式：{mode}，可选 {list(LLM_PROFILES)}")

        profile = LLM_PROFILES[mode]
        self.mode = mode
        self.base_url = base_url or profile["base_url"]
        self.api_key = api_key or profile["api_key"]
        self.model = model or profile["model"]
        self.temperature = temperature

        self._client = OpenAI(base_url=self.base_url, api_key=self.api_key or "sk-none")

    # ---------- 内部 ----------
    def _build_messages(self, question: str, context: str, history: list[dict] | None) -> list[dict]:
        messages = [{"role": "system", "content": RAG_SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append(
            {
                "role": "user",
                "content": f"参考资料：\n{context}\n\n问题：{question}",
            }
        )
        return messages

    def _handle_error(self, e: Exception) -> LLMError:
        """把底层异常翻译成用户能看懂的提示"""
        if isinstance(e, APIConnectionError):
            if self.mode == "local":
                return LLMError(
                    f"无法连接本地模型服务（{self.base_url}）。"
                    "请确认 llama-server 已启动，或改用云端模式。"
                )
            return LLMError(f"无法连接模型服务（{self.base_url}），请检查网络。")
        if isinstance(e, APIStatusError):
            if e.status_code in (401, 403):
                return LLMError("API Key 无效或权限不足，请检查配置。")
            if e.status_code == 404:
                return LLMError(f"模型 {self.model} 不存在，请检查模型名称。")
            if e.status_code == 429:
                return LLMError("请求过于频繁或额度不足，请稍后重试。")
            return LLMError(f"模型服务返回错误（HTTP {e.status_code}）：{e.message}")
        return LLMError(f"调用模型失败：{e}")

    # ---------- 对外接口 ----------
    def chat(self, question: str, context: str, history: list[dict] | None = None) -> str:
        """同步问答，返回完整回答"""
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=self._build_messages(question, context, history),
                temperature=self.temperature,
                max_tokens=4096,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            raise self._handle_error(e) from e

    def chat_stream(
        self, question: str, context: str, history: list[dict] | None = None
    ) -> Iterator[str]:
        """流式问答，逐段产出文本增量，供 SSE 推送前端"""
        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=self._build_messages(question, context, history),
                temperature=self.temperature,
                max_tokens=4096,
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            raise self._handle_error(e) from e

    def test_connection(self) -> tuple[bool, str]:
        """连通性测试，供设置页使用"""
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=8,
            )
            if resp.choices:
                return True, f"连接成功（模型：{self.model}）"
            return False, "服务无响应内容"
        except Exception as e:
            return False, str(self._handle_error(e))

    def rewrite_query(self, query: str, history: list[dict] | None = None) -> str:
        """查询改写：用 LLM 将用户查询改写成更适合检索的形式

        目的：提升召回率。用户提问往往口语化、上下文依赖强，
        直接用于 BM25 和向量检索效果差。改写后的查询更精确、
        更适合检索。

        Args:
            query: 用户原始查询
            history: 对话历史，用于上下文感知的改写

        Returns:
            改写后的查询
        """
        system_prompt = (
            "你是查询改写助手。任务是将用户查询改写成更适合检索的形式。\n"
            "规则：\n"
            "1. 保留原意，不改变查询意图；\n"
            "2. 去除口语化表达，改为精确关键词；\n"
            "3. 结合对话历史补充上下文（如代词指代）；\n"
            "4. 只输出改写后的查询，不输出其他内容。"
        )
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history[-4:])  # 只取最近 4 轮，避免上下文过长
        messages.append({"role": "user", "content": query})

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                max_tokens=100,
            )
            rewritten = (resp.choices[0].message.content or "").strip()
            return rewritten if rewritten else query
        except Exception:
            return query  # 改写失败时回退到原始查询

    def generate_hypothesis(self, query: str) -> str:
        """HyDE 假设文档：让 LLM 先生成假设答案，用答案检索

        目的：假设答案通常比原始查询更详细、更精确，能提升召回率。
        原理：用户提问往往简短、口语化，而文档中的答案通常更详细、
        更正式。用假设答案作为查询，更容易匹配到文档中的相关内容。

        Args:
            query: 用户原始查询

        Returns:
            假设答案
        """
        system_prompt = (
            "你是知识库助手。任务是根据用户查询生成一个假设答案。\n"
            "规则：\n"
            "1. 假设答案应该详细、正式，与文档风格一致；\n"
            "2. 不要编造不存在的信息，只生成合理的假设；\n"
            "3. 只输出假设答案，不输出其他内容。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                max_tokens=500,
            )
            hypothesis = (resp.choices[0].message.content or "").strip()
            return hypothesis if hypothesis else query
        except Exception:
            return query  # 生成失败时回退到原始查询

    def split_queries(self, query: str) -> list[str]:
        """多查询检索：将一个问题拆成多个子查询

        目的：一个问题可能涉及多个方面，拆分成多个子查询可以
        覆盖更多相关内容，提升召回率。

        Args:
            query: 用户原始查询

        Returns:
            子查询列表
        """
        system_prompt = (
            "你是查询拆分助手。任务是将用户查询拆分成多个子查询。\n"
            "规则：\n"
            "1. 每个子查询应该覆盖原查询的一个方面；\n"
            "2. 子查询之间应该有区分度，避免重复；\n"
            "3. 只输出子查询列表，每行一个，不输出其他内容。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                max_tokens=200,
            )
            content = (resp.choices[0].message.content or "").strip()
            # 按行分割，过滤空行
            queries = [q.strip() for q in content.split("\n") if q.strip()]
            return queries if queries else [query]
        except Exception:
            return [query]  # 拆分失败时回退到原始查询

    def select_model(self, query: str) -> str:
        """模型自动切换：根据问题类型自动选择本地/云端模型

        策略：
        - 简单问题（事实查询、定义查询）→ 本地模型（快速、低成本）
        - 复杂问题（推理、创作、多步骤）→ 云端模型（质量更高）

        Args:
            query: 用户查询

        Returns:
            选中的模型名称
        """
        # 简单问题关键词
        simple_keywords = ["什么", "哪个", "谁", "何时", "哪里", "多少", "定义", "介绍"]
        # 复杂问题关键词
        complex_keywords = ["为什么", "如何", "分析", "比较", "设计", "实现", "优化", "推理"]

        query_lower = query.lower()

        # 检查复杂问题关键词
        for kw in complex_keywords:
            if kw in query_lower:
                return "cloud"

        # 检查简单问题关键词
        for kw in simple_keywords:
            if kw in query_lower:
                return "local"

        # 默认使用本地模型
        return "local"
