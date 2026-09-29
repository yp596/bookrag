# -*- coding: utf-8 -*-
"""文档解析

按扩展名选择解析器，统一输出纯文本，交给 splitter 切片。

支持的格式：
    .pdf    pypdf（正文）+ pdfplumber（表格转 Markdown，纯 Python 无 torch）
    .txt    Python 内置读取（自动尝试多编码）
    .md     Python 内置读取
    .docx   python-docx（正文段落 + 表格转 Markdown）
    .pptx   python-pptx（幻灯片文本 + 表内表格转 Markdown）
    .xlsx   openpyxl（各工作表按行转 Markdown，一表一节）
    URL     标准库抓取 + 正文提取（见 fetch_url，不引入新依赖）
"""

import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".docx", ".pptx", ".xlsx",
                        ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif",
                        ".doc", ".xls", ".ppt"}

# 抓取 guard：桌面单机场景够用即可，不做 IP 黑名单——
# 公司内网 wiki 是 URL 导入的正当用途，拦私有地址会误伤；
# 用户粘的是自己的链接，不存在第三方 SSRF 攻击面。
FETCH_TIMEOUT = 15              # 单次抓取超时（秒）
FETCH_MAX_BYTES = 5 * 1024 * 1024   # 最多读 5MB，防超大文件打爆内存
FETCH_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) bookrag/1.0"  # 有些站拦默认 UA


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


