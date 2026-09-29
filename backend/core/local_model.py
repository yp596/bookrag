# -*- coding: utf-8 -*-
"""本地模型一键拉起（llama-server 纳入 resources，Electron 主进程调用）

之前安装包只带后端 + 向量模型，用户需手动起 llama-server。
本模块提供：模型与二进制位置解析、健康检查、缺失时的友好提示。
二进制获取：复用本机 D:\\llmma\\llama-server.exe 或随包 resources/llama/llama-server.exe，
二者皆无时提示用户放置路径，不静默失败。
"""

import os
import sys
import urllib.request
from pathlib import Path


def llama_dir() -> Path:
    override = os.environ.get("RAG_LLAMA_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        return base / "llama"
    return Path(__file__).resolve().parent.parent / "llama"


def llama_server_path() -> Path:
    return llama_dir() / ("llama-server.exe" if os.name == "nt" else "llama-server")


def default_model_path() -> Path:
    override = os.environ.get("RAG_LOCAL_MODEL")
    if override:
        return Path(override)
    return llama_dir() / "models" / "MiniCPM5-1B-F16.gguf"


def status() -> dict:
    exe = llama_server_path()
    model = default_model_path()
    return {
        "exe_exists": exe.exists(),
        "exe": str(exe),
        "model_exists": model.exists(),
        "model": str(model),
        "ready": exe.exists() and model.exists(),
    }


def check_health(base_url: str = "http://127.0.0.1:8080", timeout: int = 3) -> bool:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/health", timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False
