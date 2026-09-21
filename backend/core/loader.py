# -*- coding: utf-8 -*-
"""文档解析

按扩展名选择解析器，统一输出纯文本，交给 splitter 切片。

支持的格式：
    .pdf    pypdf
    .txt    Python 内置读取（自动尝试多编码）
    .md     Python 内置读取
    .docx   python-docx（含表格文本）
"""

from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".docx"}


class UnsupportedFormatError(Exception):
    """不支持的文件格式"""


def _read_text_file(path: Path) -> str:
    """读取纯文本文件，按常见编码依次尝试，避免中文乱码"""
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    # 全部失败时用 utf-8 容错模式兜底
    return path.read_text(encoding="utf-8", errors="ignore")


def _load_pdf(path: Path) -> str:
    """解析 PDF。注意：扫描件/图片型 PDF 提取不到文字，需 OCR 预处理"""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            # 保留页码信息，便于后续引用溯源
            pages.append(f"【第 {i + 1} 页】\n{text.strip()}")
    return "\n\n".join(pages)


def _load_docx(path: Path) -> str:
    """解析 Word 文档，正文段落与表格文本一并提取"""
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []

    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())

    # 表格内容按行拼接，单元格用 | 分隔
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    return "\n".join(parts)


def load_document(path: str | Path) -> str:
    """解析文档，返回纯文本

    Args:
        path: 文档路径

    Returns:
        提取出的纯文本

    Raises:
        FileNotFoundError: 文件不存在
        UnsupportedFormatError: 扩展名不受支持
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFormatError(
            f"不支持的格式：{suffix}，当前支持 {'、'.join(sorted(SUPPORTED_SUFFIXES))}"
        )

    if suffix == ".pdf":
        text = _load_pdf(path)
    elif suffix == ".docx":
        text = _load_docx(path)
    else:
        text = _read_text_file(path)

    if not text.strip():
        raise ValueError(
            f"未能从 {path.name} 中提取到文字。"
            "若为扫描件或图片型 PDF，需要先做 OCR 处理。"
        )
    return text
