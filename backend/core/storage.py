# -*- coding: utf-8 -*-
"""持久化存储（SQLite）

为什么用 SQLite 而不是让 Chroma 兼管元数据：
    Chroma 负责向量，但知识库/文档/切片的组织关系属于业务数据。
    分开存放后，即便将来向量库换成 Qdrant，业务数据也不受影响。

存储三类数据：
    kb     知识库
    doc    文档（隶属于某个知识库）
    chunk  切片（隶属于某个文档，用于重建检索索引）

每次操作新建连接：SQLite 本地文件开销极小，可避免多线程共享连接的问题。
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from core.config import DB_PATH
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

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

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
        """删除知识库及其全部文档与切片"""
        with self._connect() as conn:
            conn.execute("DELETE FROM chunk WHERE kb_id = ?", (kb_id,))
            conn.execute("DELETE FROM doc   WHERE kb_id = ?", (kb_id,))
            cur = conn.execute("DELETE FROM kb WHERE id = ?", (kb_id,))
            return cur.rowcount > 0

    # ====================== 文档 ======================
    def add_document(self, kb_id: str, filename: str, chunks: list[Chunk]) -> dict:
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
