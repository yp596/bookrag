# -*- coding: utf-8 -*-
"""JS 渲染页抓取（可选，需 playwright，失败回退标准库）

标准库 fetch_url 只能拿到首屏 HTML；SPA/JS 渲染站正文在 JS 执行后才出现。
本模块在 playwright 已安装时用无头 Chromium 等待网络空闲后取渲染后 HTML，
复用 loader.extract_article 做正文提取。未安装时抛错由调用方转友好提示。
"""

import sys


def available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        return True
    except Exception:
        return False


def fetch_rendered_html(url: str, timeout_ms: int = 20000) -> str:
    """返回 JS 执行后的完整 HTML"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(f"JS 渲染抓取需 pip install playwright 且执行 playwright install chromium：{exc}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) bookrag/1.0")
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                page.wait_for_timeout(1500)
                return page.content()
            finally:
                browser.close()
    except Exception as exc:
        print(f"[fetch_js] 渲染抓取失败：{exc}", file=sys.stderr)
        raise