def _rows_to_markdown(rows: list[list]) -> str:
    """二维单元格转 Markdown 表格，供检索链路直接消费。

    取首行做表头：Markdown 表格语法要求表头行，问答引用时也更规整。
    单元格内的换行压成空格、竖线转义，避免破坏表格结构。
    全空行丢弃；不足两行（无数据行）返回空串，由调用方跳过。
    """
    def clean(cell) -> str:
        return str(cell or "").replace("\n", " ").replace("|", "\\|").strip()

    body = [[clean(c) for c in row] for row in rows]
    body = [r for r in body if any(r)]
    if len(body) < 2:
        return ""
    width = max(len(r) for r in body)
    body = [r + [""] * (width - len(r)) for r in body]
    lines = [
        "| " + " | ".join(body[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(r) + " |" for r in body[1:])
    return "\n".join(lines)


def _load_pdf(path: Path) -> str:
    """解析 PDF：正文走 pypdf，表格走 pdfplumber 转 Markdown 后附在当页正文之后。

    表格缺失是最伤检索的一类信息丢失——"保修期是几年"这类答案常在表格里，
    而 pypdf 只抽得出散落的单元格碎词，BM25 与向量都对不上。
    pdfplumber 缺席时（极端精简环境）退化为纯 pypdf，不阻断导入。
    注意：扫描件/图片型 PDF 提取不到文字，需 OCR 预处理。
    """
    from pypdf import PdfReader

    try:
        import pdfplumber

        tables_per_page: list[list[list[list]]] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                tables_per_page.append(page.extract_tables() or [])
    except ImportError:
        print("[loader] pdfplumber 缺失，PDF 表格将被跳过", file=sys.stderr)
        tables_per_page = []

    reader = PdfReader(str(path))
    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        parts = [text.strip()] if text.strip() else []
        if i < len(tables_per_page):
            for table in tables_per_page[i]:
                md = _rows_to_markdown(table)
                if md:
                    parts.append(md)
        if parts:
            # 保留页码信息，便于后续引用溯源
            pages.append(f"【第 {i + 1} 页】\n" + "\n\n".join(parts))
    return "\n\n".join(pages)


def _load_docx(path: Path) -> str:
    """解析 Word 文档，正文段落与表格文本一并提取"""
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []

    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())

    # 表格转 Markdown，与 PDF 表格同一格式，检索行为一致
    for table in doc.tables:
        md = _rows_to_markdown([[c.text for c in row.cells] for row in table.rows])
        if md:
            parts.append(md)

    return "\n".join(parts)


def _load_pptx(path: Path) -> str:
    """解析 PPT：每页幻灯片的文本框按阅读顺序提取，表内表格转 Markdown。

    备注页不读：演讲备注是讲稿不是文档内容，进检索只会污染上下文。
    """
    from pptx import Presentation

    prs = Presentation(str(path))
    slides: list[str] = []
    for i, slide in enumerate(prs.slides):
        parts: list[str] = []
        for shape in slide.shapes:
            if shape.has_table:
                md = _rows_to_markdown(
                    [[cell.text for cell in row.cells] for row in shape.table.rows]
                )
                if md:
                    parts.append(md)
            elif shape.has_text_frame:
                text = shape.text.strip()
                if text:
                    parts.append(text)
        if parts:
            slides.append(f"【第 {i + 1} 页】\n" + "\n\n".join(parts))
    return "\n\n".join(slides)


def _load_xlsx(path: Path) -> str:
    """解析 Excel：每个工作表独立成节，行转 Markdown 表格。

    首行做表头（沿用 _rows_to_markdown 约定）；全空行跳过；
    空表整表丢弃，不产出残表。
    公式单元格读的是缓存值，无缓存时为空，属格式固有限制。
    """
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    sheets: list[str] = []
    for ws in wb.worksheets:
        rows = [[c.value for c in row] for row in ws.iter_rows()]
        md = _rows_to_markdown(rows)
        if md:
            sheets.append(f"## {ws.title}\n\n{md}")
    wb.close()
    return "\n\n".join(sheets)


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
        # 扫描型 PDF 正文极少时自动尝试 OCR（需 rapidocr_onnxruntime）
        if len(text.strip()) < 20:
            try:
                from core.ocr import ocr_pdf_scanned

                ocr_text = ocr_pdf_scanned(path)
                if ocr_text.strip():
                    text = ocr_text
            except Exception as exc:
                print(f"[loader] PDF OCR 回退失败，沿用原文提取：{exc}", file=sys.stderr)
    elif suffix in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"):
        from core.ocr import ocr_image

        text = ocr_image(path)
    elif suffix == ".doc":
        from core.legacy_office import load_doc_ole

        text = load_doc_ole(path)
    elif suffix == ".xls":
        from core.legacy_office import load_xls_ole

        text = load_xls_ole(path)
    elif suffix == ".ppt":
        from core.legacy_office import load_ppt_ole

        text = load_ppt_ole(path)
    elif suffix == ".docx":
        text = _load_docx(path)
    elif suffix == ".pptx":
        text = _load_pptx(path)
    elif suffix == ".xlsx":
        text = _load_xlsx(path)
    else:
        text = _read_text_file(path)

    if not text.strip():
        raise ValueError(
            f"未能从 {path.name} 中提取到文字。"
            "若为扫描件或图片型 PDF，需要先做 OCR 处理。"
        )
    return text


# ====================== URL 抓取 ======================
# 只用标准库：urllib 抓 + HTMLParser 提正文。刻意不用 trafilatura/bs4——
# 重型提取器要么新增依赖（进离线包增体积），要么对中文站点水土不服；
# 简单启发式（去噪标签 + article/main 优先 + 块级换行）覆盖文档/博客/wiki 类页面；
# JS 渲染站首屏 HTML 里本来就没有正文，抓不到由报错提示用户换文件导入。

# 正文无关标签：内容直接丢弃
_DROP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "form", "button"}
# 块级标签：前后换行，避免段落粘成一行
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "article", "main", "section", "blockquote", "pre", "table",
}
# 正文容器：命中则只取其内部，导航/侧栏/评论区一天然排除
_CONTENT_TAGS = {"article", "main"}


