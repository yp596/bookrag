# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir）

产物路径固定为 `backend/dist/rag-backend/rag-backend.exe`，
因为 electron/main.js 的 resolveBackendCommand() 只认这个位置，
落错地方会静默回退去找 .venv 解释器，目标机上直接启动失败。

选 onedir 而非 onefile：onefile 每次启动都要把整个包解压到临时目录，
冷启动慢且数据目录容易误落到 _MEIPASS。onedir 启动快、目录结构可预期。
"""

from PyInstaller.utils.hooks import collect_data_files

# jieba 的 dict.txt（5MB）与 finalseg 下的 HMM 概率表不会被打包器自动收集，
# 缺了会在首次 jieba.cut 时抛 FileNotFoundError。
datas = collect_data_files("jieba")

# core/embedder.py 里的 fastembed 是函数内延迟导入，静态分析看不到，
# 依赖链上的包必须显式声明，否则打包后 import 失败、向量检索静默失效。
hiddenimports = [
    "fastembed",
    "onnxruntime",
    "huggingface_hub",
    "hf_xet",
    "tokenizers",
    "loguru",
    "mmh3",
    "PIL",
]

# 以下模块在应用代码中零 import，静态分析本就不会收集。
# 这里再显式排除一次，防止某些第三方 hook 顺着依赖链把上百 MB 的东西带进来。
#
# 注意：不能排除 numpy —— rank_bm25 内部依赖它，排除后 BM25 检索直接崩溃。
# 同理不能排除 lxml（python-docx 需要）与 openai（core/llm.py 顶层依赖）。
#
# 注意：向量检索（core/embedder.py）接入了 fastembed 之后，
# fastembed / onnxruntime / huggingface_hub / hf_xet / tokenizers / loguru / mmh3
# 全部变成必需依赖，不可再排除，否则打包版会静默退化成 BM25 单路。
#
# 注意：不能排除 PIL —— fastembed 虽然在文本场景用不到图像能力，
# 但 fastembed/__init__.py 会经 fastembed.image 顶层导入 PIL，
# 排除后 import fastembed 直接抛 ModuleNotFoundError，向量一路全废。
EXCLUDES = [
    # LangChain 全家桶（未使用，切片与 LLM 调用均为手写）
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_chroma",
    "langchain_text_splitters",
    "langgraph",
    "langsmith",
    # 模型训练链路（未使用，只需要推理）
    "torch",
    "transformers",
    # onnxruntime 的 GPU 与训练相关可选依赖
    "onnxruntime.tools",
    "onnxruntime.transformers",
    # 其它体积大且无关的
    "matplotlib",
    "pandas",
    "scipy",
    "IPython",
    "tkinter",
    "pytest",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="rag-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX 压缩会触发杀软误报，且拖慢启动
    console=True,       # 保留 stdout/stderr，主进程要捕获日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="rag-backend",
)
