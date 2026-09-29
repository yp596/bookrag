# -*- coding: utf-8 -*-
"""知识图谱（轻量关键词共现）+ Agent 任务面板（最小可用）

图谱：以 jieba 名词/实词为节点，同一切片中共现即连边。
不做大模型抽取、不引入图数据库，前端拿 JSON 即可渲染。
Agent：极简任务队列（入库/抓取/重建索引），状态机 pending/running/done/failed，
供前端任务面板轮询。均为展示层能力，不影响检索主链路。
"""

import re
import time
import uuid
from collections import Counter


def extract_keywords(text: str, top_n: int = 20) -> list[str]:
    try:
        import jieba.posseg as pseg
    except Exception:
        import jieba

        words = [w.strip() for w in jieba.cut(text) if len(w.strip()) > 1]
        return [w for w, _ in Counter(words).most_common(top_n)]
    keep_flag = {"n", "nz", "l", "eng", "nr", "ns", "nt", "nw", "vn"}
    words = [w.word.strip() for w in pseg.cut(text) if w.flag in keep_flag and len(w.word.strip()) > 1]
    return [w for w, _ in Counter(words).most_common(top_n)]


def build_graph(chunks: list, top_n: int = 30, max_edges: int = 100) -> dict:
    """chunks 为 Chunk 列表或纯文本列表，返回 {nodes, edges}"""
    texts = [c.text if hasattr(c, "text") else str(c) for c in chunks]
    full = "\n".join(texts)
    keywords = extract_keywords(full, top_n=top_n)
    kwset = set(keywords)
    nodes = [{"id": k, "label": k, "size": full.count(k)} for k in keywords]
    edge_counter: Counter = Counter()
    for t in texts:
        present = [k for k in kwset if k in t]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                a, b = sorted((present[i], present[j]))
                edge_counter[(a, b)] += 1
    edges = [{"source": a, "target": b, "weight": w} for (a, b), w in edge_counter.most_common(max_edges)]
    return {"nodes": nodes, "edges": edges}


# ---------- Agent 任务面板：内存队列 + 落库可选 ----------
_TASKS: dict[str, dict] = {}


def create_task(kind: str, payload: dict | None = None) -> dict:
    tid = uuid.uuid4().hex[:12]
    task = {"id": tid, "kind": kind, "payload": payload or {},
            "status": "pending", "created": time.time(), "message": ""}
    _TASKS[tid] = task
    return task


def run_task(tid: str, fn) -> dict:
    task = _TASKS.get(tid)
    if not task:
        raise KeyError(tid)
    task["status"] = "running"
    try:
        result = fn(task["payload"])
        task["status"] = "done"
        task["message"] = str(result)[:500]
    except Exception as exc:
        task["status"] = "failed"
        task["message"] = str(exc)[:500]
    return task


def list_tasks() -> list[dict]:
    return sorted(_TASKS.values(), key=lambda t: -t["created"])

def _is_chinese_punct(ch: str) -> bool:
    return bool(re.match(r"[　-〿＀-￯]", ch))
