# -*- coding: utf-8 -*-
"""精排 rerank_hits 的行为约束测试

只覆盖「改错了不会报错、只会让排序悄悄变差」的逻辑，不依赖模型与网络
（向量侧用 metadata 里预置的相似度或假检索器代替）。

为什么这几条值得测：
    1. RRF 只看名次：BM25 第一名 10 分、第二名 2 分，与向量 0.75 vs 0.70
       会被抹成同样的名次差。若有人把精排改回纯 RRF 截断，长文档排序退化
       无声无息——分数量级测试锁住这条。
    2. 覆盖率若复用上游残留值，向量单路的 Hit 会把相似度当覆盖率再算一遍，
       等于给向量加了双倍权重——统一重算的约定由单测锁住。
    3. 开关 RERANK_ENABLED 是回滚路径，关掉必须回到原 RRF 顺序。

运行：backend/.venv/Scripts/python -m unittest discover -s backend/tests -v
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.retriever import Hit, HybridRetriever, rerank_hits  # noqa: E402
from core.splitter import Chunk  # noqa: E402


def _hit(text: str, bm25: float = 0.0, vec: float = 0.0) -> Hit:
    """构造带双路原始信号的候选（模拟 _fuse 的输出形态）"""
    return Hit(
        chunk=Chunk(text=text),
        score=0.03,  # RRF 值，仅占位
        coverage=0.5,
        metadata={"bm25_score": bm25, "vector_score": vec, "rrf": 0.03},
    )


class ScoreMagnitudeTest(unittest.TestCase):
    """分数量级必须能纠正名次打平"""

    def test_bm25_magnitude_breaks_rrf_tie(self):
        """BM25 10分 vs 2分（5倍差），向量侧几乎打平——分差大的一路应主导"""
        a = _hit("包邮 费用说明：满九十九元，另收运费。", bm25=10.0, vec=0.70)
        b = _hit("包邮 费用说明：满五十元，另收运费。", bm25=2.0, vec=0.75)
        out = rerank_hits("包邮 费用", [b, a], top_k=2)  # 故意逆序输入
        self.assertEqual(out[0].chunk.text, a.chunk.text)
        self.assertGreater(out[0].score, out[1].score)


class PhraseBonusTest(unittest.TestCase):
    """原短语逐字命中者优先（精确串是强信号）"""

    def test_exact_phrase_wins_on_tie(self):
        a = _hit("满九十九元包邮，欢迎选购。", bm25=5.0, vec=0.70)
        b = _hit("包邮政策：满九十九元起，偏远地区除外。", bm25=5.0, vec=0.70)
        out = rerank_hits("九十九元包邮", [b, a], top_k=2)
        self.assertEqual(out[0].chunk.text, a.chunk.text)
        self.assertTrue(out[0].metadata["phrase_hit"])
        self.assertFalse(out[1].metadata["phrase_hit"])


class CoverageTest(unittest.TestCase):
    """覆盖率统一重算：高覆盖者居首，且不受上游残留值污染"""

    def test_higher_coverage_wins(self):
        a = _hit("保修须知：费用按年收取，期限为三年。", bm25=5.0, vec=0.70)
        b = _hit("保修须知：请妥善保管凭证。", bm25=5.0, vec=0.70)
        out = rerank_hits("保修 费用 期限", [b, a], top_k=2)
        self.assertEqual(out[0].chunk.text, a.chunk.text)
        self.assertGreater(out[0].coverage, out[1].coverage)

    def test_stale_coverage_is_recomputed(self):
        """上游残留的 coverage（如向量单路记成的相似度）不得直接采用"""
        a = _hit("保修须知：费用按年收取，期限为三年。", bm25=5.0, vec=0.70)
        a.coverage = 0.0  # 故意写脏，精排必须重算纠正
        out = rerank_hits("保修 费用 期限", [a], top_k=1)
        self.assertGreater(out[0].coverage, 0.9)


class SingleRouteDowngradeTest(unittest.TestCase):
    """BM25 单路（无向量信号）不崩溃、仍可排序截断"""

    def test_no_vector_score_still_reranks(self):
        a = Hit(chunk=Chunk(text="保修须知：费用按年收取，期限为三年。"),
                score=3.0, coverage=1.0, metadata={"bm25_score": 3.0})
        b = Hit(chunk=Chunk(text="退货政策：七天无理由。"),
                score=3.0, coverage=0.0, metadata={"bm25_score": 3.0})
        out = rerank_hits("保修 费用 期限", [b, a], top_k=2)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].chunk.text, a.chunk.text)

    def test_empty_stays_empty(self):
        """无候选返回空——拒答逻辑依赖这个约定，精排不得硬凑"""
        self.assertEqual(rerank_hits("任何问题", [], top_k=3), [])


class HybridWiringTest(unittest.TestCase):
    """全链路接线：真 BM25 + 假向量，融合后必须经过精排"""

    class _FakeVector:
        def __init__(self, sims: list[float]) -> None:
            self._sims = sims
            self._chunks: list = []

        @property
        def available(self) -> bool:
            return True

        def build(self, chunks) -> None:
            self._chunks = list(chunks)

        def retrieve(self, query: str, top_k: int = 3):
            return list(zip(self._chunks, self._sims))[:top_k]

    def test_retrieve_goes_through_rerank(self):
        chunks = [
            Chunk(text="本产品的保修期是三年，全国联保。"),
            Chunk(text="退货政策：七天无理由退货。"),
            Chunk(text="满九十九元包邮，偏远地区除外。"),
        ]
        # 假向量故意唱反调：正确答案相似度最低，检验精排能否纠正
        fake = self._FakeVector([0.50, 0.90, 0.85])
        r = HybridRetriever(vector=fake)  # type: ignore[arg-type]
        r.build(chunks)
        out = r.retrieve("保修期是三年", top_k=1)
        self.assertEqual(len(out), 1)
        self.assertIn("保修期是三年", out[0].chunk.text)
        for key in ("bm25_score", "vector_score", "rerank"):
            self.assertIn(key, out[0].metadata)


class DisabledFlagTest(unittest.TestCase):
    """开关关闭时回退到原 RRF 顺序（回滚路径不断）"""

    def test_disabled_keeps_input_order(self):
        import core.retriever as ret
        prev = ret.RERANK_ENABLED
        ret.RERANK_ENABLED = False
        self.addCleanup(setattr, ret, "RERANK_ENABLED", prev)
        a = _hit("甲", bm25=10.0, vec=0.1)
        b = _hit("乙", bm25=0.1, vec=0.9)
        out = rerank_hits("甲", [b, a], top_k=2)
        self.assertEqual([h.chunk.text for h in out], ["乙", "甲"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
