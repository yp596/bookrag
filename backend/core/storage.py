# -*- coding: utf-8 -*-
"""持久化存储（SQLite）

为什么用 SQLite 而不是让 Chroma 兼管元数据：
    Chroma 负责向量，但知识库/文档/切片的组织关系属于业务数据。
    分开存放后，即便将来向量库换成 Qdrant，业务数据也不受影响。

存储三类数据：
    kb     知识库
    doc    文档（隶属于某个知识库）
    chunk  切片（隶属于某个文档，用于重建检索索引）

对话历史按会话存放：每库可有多个会话（session 表），问答（message）
归属某个会话。只做展示层持久化，重启后记录还在；
不送回模型做多轮，检索仍按单轮问题执行。

每次操作新建连接：SQLite 本地文件开销极小，可避免多线程共享连接的问题。
"""

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.config import DB_PATH, HISTORY_MAX_PER_KB
from core.splitter import Chunk

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kb (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doc (
    id          TEXT PRIMARY KEY,
    kb_id       TEXT NOT NULL,
    filename    TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    content_hash TEXT,
    tags TEXT DEFAULT '',
    status     TEXT DEFAULT 'completed',
    FOREIGN KEY (kb_id) REFERENCES kb(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chunk (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id   TEXT NOT NULL,
    kb_id    TEXT NOT NULL,
    idx      INTEGER NOT NULL,
    section  TEXT,
    text     TEXT NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES doc(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunk_kb  ON chunk(kb_id);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunk(doc_id);
CREATE INDEX IF NOT EXISTS idx_doc_kb    ON doc(kb_id);

CREATE TABLE IF NOT EXISTS message (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kb_id      TEXT NOT NULL,
    session_id TEXT,                -- 归属会话；老库迁移前为 NULL，由 _migrate_sessions 回填
    role       TEXT NOT NULL,        -- user / assistant
    text       TEXT NOT NULL,
    sources    TEXT,                 -- JSON：助手回答的引用来源，提问时为空
    created_at TEXT NOT NULL,
    feedback    TEXT,                 -- 用户反馈（up/down）
    FOREIGN KEY (kb_id) REFERENCES kb(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS session (
    id         TEXT PRIMARY KEY,
    kb_id      TEXT NOT NULL,
    doc_id     TEXT,                -- 归属文档；NULL 表示知识库级会话
    name       TEXT NOT NULL DEFAULT '新会话',
    created_at TEXT NOT NULL,
    FOREIGN KEY (kb_id) REFERENCES kb(id) ON DELETE CASCADE,
    FOREIGN KEY (doc_id) REFERENCES doc(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_msg_kb ON message(kb_id, id);
CREATE INDEX IF NOT EXISTS idx_session_kb ON session(kb_id);

CREATE TABLE IF NOT EXISTS user_preference (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class Storage:
    """知识库元数据与切片的持久化"""

    def __init__(self, db_path: Path | str = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """每次操作新建连接，用完提交即关。

        sqlite3.Connection 自身的 with 只管提交不管关闭，连接靠 GC 回收：
        回收时机的不确定会让 db 文件句柄 lingering，Windows 下删临时库时
        报 WinError 32。这里显式 commit/rollback + close，不依赖回收时机。
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            # 老库升级：message 表可能没有 session_id 列（CREATE TABLE IF NOT EXISTS 不补列）
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(message)").fetchall()]
            if "session_id" not in cols:
                conn.execute("ALTER TABLE message ADD COLUMN session_id TEXT")
            # 列就绪后才能建索引（老库走 ALTER，新库走 CREATE TABLE，统一在此补）
            conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_session ON message(session_id, id)")
            # 老库升级：session 表可能没有 doc_id 列
            session_cols = [r["name"] for r in conn.execute("PRAGMA table_info(session)").fetchall()]
            if "doc_id" not in session_cols:
                conn.execute("ALTER TABLE session ADD COLUMN doc_id TEXT")
            self._migrate_sessions(conn)

    @staticmethod
    def _migrate_sessions(conn: sqlite3.Connection) -> None:
        """老库迁移：把无归属会话的历史消息并入每库一个"默认会话"。

        只处理 session_id IS NULL 的行，已迁移过的库无操作，可重复执行。
        """
        rows = conn.execute(
            "SELECT DISTINCT kb_id FROM message WHERE session_id IS NULL"
        ).fetchall()
        for r in rows:
            kb_id = r["kb_id"]
            sess = conn.execute(
                "SELECT id FROM session WHERE kb_id = ? ORDER BY created_at LIMIT 1",
                (kb_id,),
            ).fetchone()
            if sess is None:
                sid = _new_id()
                conn.execute(
                    "INSERT INTO session (id, kb_id, name, created_at) VALUES (?, ?, ?, ?)",
                    (sid, kb_id, "默认会话", _now()),
                )
            else:
                sid = sess["id"]
            conn.execute(
                "UPDATE message SET session_id = ? WHERE kb_id = ? AND session_id IS NULL",
                (sid, kb_id),
            )

    # ====================== 知识库 ======================
    def create_kb(self, name: str) -> dict:
        """新建知识库"""
        kb_id = _new_id()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO kb (id, name, created_at) VALUES (?, ?, ?)",
                (kb_id, name.strip() or "未命名知识库", _now()),
            )
        return self.get_kb(kb_id)

    def get_kb(self, kb_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM kb WHERE id = ?", (kb_id,)).fetchone()
        return dict(row) if row else None

    def list_kbs(self) -> list[dict]:
        """列出全部知识库，附带文档数与切片数"""
        sql = """
            SELECT k.id, k.name, k.created_at,
                   COUNT(DISTINCT d.id) AS doc_count,
                   COUNT(c.id)          AS chunk_count
            FROM kb k
            LEFT JOIN doc d   ON d.kb_id = k.id
            LEFT JOIN chunk c ON c.kb_id = k.id
            GROUP BY k.id
            ORDER BY k.created_at DESC
        """
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def delete_kb(self, kb_id: str) -> bool:
        """删除知识库及其全部文档、切片、会话与对话历史"""
        with self._connect() as conn:
            conn.execute("DELETE FROM message WHERE kb_id = ?", (kb_id,))
            conn.execute("DELETE FROM session WHERE kb_id = ?", (kb_id,))
            conn.execute("DELETE FROM chunk WHERE kb_id = ?", (kb_id,))
            conn.execute("DELETE FROM doc   WHERE kb_id = ?", (kb_id,))
            cur = conn.execute("DELETE FROM kb WHERE id = ?", (kb_id,))
            return cur.rowcount > 0

    # ====================== 文档 ======================
    def add_document(self, kb_id: str, filename: str, chunks: list[Chunk]) -> dict:
        """写入一个文档及其切片，自动去重

        去重策略：计算文档内容的哈希值，如果已存在相同内容的文档，
        返回已存在的文档，不重复导入。
        """
        import hashlib

        # 计算文档内容的哈希值
        content = "".join(c.text for c in chunks)
        content_hash = hashlib.md5(content.encode()).hexdigest()

        # 检查是否已存在相同内容的文档
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM doc WHERE kb_id = ? AND content_hash = ?",
                (kb_id, content_hash),
            ).fetchone()
            if existing:
                return dict(existing)

        # 不存在重复，写入新文档
        doc_id = _new_id()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO doc (id, kb_id, filename, chunk_count, created_at, content_hash) VALUES (?, ?, ?, ?, ?, ?)",
                (doc_id, kb_id, filename, len(chunks), _now(), content_hash),
            )
            conn.executemany(
                "INSERT INTO chunk (doc_id, kb_id, idx, section, text) VALUES (?, ?, ?, ?, ?)",
                [(doc_id, kb_id, c.index, c.section, c.text) for c in chunks],
            )
        return self.get_document(doc_id)
        """写入一个文档及其切片"""
        doc_id = _new_id()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO doc (id, kb_id, filename, chunk_count, created_at) VALUES (?, ?, ?, ?, ?)",
                (doc_id, kb_id, filename, len(chunks), _now()),
            )
            conn.executemany(
                "INSERT INTO chunk (doc_id, kb_id, idx, section, text) VALUES (?, ?, ?, ?, ?)",
                [(doc_id, kb_id, c.index, c.section, c.text) for c in chunks],
            )
        return self.get_document(doc_id)

    def get_document(self, doc_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM doc WHERE id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None

    def list_documents(self, kb_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM doc WHERE kb_id = ? ORDER BY created_at DESC", (kb_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_document(self, doc_id: str) -> bool:
        """删除文档及其切片"""
        with self._connect() as conn:
            conn.execute("DELETE FROM chunk WHERE doc_id = ?", (doc_id,))
            cur = conn.execute("DELETE FROM doc WHERE id = ?", (doc_id,))
            return cur.rowcount > 0

    def clear_documents(self, kb_id: str) -> dict:
        """清空某库的全部文档与切片，保留空库与对话历史。

        历史消息的 sources 是入库时的文本快照，不依赖 doc 表，
        清空后旧记录仍可查看，故不联删。
        """
        with self._connect() as conn:
            conn.execute("DELETE FROM chunk WHERE kb_id = ?", (kb_id,))
            cur = conn.execute("DELETE FROM doc WHERE kb_id = ?", (kb_id,))
            return {"docs": cur.rowcount}

    def restore_kb(self, kb_id: str, name: str, created_at: str) -> None:
        """恢复知识库（指定 ID）"""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO kb (id, name, created_at) VALUES (?, ?, ?)",
                (kb_id, name, created_at),
            )

    def restore_document(self, doc_id: str, kb_id: str, filename: str, chunk_count: int, created_at: str) -> None:
        """恢复文档（指定 ID）"""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO doc (id, kb_id, filename, chunk_count, created_at) VALUES (?, ?, ?, ?, ?)",
                (doc_id, kb_id, filename, chunk_count, created_at),
            )

    def restore_chunk(self, doc_id: str, kb_id: str, idx: int, section: str, text: str) -> None:
        """恢复切片（指定 doc_id）"""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chunk (doc_id, kb_id, idx, section, text) VALUES (?, ?, ?, ?, ?)",
                (doc_id, kb_id, idx, section, text),
            )

    def restore_session(self, sess_id: str, kb_id: str, doc_id: str | None, name: str, created_at: str) -> None:
        """恢复会话（指定 ID）"""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO session (id, kb_id, doc_id, name, created_at) VALUES (?, ?, ?, ?, ?)",
                (sess_id, kb_id, doc_id, name, created_at),
            )

    def restore_message(self, kb_id: str, session_id: str | None, role: str, text: str, sources: str | None, created_at: str) -> None:
        """恢复消息（指定 session_id）"""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO message (kb_id, session_id, role, text, sources, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (kb_id, session_id, role, text, sources, created_at),
            )

    # ====================== 切片 ======================
    def get_chunks(self, kb_id: str) -> list[Chunk]:
        """读取某知识库的全部切片，用于重建检索索引"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.*, d.filename FROM chunk c JOIN doc d ON d.id = c.doc_id "
                "WHERE c.kb_id = ? ORDER BY c.doc_id, c.idx",
                (kb_id,),
            ).fetchall()
        return [
            Chunk(
                text=r["text"],
                source=r["filename"],
                index=r["idx"],
                section=r["section"] or "",
            )
            for r in rows
        ]

    def search_chunks(self, kb_id: str, query: str, limit: int = 20) -> list[dict]:
        """搜索知识库内切片，返回匹配的片段（含文档名与相关度）"""
        sql = """
            SELECT c.*, d.filename,
                   (LENGTH(c.text) - LENGTH(REPLACE(LOWER(c.text), LOWER(?), ''))) / LENGTH(?) AS score
            FROM chunk c JOIN doc d ON d.id = c.doc_id
            WHERE c.kb_id = ? AND LOWER(c.text) LIKE '%' || LOWER(?) || '%'
            ORDER BY score DESC, c.idx
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (query, query, kb_id, query, limit)).fetchall()
        return [dict(r) for r in rows]

    def list_chunks_by_doc(self, doc_id: str, limit: int = 100) -> list[dict]:
        """读取某文档的全部切片"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chunk WHERE doc_id = ? ORDER BY idx LIMIT ?",
                (doc_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ====================== 会话 ======================
    def create_session(self, kb_id: str, name: str | None = None, doc_id: str | None = None) -> dict:
        """新建会话。未命名时叫"新会话"，首条提问到达时按内容自动命名"""
        sid = _new_id()
        now = _now()
        clean = (name or "").strip() or "新会话"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO session (id, kb_id, doc_id, name, created_at) VALUES (?, ?, ?, ?, ?)",
                (sid, kb_id, doc_id, clean, now),
            )
        return {"id": sid, "kb_id": kb_id, "doc_id": doc_id, "name": clean, "created_at": now}

    def list_sessions(self, kb_id: str, doc_id: str | None = None) -> list[dict]:
        """列出某库某文档的会话，按最近活跃倒序（无消息的排后面）"""
        sql = """
            SELECT s.id, s.kb_id, s.doc_id, s.name, s.created_at,
                   COUNT(m.id) AS msg_count,
                   COALESCE(MAX(m.id), 0) AS last_msg_id
            FROM session s LEFT JOIN message m ON m.session_id = s.id
            WHERE s.kb_id = ?
        """
        params: list = [kb_id]
        if doc_id is not None:
            sql += " AND s.doc_id = ?"
            params.append(doc_id)
        sql += " GROUP BY s.id ORDER BY last_msg_id DESC, s.created_at DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def rename_session(self, kb_id: str, session_id: str, name: str) -> bool:
        """重命名会话，空名拒绝（返回 False，不落库）"""
        clean = (name or "").strip()
        if not clean:
            return False
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE session SET name = ? WHERE id = ? AND kb_id = ?",
                (clean, session_id, kb_id),
            )
            return cur.rowcount > 0

    def delete_session(self, kb_id: str, session_id: str) -> bool:
        """删除会话及其全部消息，返回会话是否存在"""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM message WHERE kb_id = ? AND session_id = ?",
                (kb_id, session_id),
            )
            cur = conn.execute(
                "DELETE FROM session WHERE id = ? AND kb_id = ?", (session_id, kb_id)
            )
            return cur.rowcount > 0

    def ensure_session(self, kb_id: str, session_id: str | None = None, doc_id: str | None = None) -> dict | None:
        """解析会话：指定 id 则校验归属（错库/不存在返回 None）；
        缺省则取最近活跃的，尚无会话时懒建一个"新会话"。

        问答接口的老客户端不传 session_id，走缺省分支，记录进默认会话，
        不报错、不丢失。
        """
        with self._connect() as conn:
            if session_id:
                if doc_id:
                    row = conn.execute(
                        "SELECT * FROM session WHERE id = ? AND kb_id = ? AND doc_id = ?",
                        (session_id, kb_id, doc_id),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT * FROM session WHERE id = ? AND kb_id = ?",
                        (session_id, kb_id),
                    ).fetchone()
                return dict(row) if row else None
            if doc_id:
                row = conn.execute(
                    "SELECT s.* FROM session s LEFT JOIN message m ON m.session_id = s.id "
                    "WHERE s.kb_id = ? AND s.doc_id = ? GROUP BY s.id "
                    "ORDER BY COALESCE(MAX(m.id), 0) DESC, s.created_at DESC LIMIT 1",
                    (kb_id, doc_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT s.* FROM session s LEFT JOIN message m ON m.session_id = s.id "
                    "WHERE s.kb_id = ? GROUP BY s.id "
                    "ORDER BY COALESCE(MAX(m.id), 0) DESC, s.created_at DESC LIMIT 1",
                    (kb_id,),
                ).fetchone()
            if row:
                return dict(row)
            sid = _new_id()
            now = _now()
            conn.execute(
                "INSERT INTO session (id, kb_id, doc_id, name, created_at) VALUES (?, ?, ?, ?, ?)",
                (sid, kb_id, doc_id, "新会话", now),
            )
            return {"id": sid, "kb_id": kb_id, "doc_id": doc_id, "name": "新会话", "created_at": now}

    # ====================== 对话历史 ======================
    def add_message(
        self,
        kb_id: str,
        role: str,
        text: str,
        sources: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """追加一条对话记录，返回该行。超限时按会话裁掉最旧的多余行"""
        sess = self.ensure_session(kb_id, session_id)
        if sess is None:
            raise ValueError(f"会话不存在：{session_id}")
        sid = sess["id"]
        with self._connect() as conn:
            # "新会话"尚未命名：用首条提问的前 12 字命名，只做一次
            if role == "user" and (sess.get("name") or "").strip() in ("新会话", ""):
                auto = text.strip()[:12]
                if auto:
                    conn.execute("UPDATE session SET name = ? WHERE id = ?", (auto, sid))
            cur = conn.execute(
                "INSERT INTO message (kb_id, session_id, role, text, sources, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (kb_id, sid, role, text, sources, _now()),
            )
            row_id = cur.lastrowid
            # 桌面单机场景，单会话 200 条上限足够；按会话裁剪保证 db 文件不膨胀
            conn.execute(
                "DELETE FROM message WHERE kb_id = ? AND session_id = ? AND id NOT IN "
                "(SELECT id FROM message WHERE kb_id = ? AND session_id = ? "
                "ORDER BY id DESC LIMIT ?)",
                (kb_id, sid, kb_id, sid, HISTORY_MAX_PER_KB),
            )
            row = conn.execute("SELECT * FROM message WHERE id = ?", (row_id,)).fetchone()
        return dict(row)

    def list_messages(
        self, kb_id: str, limit: int = 100, session_id: str | None = None
    ) -> list[dict]:
        """按时间正序列出对话记录（展示用），默认最近 100 条。

        session_id 缺省时返回整库记录（兼容旧客户端）；前端多会话下必传。
        """
        with self._connect() as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT * FROM (SELECT * FROM message WHERE kb_id = ? AND session_id = ? "
                    "ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
                    (kb_id, session_id, max(limit, 1)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM (SELECT * FROM message WHERE kb_id = ? ORDER BY id DESC LIMIT ?) "
                    "ORDER BY id ASC",
                    (kb_id, max(limit, 1)),
                ).fetchall()
        return [dict(r) for r in rows]

    def clear_messages(self, kb_id: str, session_id: str | None = None) -> int:
        """清空对话记录：传 session_id 只清该会话，缺省清整库（兼容旧语义）。
        返回删除条数"""
        with self._connect() as conn:
            if session_id:
                cur = conn.execute(
                    "DELETE FROM message WHERE kb_id = ? AND session_id = ?",
                    (kb_id, session_id),
                )
            else:
                cur = conn.execute("DELETE FROM message WHERE kb_id = ?", (kb_id,))
            return cur.rowcount

    def update_document(self, doc_id: str, chunks: list[Chunk]) -> bool:
        """增量更新：只重新索引修改过的文档

        Args:
            doc_id: 文档 ID
            chunks: 新的切片列表

        Returns:
            是否更新成功
        """
        with self._connect() as conn:
            # 获取文档的 kb_id
            doc_row = conn.execute("SELECT kb_id FROM doc WHERE id = ?", (doc_id,)).fetchone()
            if not doc_row:
                return False
            kb_id = doc_row["kb_id"]

            # 删除旧切片
            conn.execute("DELETE FROM chunk WHERE doc_id = ?", (doc_id,))
            # 插入新切片
            conn.executemany(
                "INSERT INTO chunk (doc_id, kb_id, idx, section, text) VALUES (?, ?, ?, ?, ?)",
                [(doc_id, kb_id, c.index, c.section, c.text) for c in chunks],
            )
            # 更新文档信息
            conn.execute(
                "UPDATE doc SET chunk_count = ?, created_at = ? WHERE id = ?",
                (len(chunks), _now(), doc_id),
            )
            return True
            # 删除旧切片
            conn.execute("DELETE FROM chunk WHERE doc_id = ?", (doc_id,))
            # 插入新切片
            conn.executemany(
                "INSERT INTO chunk (doc_id, kb_id, idx, section, text) VALUES (?, ?, ?, ?, ?)",
                [(doc_id, c.kb_id, c.index, c.section, c.text) for c in chunks],
            )
            # 更新文档信息
            conn.execute(
                "UPDATE doc SET chunk_count = ?, created_at = ? WHERE id = ?",
                (len(chunks), _now(), doc_id),
            )
            return True

    def set_document_tags(self, doc_id: str, tags: list[str]) -> bool:
        """设置文档标签

        Args:
            doc_id: 文档 ID
            tags: 标签列表

        Returns:
            是否设置成功
        """
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE doc SET tags = ? WHERE id = ?",
                (",".join(tags), doc_id),
            )
            return cur.rowcount > 0

    def get_document_tags(self, doc_id: str) -> list[str]:
        """获取文档标签

        Args:
            doc_id: 文档 ID

        Returns:
            标签列表
        """
        with self._connect() as conn:
            row = conn.execute("SELECT tags FROM doc WHERE id = ?", (doc_id,)).fetchone()
            if not row or not row["tags"]:
                return []
            return [t.strip() for t in row["tags"].split(",") if t.strip()]

    def filter_by_tags(self, kb_id: str, tags: list[str]) -> list[dict]:
        """按标签过滤文档

        Args:
            kb_id: 知识库 ID
            tags: 标签列表

        Returns:
            符合条件的文档列表
        """
        with self._connect() as conn:
            if not tags:
                return self.list_documents(kb_id)

            # 构建查询条件
            conditions = []
            params = [kb_id]
            for tag in tags:
                conditions.append("tags LIKE ?")
                params.append(f"%{tag}%")

            rows = conn.execute(
                f"SELECT * FROM doc WHERE kb_id = ? AND ({' OR '.join(conditions)})",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def get_kb_stats(self, kb_id: str) -> dict:
        """知识库统计：文档数、切片数、存储占用

        Args:
            kb_id: 知识库 ID

        Returns:
            统计信息字典
        """
        with self._connect() as conn:
            # 文档数
            doc_count = conn.execute(
                "SELECT COUNT(*) FROM doc WHERE kb_id = ?", (kb_id,)
            ).fetchone()[0]

            # 切片数
            chunk_count = conn.execute(
                "SELECT COUNT(*) FROM chunk WHERE kb_id = ?", (kb_id,)
            ).fetchone()[0]

            # 存储占用（切片总字符数）
            total_chars = conn.execute(
                "SELECT COALESCE(SUM(LENGTH(text)), 0) FROM chunk WHERE kb_id = ?", (kb_id,)
            ).fetchone()[0]

            # 会话数
            session_count = conn.execute(
                "SELECT COUNT(*) FROM session WHERE kb_id = ?", (kb_id,)
            ).fetchone()[0]

            # 消息数
            message_count = conn.execute(
                "SELECT COUNT(*) FROM message WHERE kb_id = ?", (kb_id,)
            ).fetchone()[0]

            return {
                "doc_count": doc_count,
                "chunk_count": chunk_count,
                "total_chars": total_chars,
                "session_count": session_count,
                "message_count": message_count,
            }

    def set_user_preference(self, key: str, value: str) -> bool:
        """设置用户偏好

        Args:
            key: 偏好键
            value: 偏好值

        Returns:
            是否设置成功
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_preference (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, _now()),
            )
            return True

    def get_user_preference(self, key: str) -> str | None:
        """获取用户偏好

        Args:
            key: 偏好键

        Returns:
            偏好值，不存在时返回 None
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM user_preference WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def get_all_preferences(self) -> dict[str, str]:
        """获取所有用户偏好

        Returns:
            偏好字典
        """
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM user_preference").fetchall()
            return {r["key"]: r["value"] for r in rows}

    def update_message_feedback(self, msg_id: int, feedback: str | None) -> bool:
        """更新消息反馈（点赞/点踩）

        Args:
            msg_id: 消息 ID
            feedback: 反馈类型（'up' 或 'down'），None 表示清除反馈

        Returns:
            是否更新成功
        """
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE message SET feedback = ? WHERE id = ?",
                (feedback, msg_id),
            )
            return cur.rowcount > 0

    def update_document_status(self, doc_id: str, status: str) -> bool:
        """更新文档状态

        Args:
            doc_id: 文档 ID
            status: 状态（pending/processing/completed/failed）

        Returns:
            是否更新成功
        """
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE doc SET status = ? WHERE id = ?",
                (status, doc_id),
            )
            return cur.rowcount > 0
