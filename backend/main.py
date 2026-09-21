# -*- coding: utf-8 -*-
"""FastAPI 应用入口

启动方式：
    .venv/Scripts/python.exe main.py                 # 默认 127.0.0.1:8756
    .venv/Scripts/python.exe main.py --port 9000     # 指定端口

Electron 集成：主进程启动时传入动态端口，并将本进程作为子进程管理，
窗口关闭时一并终止。
"""

import argparse
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 支持从任意工作目录启动
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI                                    # noqa: E402
from fastapi.middleware.cors import CORSMiddleware             # noqa: E402

from api import chat as chat_api                               # noqa: E402
from api import kb as kb_api                                   # noqa: E402
from api import settings as settings_api                       # noqa: E402
from api.deps import kb_manager, settings_store, storage       # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时预热：加载各知识库索引，避免首次提问卡顿"""
    for kb in storage.list_kbs():
        if kb.get("chunk_count"):
            kb_manager.get_retriever(kb["id"])
    yield


app = FastAPI(title="本地 RAG 知识库", version="0.2.0", lifespan=lifespan)

# 前端开发服务器（Vite）与 Electron 渲染进程需要跨域访问；
# 服务仅监听本机回环地址，因此放开来源限制。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(kb_api.router)
app.include_router(chat_api.router)
app.include_router(settings_api.router)


@app.get("/api/health")
def health() -> dict:
    """健康检查与运行时概览"""
    profile = settings_store.get_llm_profile()
    return {
        "status": "ok",
        "knowledge_bases": len(storage.list_kbs()),
        "llm_mode": profile["mode"],
        "model": profile["model"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 RAG 知识库后端服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8756, help="监听端口")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
