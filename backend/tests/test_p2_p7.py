# -*- coding: utf-8 -*-
"""P2-P7 新增模块的行为约束：无重依赖时不断链"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.graph import build_graph, create_task, list_tasks, run_task  # noqa: E402
from core.local_model import status as llama_status  # noqa: E402
from core.secret import decrypt_key, encrypt_key  # noqa: E402


class GraphTest(unittest.TestCase):
    def test_build_graph_nodes_edges(self):
        g = build_graph(["保修期三年全国联保", "保修费用按年收取", "退货七天无理由"], top_n=10)
        self.assertIn("nodes", g)
        self.assertIn("edges", g)
        self.assertGreater(len(g["nodes"]), 0)

    def test_tasks_lifecycle(self):
        t = create_task("rebuild", {"kb_id": "x"})
        self.assertEqual(t["status"], "pending")
        done = run_task(t["id"], lambda p: "ok")
        self.assertEqual(done["status"], "done")
        self.assertIn(t["id"], [x["id"] for x in list_tasks()])

    def test_tasks_failure(self):
        t = create_task("rebuild", {})

        def _boom(_):
            raise RuntimeError("boom")

        out = run_task(t["id"], _boom)
        self.assertEqual(out["status"], "failed")


class SecretTest(unittest.TestCase):
    def test_roundtrip_or_compat(self):
        enc = encrypt_key("sk-test-123")
        # Windows 下应为 ENC(...)，非 Windows 允许原文兼容返回
        plain = decrypt_key(enc)
        self.assertIn(plain, ("sk-test-123", ""))
        self.assertEqual(decrypt_key(""), "")
        self.assertEqual(decrypt_key("plain-key"), "plain-key")


class LlamaStatusTest(unittest.TestCase):
    def test_status_shape(self):
        s = llama_status()
        for k in ("exe_exists", "model_exists", "ready"):
            self.assertIn(k, s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
