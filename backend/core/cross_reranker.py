# -*- coding: utf-8 -*-
"""CrossEncoder 真重排（可选第二阶段，可开关）

为什么需要这一层：
    现有加权精排只用 BM25/向量/覆盖率三路粗信号做线性加权，
    对「字面相近但语义相反」（如支持 vs 不支持）区分力不足。
    CrossEncoder 把【问题 + 片段】成对送入模型打分，是真正的语义重排。

轻量约束：
    不引入 torch/transformers，只用 ONNX 路线（flashrank，底层 onnxruntime，
    与现有 embedder 一致）。模型默认用 ms-marco-TinyBERT-L-2-v2（约 40MB），
    首次启用时从镜像下载到 MODELS_DIR/rerank，失败则静默回退加权精排。

使用约定：
    惰性加载 + 开关 + 失败回退，与 Embedder 三态机一致。
    无命中返回空，不硬凑（拒答逻辑依赖此约定）。
"""

import sys
from pathlib import Path

from core.config import MODELS_DIR

CROSS_DEFAULT_MODEL = "ms-marco-TinyBERT-L-2-v2"
# flashrank 用 requests 直连 huggingface.co（不认 HF_ENDPOINT），国内必然超时。
# 同站镜像保留完全相同的 resolve 路径，只换主机名即可。
_MIRROR_HOST = "https://hf-mirror.com"


class CrossReranker:
    """惰性加载的 CrossEncoder 重排器"""

    def __init__(self, model_name: str = CROSS_DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._ranker = None
        self._failed = False
        self._error = ""

    @property
    def available(self) -> bool:
        return self_ranker_available(self)

    @property
    def state(self) -> str:
        if self._ranker is not None:
            return "ready"
        return "failed" if self._failed else "idle"

    @property
    def error(self) -> str:
        return self._error

    def _prefetch_via_mirror(self) -> None:
        """镜像预取模型 zip 到缓存（尽力而为）。

        Ranker 见到缓存目录已存在即跳过下载；预取失败不抛，由 Ranker
        走直连再试一次（失败则整体回退加权精排，与之前行为一致）。
        URL 从 flashrank 自带模板只换主机名推导，与其版本锁定保持同步。
        """
        import zipfile

        cache = Path(MODELS_DIR) / "rerank"
        if (cache / self.model_name).exists():
            return
        from flashrank.Config import model_url

        url = model_url.replace("https://huggingface.co", _MIRROR_HOST).format(self.model_name)
        import requests

        cache.mkdir(parents=True, exist_ok=True)
        dest = cache / f"{self.model_name}.zip"
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        with zipfile.ZipFile(dest) as zf:
            zf.extractall(cache)
        dest.unlink(missing_ok=True)

    def _ensure_loaded(self) -> bool:
        """懒加载，失败只记一次，不反复重试"""
        if self._ranker is not None:
            return True
        if self._failed:
            return False
        try:
            from flashrank import Ranker
        except Exception as exc:  # 未安装 flashrank 时静默降级
            self._failed = True
            self._error = f"flashrank 未安装：{exc}"
            print(f"[cross_reranker] {self._error}", file=sys.stderr)
            return False
        try:
            self._prefetch_via_mirror()
        except Exception as exc:  # 预取失败不致命，Ranker 还会直连再试
            print(f"[cross_reranker] 镜像预取失败，转直连：{exc}", file=sys.stderr)
        try:
            cache = str(Path(MODELS_DIR) / "rerank")
            Path(cache).mkdir(parents=True, exist_ok=True)
            self._ranker = Ranker(model_name=self.model_name, cache_dir=cache)
            return True
        except Exception as exc:  # 下载失败/模型缺失时降级
            self._failed = True
            self._error = str(exc)
            print(f"[cross_reranker] 加载失败，已回退加权精排：{exc}", file=sys.stderr)
            return False

    def rerank(self, query: str, hits, top_k: int = 0):
        """对已有候选做 CrossEncoder 重排，失败返回原序"""
        if not hits:
            return []
        if not self._ensure_loaded():
            return list(hits)
        try:
            # 0.2.x 起改名 RerankRequest，旧版叫 RankRequest，两种都兼容
            from flashrank import RerankRequest as RankRequest  # type: ignore
        except Exception:
            try:
                from flashrank.Ranker import RerankRequest as RankRequest  # type: ignore
            except Exception:
                try:
                    from flashrank.Ranker import RankRequest  # type: ignore
                except Exception:
                    try:
                        from flashrank import RankRequest  # type: ignore
                    except Exception as exc:
                        print(f"[cross_reranker] 推理接口缺失，已回退：{exc}", file=sys.stderr)
                        return list(hits)
        try:
            pairs = [{"id": i, "text": h.chunk.text[:2000]} for i, h in enumerate(hits)]
            req = RankRequest(query=query, passages=pairs)
            scored = self._ranker.rerank(req)
            order = {r["id"]: float(r["score"]) for r in scored}
            rescored = []
            for i, h in enumerate(hits):
                s = order.get(i, 0.0)
                meta = {**h.metadata, "cross_score": s}
                from core.retriever import Hit

                rescored.append(Hit(chunk=h.chunk, score=s, coverage=h.coverage, metadata=meta))
            rescored.sort(key=lambda h: -h.score)
            return rescored[:top_k] if top_k > 0 else rescored
        except Exception as exc:  # 推理异常绝不影响主链路
            print(f"[cross_reranker] 推理失败，已回退加权精排：{exc}", file=sys.stderr)
            return list(hits)


def self_ranker_available(self) -> bool:
    return self._ranker is not None


# 进程内单例：避免重复加载模型（提交内存常年打满，见记忆）
_singleton: CrossReranker | None = None


def get_cross_reranker(model_name: str = CROSS_DEFAULT_MODEL) -> CrossReranker:
    """返回进程内单例"""
    global _singleton
    if _singleton is None or _singleton.model_name != model_name:
        _singleton = CrossReranker(model_name=model_name)
    return _singleton


def apply_cross_rerank(query: str, hits, top_k: int = 0, model_name: str = CROSS_DEFAULT_MODEL):
    """可选第二阶段入口：未启用/不可用时原样返回"""
    from core import config as cfg

    enabled = bool(getattr(cfg, "CROSS_RERANK_ENABLED", False))
    if not enabled:
        # 设置页开关落库到 settings.json，免重启生效
        try:
            from core.settings_store import SettingsStore

            enabled = bool(SettingsStore().get().get("cross_rerank_enabled", False))
        except Exception:
            enabled = False
    if not enabled:
        return list(hits)
    reranker = get_cross_reranker(model_name=getattr(cfg, "CROSS_RERANK_MODEL", model_name))
    out = reranker.rerank(query, hits, top_k=top_k if top_k > 0 else len(hits))
    return out