class _ArticleParser(HTMLParser):
    """极简正文提取：标题 + 去噪后的块级文本"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.chunks: list[str] = []
        self._in_title = False
        self._drop_depth = 0
        self._content_depth = 0   # >0 表示正文容器内部
        self._seen_content = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        if tag in _DROP_TAGS:
            self._drop_depth += 1
        if tag in _CONTENT_TAGS:
            self._content_depth += 1
            self._seen_content = True
        if tag in _BLOCK_TAGS and not self._drop_depth:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in _DROP_TAGS and self._drop_depth:
            self._drop_depth -= 1
        if tag in _CONTENT_TAGS and self._content_depth:
            self._content_depth -= 1
        if tag in _BLOCK_TAGS and not self._drop_depth:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif not self._drop_depth:
            # 有正文容器时只收容器内文本（导航/评论天然排除）；
            # 无容器（简陋页面）则全收，由空行归一兜底
            if not self._seen_content or self._content_depth:
                self.chunks.append(data)


def extract_article(html: str) -> tuple[str, str]:
    """从 HTML 提取（标题，正文纯文本）。纯函数，不碰网络，便于单测"""
    parser = _ArticleParser()
    parser.feed(html)
    title = re.sub(r"\s+", " ", "".join(parser.title_parts)).strip()
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in "".join(parser.chunks).split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    return title, text


def _decode_body(data: bytes, content_type: str) -> str:
    """按 header charset → meta charset → utf-8 → gbk 依次解码"""
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    charsets = [m.group(1)] if m else []
    if not charsets:
        m = re.search(
            rb'<meta[^>]+charset=["\']?([\w-]+)', data[:4096], re.I
        )
        if m:
            try:
                charsets.append(m.group(1).decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                pass
    for enc in charsets + ["utf-8", "gbk"]:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="ignore")


def fetch_url(url: str, timeout: int = FETCH_TIMEOUT, max_bytes: int = FETCH_MAX_BYTES) -> tuple[str, str]:
    """抓取网页并提取（标题，正文）。

    Raises:
        ValueError: 链接非法（非 http/https）、非 HTML、解码失败或正文为空
        URLError / TimeoutError 等：网络问题由调用方转成用户提示
    """
    url = (url or "").strip()
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"只支持 http/https 链接：{url[:80]}")

    req = urllib.request.Request(url, headers={"User-Agent": FETCH_UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get_content_type()
        # Content-Length 预检：超大文件直接拒绝，不读 body
        try:
            declared = int(resp.headers.get("Content-Length") or 0)
        except ValueError:
            declared = 0
        if declared > max_bytes:
            raise ValueError(f"页面超过 {max_bytes // 1024 // 1024}MB 上限，请用文件导入")
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"页面超过 {max_bytes // 1024 // 1024}MB 上限，请用文件导入")
    if content_type not in ("text/html", "application/xhtml+xml") and not content_type.startswith("text/"):
        raise ValueError(f"该链接不是网页文本（{content_type}），暂不支持 PDF/图片直链")

    title, text = extract_article(_decode_body(data, resp.headers.get("Content-Type", "")))
    if not text.strip():
        # 疑似 JS 渲染站/登录墙：首屏 HTML 无正文时，尝试渲染后重提
        try:
            from core.fetch_js import available, fetch_rendered_html

            if available():
                html = fetch_rendered_html(url)
                title2, text2 = extract_article(html)
                if text2.strip():
                    return title2 or title, text2
        except Exception as exc:
            print(f"[loader] JS 渲染回退失败：{exc}", file=sys.stderr)
        raise ValueError("页面正文为空（可能是 JS 渲染站或需要登录），请换文件导入")
    return title, text


def recursive_fetch(
    url: str,
    max_depth: int = 2,
    max_pages: int = 50,
    timeout: int = FETCH_TIMEOUT,
) -> list[tuple[str, str, str]]:
    """递归爬取网页及其链接

    Args:
        url: 起始 URL
        max_depth: 最大爬取深度
        max_pages: 最大爬取页面数
        timeout: 单次抓取超时

    Returns:
        [(url, title, text), ...] 抓取结果列表
    """
    from html.parser import HTMLParser
    from urllib.parse import urljoin

    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links: list[str] = []

        def handle_starttag(self, tag: str, attrs) -> None:
            if tag.lower() == "a":
                for attr, value in attrs:
                    if attr.lower() == "href" and value:
                        self.links.append(value)

    results: list[tuple[str, str, str]] = []
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(url, 0)]  # (url, depth)

    while queue and len(results) < max_pages:
        current_url, depth = queue.pop(0)

        # 跳过已访问的 URL
        if current_url in visited:
            continue
        visited.add(current_url)

        # 跳过超出深度的 URL
        if depth > max_depth:
            continue

        try:
            title, text = fetch_url(current_url, timeout=timeout)
            results.append((current_url, title, text))

            # 提取页面内链接
            if depth < max_depth:
                try:
                    req = urllib.request.Request(
                        current_url,
                        headers={"User-Agent": FETCH_UA},
                    )
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        html = resp.read().decode("utf-8", errors="ignore")

                    parser = LinkParser()
                    parser.feed(html)

                    # 添加新链接到队列
                    for link in parser.links:
                        absolute_url = urljoin(current_url, link)
                        # 只爬取 http/https 链接
                        if absolute_url.startswith(("http://", "https://")):
                            if absolute_url not in visited:
                                queue.append((absolute_url, depth + 1))
                except Exception:
                    pass  # 链接提取失败不影响已抓取的内容
        except Exception:
            continue  # 抓取失败跳过该 URL

    return results
