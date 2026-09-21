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
