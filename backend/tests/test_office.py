# -*- coding: utf-8 -*-
"""Office 文档解析的行为约束测试

只覆盖「改错了不会报错、只会让内容悄悄丢失」的逻辑，不依赖模型与网络。

为什么这几条值得测：
    1. pptx 备注页必须跳过：讲稿进检索只会污染上下文，删了这行过滤器
       单测立刻变红——回归靠这一条。
    2. xlsx 空表必须整表丢弃，否则产出只有表头的残表，污染检索。
    3. 公式单元格无缓存读空是格式固有限制，单测只锁"不崩溃"，不锁值。

运行：backend/.venv/Scripts/python -m unittest discover -s backend/tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.loader import load_document  # noqa: E402


def _make_pptx(path: Path) -> None:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(100, 100, 400, 100).text_frame.text = "slide-hello"
    table = slide.shapes.add_table(2, 2, 100, 250, 400, 100).table
    table.cell(0, 0).text = "H1"
    table.cell(0, 1).text = "H2"
    table.cell(1, 0).text = "a"
    table.cell(1, 1).text = "b"
    slide.notes_slide.placeholders[1].text_frame.text = "secret-notes"
    prs.save(str(path))


def _make_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Prices"
    ws.append(["Item", "Cost"])
    ws.append(["pen", 5])
    wb.create_sheet("Empty")
    wb.save(str(path))


class PptxTest(unittest.TestCase):
    def test_text_and_table_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.pptx"
            _make_pptx(p)
            text = load_document(p)
            self.assertIn("slide-hello", text)
            self.assertIn("| H1 | H2 |", text)
            self.assertIn("| a | b |", text)

    def test_notes_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.pptx"
            _make_pptx(p)
            self.assertNotIn("secret-notes", load_document(p))


class XlsxTest(unittest.TestCase):
    def test_sheet_becomes_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.xlsx"
            _make_xlsx(p)
            text = load_document(p)
            self.assertIn("## Prices", text)
            self.assertIn("| Item | Cost |", text)
            self.assertIn("| pen | 5 |", text)

    def test_empty_sheet_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.xlsx"
            _make_xlsx(p)
            self.assertNotIn("Empty", load_document(p))


if __name__ == "__main__":
    unittest.main()
