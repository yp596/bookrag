# -*- coding: utf-8 -*-
"""向量矩阵落盘缓存的行为约束测试

只覆盖「改错了不会报错、只会静默变慢或读错」的逻辑，不依赖模型与网络。

为什么这几条值得测：
    1. 缓存未命中时必须回退到重算，绝不能因为缓存文件坏了就导致整路不可用。
    2. 指纹漏掉模型名会导致换模型后读到旧矩阵，检索结果悄悄出错。
    3. invalidate 若不清文件，删库后会在磁盘留下永久垃圾。

运行：backend/.venv/Scripts/python -m unittest discover -s backend/tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.splitter import Chunk  # noqa: E402
from core.vector_index import VectorRetriever, cache_path, drop_vector_cache  # noqa: E402


class FakeEmbedder:
    """确定性假向量：调用次数可查，文本不同则向量不同"""

    def __init__(self, model_name: str = "fake-model", dim: int = 4) -> None:
        self.model_name = model_name
        self.dim = dim
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        out = []
        for t in texts:
            seed = sum(ord(ch) for ch in t) % 100 + 1
            out.append([float(seed + i) for i in range(self.dim)])
        return out


def _chunks(*texts: str) -> list[Chunk]:
    return [Chunk(text=t, source="s.txt", index=i) for i, t in enumerate(texts)]


class VectorCacheTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name) / "vec"

    def tearDown(self):
        self._tmp.cleanup()

    def _retriever(self, kb_id="kb1", **kwargs):
        return VectorRetriever(
            embedder=FakeEmbedder(**kwargs),
            kb_id=kb_id,
            cache_dir=self.cache_dir,
        )

    def test_second_build_hits_cache(self):
        r = self._retriever()
        r.build(_chunks("保修三年", "退货七天"))
        self.assertEqual(r.embedder.calls, 1)
        self.assertTrue(cache_path("kb1", self.cache_dir).exists())

        r2 = self._retriever()
        r2.build(_chunks("保修三年", "退货七天"))
        self.assertEqual(r2.embedder.calls, 0)
        self.assertTrue(r2.available)
        hits = r2.retrieve("保修", top_k=2)
        self.assertTrue(len(hits) > 0)

    def test_changed_chunks_rebuild(self):
        r = self._retriever()
        r.build(_chunks("保修三年"))
        r2 = self._retriever()
        r2.build(_chunks("保修三年", "新增条款"))
        self.assertEqual(r2.embedder.calls, 1)

    def test_model_change_rebuilds(self):
        r = self._retriever()
        r.build(_chunks("保修三年"))
        r2 = self._retriever(model_name="other-model")
        r2.build(_chunks("保修三年"))
        self.assertEqual(r2.embedder.calls, 1)

    def test_corrupt_file_falls_back(self):
        r = self._retriever()
        r.build(_chunks("保修三年"))
        cache_path("kb1", self.cache_dir).write_bytes(b"not a npz file")
        r2 = self._retriever()
        r2.build(_chunks("保修三年"))
        self.assertEqual(r2.embedder.calls, 1)
        self.assertTrue(r2.available)

    def test_no_kb_id_skips_cache(self):
        emb = FakeEmbedder()
        r = VectorRetriever(embedder=emb, kb_id=None, cache_dir=self.cache_dir)
        r.build(_chunks("保修三年"))
        r.build(_chunks("保修三年"))
        self.assertEqual(emb.calls, 2)
        self.assertEqual(list(self.cache_dir.glob("*.npz")) if self.cache_dir.exists() else [], [])

    def test_empty_chunks_clears_cache(self):
        r = self._retriever()
        r.build(_chunks("保修三年"))
        self.assertTrue(cache_path("kb1", self.cache_dir).exists())
        r.build([])
        self.assertFalse(r.available)
        self.assertFalse(cache_path("kb1", self.cache_dir).exists())

    def test_kb_isolation(self):
        a = self._retriever(kb_id="a")
        a.build(_chunks("保修三年"))
        b = self._retriever(kb_id="b")
        b.build(_chunks("保修三年"))
        self.assertEqual(b.embedder.calls, 1)
        drop_vector_cache("a", self.cache_dir)
        self.assertFalse(cache_path("a", self.cache_dir).exists())
        self.assertTrue(cache_path("b", self.cache_dir).exists())


class ManagerInvalidateTest(unittest.TestCase):
    """invalidate 必须连内存带文件一起清"""

    def test_invalidate_drops_file(self):
        from core.manager import KBManager
        from core.storage import Storage

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            storage = Storage(str(tmp_path / "rag.db"))
            kb = storage.create_kb("测试库")
            storage.add_document(
                kb["id"], "d.txt", _chunks("保修三年", "退货七天")
            )
            mgr = KBManager(storage, cache_dir=tmp_path / "vec")

            import core.vector_index as vi
            real = vi.VectorRetriever
            emb = FakeEmbedder()

            class _R(real):  # type: ignore[valid-type, misc]
                def __init__(self, **kw):
                    super().__init__(embedder=emb, **kw)

            vi.VectorRetriever = _R  # type: ignore[assignment]
            try:
                mgr.get_retriever(kb["id"])
            finally:
                vi.VectorRetriever = real
            self.assertTrue(cache_path(kb["id"], tmp_path / "vec").exists())

            mgr.invalidate(kb["id"])
            self.assertFalse(cache_path(kb["id"], tmp_path / "vec").exists())


if __name__ == "__main__":
    unittest.main()
