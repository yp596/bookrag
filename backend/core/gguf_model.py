# -*- coding: utf-8 -*-
"""GGUF 直接加载（不依赖 llama-server）

使用 llama-cpp-python 直接在 Python 中加载 GGUF 模型进行推理，
无需启动 llama-server 进程。

优点：
- 减少外部依赖（不需要 llama-server）
- 减少内存占用（不需要单独的服务器进程）
- 启动更快（不需要等待服务器启动）

缺点：
- 需要安装 llama-cpp-python（C++ 扩展）
- 推理速度可能略低于 llama-server（缺少批处理优化）
"""

from collections.abc import Iterator
from pathlib import Path

from core.config import RAG_SYSTEM_PROMPT


class GGUFModelError(Exception):
    """GGUF 模型加载或推理异常"""


class GGUFLocalModel:
    """GGUF 直接加载模型

    提供与 LLMClient 相同的接口（chat、chat_stream），
    但直接在 Python 中加载 GGUF 模型，不依赖 llama-server。
    """

    def __init__(
        self,
        model_path: str | Path,
        n_ctx: int = 4096,
        n_gpu_layers: int = -1,
        temperature: float = 0.0,
    ) -> None:
        """初始化 GGUF 模型

        Args:
            model_path: GGUF 模型文件路径
            n_ctx: 上下文长度
            n_gpu_layers: GPU 层数（-1 表示全部使用 GPU）
            temperature: 温度参数
        """
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise GGUFModelError(f"模型文件不存在：{self.model_path}")

        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.temperature = temperature
        self._model = None

    def _load(self) -> None:
        """延迟加载模型（首次调用时加载）"""
        if self._model is not None:
            return

        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise GGUFModelError(
                "llama-cpp-python 未安装。请运行：pip install llama-cpp-python"
            ) from e

        try:
            self._model = Llama(
                model_path=str(self.model_path),
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                verbose=False,
            )
        except Exception as e:
            raise GGUFModelError(f"加载 GGUF 模型失败：{e}") from e

    def chat(
        self,
        question: str,
        context: str,
        history: list[dict] | None = None,
    ) -> str:
        """同步问答，返回完整回答

        Args:
            question: 用户问题
            context: 检索到的上下文
            history: 对话历史

        Returns:
            完整回答文本
        """
        self._load()
        assert self._model is not None

        messages = [{"role": "system", "content": RAG_SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append(
            {
                "role": "user",
                "content": f"参考资料：\n{context}\n\n问题：{question}",
            }
        )

        try:
            resp = self._model.create_chat_completion(
                messages=messages,
                temperature=self.temperature,
                max_tokens=4096,
            )
            return resp["choices"][0]["message"]["content"] or ""
        except Exception as e:
            raise GGUFModelError(f"推理失败：{e}") from e

    def chat_stream(
        self,
        question: str,
        context: str,
        history: list[dict] | None = None,
    ) -> Iterator[str]:
        """流式问答，逐段产出文本增量

        Args:
            question: 用户问题
            context: 检索到的上下文
            history: 对话历史

        Yields:
            文本增量
        """
        self._load()
        assert self._model is not None

        messages = [{"role": "system", "content": RAG_SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append(
            {
                "role": "user",
                "content": f"参考资料：\n{context}\n\n问题：{question}",
            }
        )

        try:
            stream = self._model.create_chat_completion(
                messages=messages,
                temperature=self.temperature,
                max_tokens=4096,
                stream=True,
            )
            for chunk in stream:
                if not chunk["choices"]:
                    continue
                delta = chunk["choices"][0]["delta"].get("content")
                if delta:
                    yield delta
        except Exception as e:
            raise GGUFModelError(f"推理失败：{e}") from e

    def test_connection(self) -> tuple[bool, str]:
        """连通性测试

        Returns:
            (是否成功, 提示信息)
        """
        try:
            self._load()
            return True, f"模型已加载：{self.model_path.name}"
        except GGUFModelError as e:
            return False, str(e)
