# -*- coding: utf-8 -*-
"""CrossEncoder 第二阶段的行为约束：默认关闭不断链，失败必须回退"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.cross_reranker import CrossReranker, apply_cross_rerank  # noqa: E402
from core.retriever import Hit  # noqa: E402
from core.splitter import Chunk  # noqa: E402


def _hits():
    return [
        Hit(chunk=Chunk(text="保修期三年"), score=0.9, coverage=1.0, metadata={}),
        Hit(chunk=Chunk(text="退货七天"), score=0.1, coverage=0.0, metadata={}),
    ]


class DisabledByDefaultTest(unittest.TestCase):
    def test_disabled_returns_input_order(self):
        import core.config as cfg

        prev = cfg.CROSS_RERANK_ENABLED
        cfg.CROSS_RERANK_ENABLED = False
        self.addCleanup(setattr, cfg, "CROSS_RERANK_ENABLED", prev)
        out = apply_cross_rerank("保修", _hits(), top_k=2)
        self.assertEqual([h.chunk.text for h in out], ["保修期三年", "退货七天"])

    def test_empty_stays_empty(self):
        self.assertEqual(apply_cross_rerank("任何问题", [], top_k=3), [])

    def test_missing_dep_falls_back(self):
        r = CrossReranker(model_name="no-such-model")
        # 未安装 flashrank 或模型缺失时必须原序返回，不抛异常
        out = r.rerank("保修", _hits(), top_k=2)
        self.assertEqual(len(out), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
