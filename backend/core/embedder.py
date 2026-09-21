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

# 必须在导入 huggingface_hub 之前设置，否则不生效。
#
# 用直接赋值而非 os.environ.setdefault：这两项不是「用户偏好」而是
# 「绕过已知故障的必需开关」——镜像不支持 Xet 协议、Google 桶不可达，
# 一旦被外部环境里的残留值覆盖，下载就会失败并静默退化成 BM25 单路。
# 若确有覆盖，下面会把原值打出来，不做无声改变。
_HF_OVERRIDES = {
    "HF_ENDPOINT": "https://hf-mirror.com",
    "HF_HUB_DISABLE_XET": "1",
    # Windows 下 huggingface_hub 无法建符号链接，关掉警告噪音
    "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
}
for _key, _value in _HF_OVERRIDES.items():
    _prev = os.environ.get(_key)
    if _prev and _prev != _value:
        print(f"[embedder] 覆盖环境变量 {_key}: {_prev!r} -> {_value!r}", file=sys.stderr)
    os.environ[_key] = _value

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
    def state(self) -> str:
        """三态：idle（尚未加载）/ ready（已加载）/ failed（加载失败）

        单看 available 分不清「还没试过」与「试过但失败了」，
        而对用户来说前者需要等待、后者需要修配置，提示文案完全不同。
        """
        if self._model is not None:
            return "ready"
        return "failed" if self._failed else "idle"

    @property
    def error(self) -> str:
        return self._error

    def warmup(self) -> bool:
        """主动加载模型并返回是否可用。

        供服务启动时调用：既省掉首次提问的加载等待，也让健康检查
        能立刻报告真实状态（否则空知识库时无人触发加载，状态一直是 idle）。
        失败不抛异常——降级由检索层处理，不该阻断服务启动。
        """
        return self._ensure_loaded()

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


# 全局共享实例。
#
# 模型权重（约 90 MB）必须只加载一份：早期实现里每个 VectorRetriever
# 各自 new 一个 Embedder，N 个知识库就会重复常驻 N 份权重，
# 且 health 上报时不知道该读哪一个。此处集中到模块级单例，
# 由 get_embedder() 提供给所有检索器。
_shared: "Embedder | None" = None


def get_embedder() -> Embedder:
    """取全局 Embedder 单例（进程内模型只加载一次）"""
    global _shared
    if _shared is None:
        _shared = Embedder()
    return _shared
