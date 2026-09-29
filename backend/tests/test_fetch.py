# -*- coding: utf-8 -*-
"""URL 抓取与正文提取的行为约束测试

只覆盖「错了不报错、只会入库垃圾」的逻辑，不依赖外网：
网络相关的端到端走本地 http.server（127.0.0.1 随机端口）。

为什么这几条值得测：
    1. 噪音（导航/脚本/侧栏）若混入正文，检索上下文会被污染且难以察觉。
    2. file:// 等 scheme 若不拦，等于给后端开了个本地文件读取口。
    3. 非 HTML（PDF 直链）若不拒，会入库一堆乱码。
    4. 中文站常见的 gbk 编码若解错，整篇变问号。

运行：backend/.venv/Scripts/python -m unittest discover -s backend/tests -v
"""

import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.loader import extract_article, fetch_url  # noqa: E402


class ExtractTest(unittest.TestCase):
    def test_title_and_paragraphs(self):
        html = (
            "<html><head><title>保修政策</title></head><body>"
            "<h1>保修政策</h1><p>整机保修三年。</p><p>七天无理由退货。</p>"
            "</body></html>"
        )
        title, text = extract_article(html)
        self.assertEqual(title, "保修政策")
        self.assertIn("整机保修三年", text)
        self.assertIn("七天无理由退货", text)

    def test_noise_dropped(self):
        """导航/侧栏/脚本/样式一律丢弃；article 容器外文本不收"""
        html = (
            "<html><head><title>正文</title><style>.a{color:red}</style></head><body>"
            "<nav>首页 产品 关于</nav>"
            "<article><p>真正的条款内容</p></article>"
            "<aside>相关推荐 广告</aside>"
            "<script>alert(1)</script>"
            "</body></html>"
        )
        _, text = extract_article(html)
        self.assertIn("真正的条款内容", text)
        for noise in ("首页", "相关推荐", "alert", "color"):
            self.assertNotIn(noise, text)

    def test_no_container_falls_back_to_all(self):
        """简陋页面无 article/main 时全收，不吞正文"""
        _, text = extract_article("<html><body><div>只有一段话</div></body></html>")
        self.assertIn("只有一段话", text)

    def test_empty_page(self):
        title, text = extract_article("<html><head></head><body><br></body></html>")
        self.assertEqual(text, "")


class FetchValidationTest(unittest.TestCase):
    def test_rejects_non_http_scheme(self):
        for bad in ("file:///etc/passwd", "ftp://a/b", "javascript:alert(1)", "", "example.com"):
            with self.assertRaises(ValueError, msg=bad):
                fetch_url(bad)


PAGE_UTF8 = (
    "<html><head><meta charset='utf-8'><title>退货须知</title></head><body>"
    "<nav>导航栏</nav><article><p>七天无理由退货，运费自理。</p></article></body></html>"
).encode("utf-8")

PAGE_GBK = (
    "<html><head><meta charset='gbk'><title>保修卡</title></head><body>"
    "<article><p>整机保修三年，以发票为准。</p></article></body></html>"
).encode("gbk")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 单测输出保持干净
        pass

    def do_GET(self):
        if self.path == "/utf8":
            body, ctype = PAGE_UTF8, "text/html; charset=utf-8"
        elif self.path == "/gbk":
            body, ctype = PAGE_GBK, "text/html"  # 无 header charset，走 meta
        elif self.path == "/pdf":
            body, ctype = b"%PDF-1.4 fake", "application/pdf"
        elif self.path == "/empty":
            body, ctype = b"<html><body></body></html>", "text/html"
        elif self.path == "/big":
            body, ctype = b"x" * 200, "text/html"
        else:
            self.send_response(404)
            self.end_headers()
            return
        if self.path == "/big":
            # 谎报超大 Content-Length，触发预检拒绝（不真传大 body）
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(10 * 1024 * 1024))
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FetchServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def test_end_to_end_utf8(self):
        title, text = fetch_url(self._url("/utf8"))
        self.assertEqual(title, "退货须知")
        self.assertIn("七天无理由退货", text)
        self.assertNotIn("导航栏", text)

    def test_gbk_via_meta(self):
        title, text = fetch_url(self._url("/gbk"))
        self.assertEqual(title, "保修卡")
        self.assertIn("整机保修三年", text)

    def test_rejects_non_html(self):
        with self.assertRaises(ValueError):
            fetch_url(self._url("/pdf"))

    def test_rejects_empty_article(self):
        with self.assertRaises(ValueError):
            fetch_url(self._url("/empty"))

    def test_rejects_declared_oversize(self):
        with self.assertRaises(ValueError):
            fetch_url(self._url("/big"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
