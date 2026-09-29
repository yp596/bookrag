# -*- coding: utf-8 -*-
"""文档管理与切片配置的行为约束测试

只覆盖「改错了不会报错、只会静默丢数据」的逻辑，不依赖模型与网络。

为什么这几条值得测：
    1. clear_documents 的 WHERE 若漏写 kb_id，会清空全库文档。
    2. 切片钳制若失效，overlap >= size 会让二次切分步进归零、陷入死循环。
    3. 手工改坏的 settings.json 不能拖垮服务，get 必须钳制后返回。

运行：backend/.venv/Scripts/python -m unittest discover -s backend/tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.settings_store import SettingsStore  # noqa: E402
from core.storage import Storage  # noqa: E402


class ClearDocumentsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Storage(str(Path(self._tmp.name) / "rag.db"))
        self.kb_a = self.s.create_kb("A")
        self.kb_b = self.s.create_kb("B")

    def tearDown(self):
        self._tmp.cleanup()

    def _add_doc(self, kb_id, name="d.txt"):
        from core.splitter import Chunk

        return self.s.add_document(
            kb_id, name, [Chunk(text="内容", source=name, index=0)]
        )

    def test_clear_keeps_kb_and_other_kb(self):
        self._add_doc(self.kb_a["id"])
        self._add_doc(self.kb_b["id"], "e.txt")
        result = self.s.clear_documents(self.kb_a["id"])
        self.assertEqual(result["docs"], 1)
        self.assertIsNotNone(self.s.get_kb(self.kb_a["id"]))
        self.assertEqual(len(self.s.list_documents(self.kb_a["id"])), 0)
        self.assertEqual(len(self.s.list_documents(self.kb_b["id"])), 1)
        self.assertEqual(len(self.s.get_chunks(self.kb_b["id"])), 1)

    def test_clear_empty_kb(self):
        self.assertEqual(self.s.clear_documents(self.kb_a["id"]), {"docs": 0})

    def test_clear_keeps_history(self):
        self._add_doc(self.kb_a["id"])
        self.s.add_message(self.kb_a["id"], "user", "你好")
        self.s.clear_documents(self.kb_a["id"])
        self.assertEqual(len(self.s.list_messages(self.kb_a["id"])), 1)


class ChunkClampTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = SettingsStore(str(Path(self._tmp.name) / "settings.json"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_defaults(self):
        data = self.store.get()
        self.assertEqual(data["chunk_size"], 800)
        self.assertEqual(data["chunk_overlap"], 100)

    def test_out_of_range_clamped(self):
        data = self.store.save({"chunk_size": 99999, "chunk_overlap": 99999})
        self.assertEqual(data["chunk_size"], 2000)
        self.assertLess(data["chunk_overlap"], data["chunk_size"])

    def test_overlap_never_reaches_size(self):
        data = self.store.save({"chunk_size": 200, "chunk_overlap": 500})
        self.assertLess(data["chunk_overlap"], 200)

    def test_broken_file_still_clamped(self):
        self.store.path.write_text(
            json.dumps({"chunk_size": 10, "chunk_overlap": 50}), encoding="utf-8"
        )
        data = self.store.get()
        self.assertGreaterEqual(data["chunk_size"], 200)
        self.assertLess(data["chunk_overlap"], data["chunk_size"])


if __name__ == "__main__":
    unittest.main()
