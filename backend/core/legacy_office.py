# -*- coding: utf-8 -*-
"""旧版 Office 解析（.doc/.xls/.ppt，纯 Python 轻量路线）

新版 docx/pptx/xlsx 已有专用库；旧版是 OLE2 复合文档，无专用解析器时
只能做文本抽取（排版/表格结构丢失，但至少可检索）。
依赖 olefile + xlrd，均为纯 Python、无 torch，体积可忽略。
"""

import sys
from pathlib import Path


def load_doc_ole(path: Path) -> str:
    """Word 97-2003 .doc：从 WordDocument 流中抽取可读文本"""
    try:
        import olefile
    except Exception as exc:
        raise RuntimeError(f"旧版 .doc 解析需 pip install olefile：{exc}")
    if not olefile.isOleFile(str(path)):
        raise ValueError("不是有效的 OLE 文档")
    ole = olefile.OleFileIO(str(path))
    try:
        if not ole.exists("WordDocument"):
            raise ValueError("未找到 WordDocument 流")
        data = ole.openstream("WordDocument").read()
    finally:
        ole.close()
    # 粗抽取：可打印 ASCII + CJK 片段，长度不足 2 的丢弃
    out: list[str] = []
    buf = ""
    for ch in data.decode("utf-16-le", errors="ignore"):
        if ch.isprintable() and (ch.strip() or ch == " "):
            buf += ch
        else:
            if len(buf.strip()) >= 2:
                out.append(buf.strip())
            buf = ""
    if len(buf.strip()) >= 2:
        out.append(buf.strip())
    # 去重去噪：过短碎片太多时只保留较长行
    lines = [l for l in out if len(l) >= 4]
    return "\n".join(lines[:2000])


def load_xls_ole(path: Path) -> str:
    """Excel 97-2003 .xls：经 xlrd 按表转 Markdown"""
    try:
        import xlrd
    except Exception as exc:
        raise RuntimeError(f"旧版 .xls 解析需 pip install xlrd：{exc}")
    from core.loader import _rows_to_markdown

    book = xlrd.open_workbook(str(path))
    sheets: list[str] = []
    for si in range(book.nsheets):
        sh = book.sheet_by_index(si)
        rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
        try:
            md = _rows_to_markdown(rows)
        except Exception as exc:
            print(f"[legacy] 表 {sh.name} 转换失败，已跳过：{exc}", file=sys.stderr)
            continue
        if md:
            sheets.append(f"## {sh.name}\n\n{md}")
    return "\n\n".join(sheets)


def load_ppt_ole(path: Path) -> str:
    """PowerPoint 97-2003 .ppt：从 PowerPoint Document 流粗抽文本"""
    try:
        import olefile
    except Exception as exc:
        raise RuntimeError(f"旧版 .ppt 解析需 pip install olefile：{exc}")
    if not olefile.isOleFile(str(path)):
        raise ValueError("不是有效的 OLE 文档")
    ole = olefile.OleFileIO(str(path))
    try:
        streams = [e for e in ole.listdir() if e and "PowerPoint" in e[0]]
        blobs = []
        for s in streams:
            try:
                blobs.append(ole.openstream(s).read())
            except Exception:
                continue
        if not blobs:
            raise ValueError("未找到演示文稿流")
        data = b"\n".join(blobs)
    finally:
        ole.close()
    out: list[str] = []
    buf = ""
    for ch in data.decode("utf-16-le", errors="ignore"):
        if ch.isprintable() and (ch.strip() or ch == " "):
            buf += ch
        else:
            if len(buf.strip()) >= 4:
                out.append(buf.strip())
            buf = ""
    if len(buf.strip()) >= 4:
        out.append(buf.strip())
    # 幻灯片碎片按长度过滤，避免二进制噪音
    lines = [l for l in out if 4 <= len(l) <= 2000][:2000]
    return "\n".join(lines)
