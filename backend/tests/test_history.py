# -*- coding: utf-8 -*-
"""对话历史 message 表的行为约束测试

只覆盖「改错了不会报错、只会让记录悄悄丢失」的逻辑，不依赖模型与网络。

为什么这几条值得测：
    1. 老库升级：_init_schema 用 CREATE TABLE IF NOT EXISTS，已有 rag.db 的用户
       重启后必须自动建出 message 表，否则历史接口全挂——发版回归靠这一条。
    2. 上限裁剪若写错 WHERE 条件，会把刚写入的行裁掉或把别的库裁掉。
    3. list 必须正序返回且带 limit 截断，否则前端恢复展示错乱。

运行：backend/.venv/Scripts/python -m unittest discover -s backend/tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.storage import Storage  # noqa: E402


class HistoryUpgradeTest(unittest.TestCase):
    """老库自动建表：先建无 message 表的旧库，再开 Storage 必须补上"""

    def test_old_db_gains_message_table(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "rag.db")
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE kb (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)")
            conn.execute(
                "CREATE TABLE doc (id TEXT PRIMARY KEY, kb_id TEXT NOT NULL, filename TEXT NOT NULL, "
                "chunk_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE chunk (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, "
                "kb_id TEXT NOT NULL, idx INTEGER NOT NULL, section TEXT, text TEXT NOT NULL)"
            )
            conn.commit()
            conn.close()

            s = Storage(db)
            kb = s.create_kb("旧库")
            s.add_message(kb["id"], "user", "你好")
            rows = s.list_messages(kb["id"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["text"], "你好")


class HistoryCrudTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Storage(str(Path(self._tmp.name) / "rag.db"))
        self.kb = self.s.create_kb("测试库")

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_and_list_order(self):
        """写入顺序 = 返回顺序（正序），role 与 sources 原样保留"""
        self.s.add_message(self.kb["id"], "user", "保修期几年？")
        self.s.add_message(self.kb["id"], "assistant", "三年。", '[{"title": "保修"}]')
        rows = self.s.list_messages(self.kb["id"])
        self.assertEqual([r["role"] for r in rows], ["user", "assistant"])
        self.assertEqual(rows[1]["sources"], '[{"title": "保修"}]')

    def test_limit_returns_latest(self):
        """limit 截最近 N 条，且仍是正序"""
        for i in range(5):
            self.s.add_message(self.kb["id"], "user", f"问题{i}")
        rows = self.s.list_messages(self.kb["id"], limit=2)
        self.assertEqual([r["text"] for r in rows], ["问题3", "问题4"])

    def test_isolated_per_kb(self):
        """按库隔离：A 库的记录不出现在 B 库"""
        other = self.s.create_kb("另一库")
        self.s.add_message(self.kb["id"], "user", "A 的问题")
        self.assertEqual(self.s.list_messages(other["id"]), [])

    def test_clear(self):
        self.s.add_message(self.kb["id"], "user", "q")
        self.assertEqual(self.s.clear_messages(self.kb["id"]), 1)
        self.assertEqual(self.s.list_messages(self.kb["id"]), [])

    def test_delete_kb_cascades_messages(self):
        """删库连带清历史，不留孤儿行"""
        self.s.add_message(self.kb["id"], "user", "q")
        self.s.delete_kb(self.kb["id"])
        other = self.s.create_kb("新库")
        self.assertEqual(self.s.list_messages(other["id"]), [])


class HistoryCapTest(unittest.TestCase):
    """上限裁剪：只裁本库最旧行，不动别的库"""

    def test_cap_trims_oldest_only(self):
        import core.storage as stor

        prev = stor.HISTORY_MAX_PER_KB
        stor.HISTORY_MAX_PER_KB = 3
        self.addCleanup(setattr, stor, "HISTORY_MAX_PER_KB", prev)
        with tempfile.TemporaryDirectory() as tmp:
            s = Storage(str(Path(tmp) / "rag.db"))
            a = s.create_kb("A")
            b = s.create_kb("B")
            for i in range(5):
                s.add_message(a["id"], "user", f"A{i}")
            s.add_message(b["id"], "user", "B0")
            rows_a = s.list_messages(a["id"], limit=10)
            self.assertEqual([r["text"] for r in rows_a], ["A2", "A3", "A4"])
            self.assertEqual(len(s.list_messages(b["id"])), 1)


class SessionTest(unittest.TestCase):
    """多会话的行为约束：只覆盖「错了不报错、只会悄悄记错地方」的逻辑"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Storage(str(Path(self._tmp.name) / "rag.db"))
        self.kb = self.s.create_kb("测试库")

    def tearDown(self):
        self._tmp.cleanup()

    def test_old_db_messages_migrated_to_default_session(self):
        """老库升级：无 session 表、无 session_id 列的库，旧消息自动归入默认会话"""
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "rag.db")
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE kb (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)")
            conn.execute("INSERT INTO kb VALUES ('kb1', '旧库', '2026-01-01 00:00:00')")
            conn.execute(
                "CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, kb_id TEXT NOT NULL, "
                "role TEXT NOT NULL, text TEXT NOT NULL, sources TEXT, created_at TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO message (kb_id, role, text, sources, created_at) "
                "VALUES ('kb1', 'user', '旧问题', NULL, '2026-01-01 00:00:01')"
            )
            conn.commit()
            conn.close()

            s = Storage(db)
            sessions = s.list_sessions("kb1")
            self.assertEqual(len(sessions), 1)
            rows = s.list_messages("kb1", session_id=sessions[0]["id"])
            self.assertEqual([r["text"] for r in rows], ["旧问题"])

    def test_sessions_isolated(self):
        """两会话互不可见；不传 session_id 返回整库（兼容旧客户端）"""
        a = self.s.create_session(self.kb["id"], "A")
        b = self.s.create_session(self.kb["id"], "B")
        self.s.add_message(self.kb["id"], "user", "问A", session_id=a["id"])
        self.s.add_message(self.kb["id"], "user", "问B", session_id=b["id"])
        self.assertEqual(
            [r["text"] for r in self.s.list_messages(self.kb["id"], session_id=a["id"])],
            ["问A"],
        )
        self.assertEqual(
            [r["text"] for r in self.s.list_messages(self.kb["id"], session_id=b["id"])],
            ["问B"],
        )
        self.assertEqual(len(self.s.list_messages(self.kb["id"])), 2)

    def test_default_session_auto_named_by_first_question(self):
        """缺省落会话：自动建会话，首问前 12 字命名，第二问不再改名"""
        self.s.add_message(self.kb["id"], "user", "保修期到底是几年时间呢请回答")
        sessions = self.s.list_sessions(self.kb["id"])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["name"], "保修期到底是几年时间呢请回答"[:12])
        self.s.add_message(
            self.kb["id"], "user", "换个问题", session_id=sessions[0]["id"]
        )
        self.assertEqual(
            self.s.list_sessions(self.kb["id"])[0]["name"], "保修期到底是几年时间呢请回答"[:12]
        )

    def test_cap_trims_per_session(self):
        """上限按会话裁：A 会话超限不影响 B 会话"""
        import core.storage as stor

        prev = stor.HISTORY_MAX_PER_KB
        stor.HISTORY_MAX_PER_KB = 3
        self.addCleanup(setattr, stor, "HISTORY_MAX_PER_KB", prev)
        a = self.s.create_session(self.kb["id"], "A")
        b = self.s.create_session(self.kb["id"], "B")
        for i in range(5):
            self.s.add_message(self.kb["id"], "user", f"A{i}", session_id=a["id"])
        self.s.add_message(self.kb["id"], "user", "B0", session_id=b["id"])
        self.assertEqual(
            [r["text"] for r in self.s.list_messages(self.kb["id"], limit=10, session_id=a["id"])],
            ["A2", "A3", "A4"],
        )
        self.assertEqual(len(self.s.list_messages(self.kb["id"], session_id=b["id"])), 1)

    def test_clear_scoped_to_session(self):
        """按会话清空只删该会话，整库清空保持旧语义"""
        a = self.s.create_session(self.kb["id"], "A")
        b = self.s.create_session(self.kb["id"], "B")
        self.s.add_message(self.kb["id"], "user", "问A", session_id=a["id"])
        self.s.add_message(self.kb["id"], "user", "问B", session_id=b["id"])
        self.assertEqual(self.s.clear_messages(self.kb["id"], session_id=a["id"]), 1)
        self.assertEqual(self.s.list_messages(self.kb["id"], session_id=a["id"]), [])
        self.assertEqual(len(self.s.list_messages(self.kb["id"], session_id=b["id"])), 1)
        self.s.clear_messages(self.kb["id"])
        self.assertEqual(self.s.list_messages(self.kb["id"], session_id=b["id"]), [])

    def test_delete_session_cascades_messages(self):
        """删会话连带清其消息；重命名空名拒绝；错库会话 id 校验失败"""
        a = self.s.create_session(self.kb["id"], "A")
        self.s.add_message(self.kb["id"], "user", "问A", session_id=a["id"])
        self.assertTrue(self.s.delete_session(self.kb["id"], a["id"]))
        self.assertEqual(self.s.list_messages(self.kb["id"], session_id=a["id"]), [])
        self.assertEqual(self.s.list_sessions(self.kb["id"]), [])

        b = self.s.create_session(self.kb["id"], "B")
        self.assertFalse(self.s.rename_session(self.kb["id"], b["id"], "   "))
        self.assertTrue(self.s.rename_session(self.kb["id"], b["id"], "新名"))
        self.assertEqual(self.s.list_sessions(self.kb["id"])[0]["name"], "新名")

        other = self.s.create_kb("另一库")
        self.assertIsNone(self.s.ensure_session(other["id"], b["id"]))
        self.assertFalse(self.s.delete_session(other["id"], b["id"]))

    def test_delete_kb_cascades_sessions(self):
        """删库连带清会话，不留孤儿会话"""
        a = self.s.create_session(self.kb["id"], "A")
        self.s.add_message(self.kb["id"], "user", "问A", session_id=a["id"])
        self.s.delete_kb(self.kb["id"])
        new_kb = self.s.create_kb("新库")
        self.assertEqual(self.s.list_sessions(new_kb["id"]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
