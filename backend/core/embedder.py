# -*- coding: utf-8 -*-
"""文本向量化（ONNX，本地离线）

用 fastembed 加载 bge-small-zh-v1.5，底层是 onnxruntime 而非 torch，
避免后者 2.5 GB 的体积与运行期内存开销。

模型来源与镜像：
    fastembed 默认从 Google 存储桶下载，本机不可达；改用 HuggingFace 镜像。
    另外新版 huggingface_hub 默认走 Xet 协议（CAS 传输层），镜像不支持会
    返回 401，必须置 HF_HUB_DISABLE_XET=1 回退到普通 HTTP 下载。
    这两项都在模块导入时设置，避免依赖外部环境变量。

模型缺失时不应让整个服务起不来：向量检索是增强项，BM25 单路仍可工作，
因此加载失败只记录状态，由检索层决定是否降级。
"""

import os
import sys
import traceback
from pathlib import Path

# 必须在导入 huggingface_hub 之前设置，否则不生效
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
# Windows 下 huggingface_hub 无法建符号链接，关掉警告噪音
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from core.config import EMBEDDING_MODEL, MODELS_DIR  # noqa: E402


class Embedder:
    """惰性加载的文本向量化器。

    模型首次使用时才加载（约 1–2 秒），避免拖慢服务启动；
    加载失败会被记住，不会反复重试拖累每次检索。
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL) -> None:
        self.model_name = model_name
        self._model = None
        self._failed = False
        self._error = ""

    @property
    def available(self) -> bool:
        """模型是否可用（不触发加载，避免在索引构建路径上意外阻塞）"""
        return self._model is not None

    @property
    def error(self) -> str:
        return self._error

    def _ensure_loaded(self) -> bool:
        """确保模型已加载，返回是否可用"""
        if self._model is not None:
            return True
        if self._failed:
            return False

        try:
            from fastembed import TextEmbedding

            # 缓存目录放在项目 models/ 下，便于打包时一并带上、离线可用
            cache_dir = str(MODELS_DIR / "fastembed")
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            self._model = TextEmbedding(self.model_name, cache_dir=cache_dir)
            self._error = ""
            return True
        except Exception as e:  # 模型缺失、磁盘满、依赖损坏等
            self._failed = True
            self._error = f"{type(e).__name__}: {e}"
            # 降级是静默的，但绝不能无声：出问题时必须能在后端日志里看到原因，
            # 否则只能观察到「检索结果莫名变少」，无从定位。
            print(f"[embedder] 向量模型加载失败，退化为 BM25 单路检索", file=sys.stderr)
            print(f"[embedder] {self._error}", file=sys.stderr)
            print(f"[embedder] 模型目录: {MODELS_DIR}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        """把一批文本转成向量。模型不可用时返回空列表，由调用方降级"""
        if not texts:
            return []
        if not self._ensure_loaded():
            return []
        return [v.tolist() for v in self._model.embed(texts)]
