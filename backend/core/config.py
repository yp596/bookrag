# -*- coding: utf-8 -*-
"""全局配置

集中管理路径、切片参数、检索参数与 LLM 配置，避免散落在各模块中硬编码。
"""

import os
import sys
from pathlib import Path


def _resolve_base_dir() -> Path:
    """确定数据根目录。

    打包后不能再用 __file__ 定位：PyInstaller 冻结时它指向 _MEIPASS 临时目录，
    进程退出即被清理，用户导入的知识库会静默消失且不抛任何异常。
    三种运行形态分别处理：

    1. Electron 拉起 —— 主进程经 RAG_DATA_DIR 指定可写目录（优先）
    2. 独立运行 exe —— 落到 %APPDATA%，安装目录只读且升级会被覆盖
    3. 源码运行 —— 沿用 backend/，开发习惯不变
    """
    override = os.environ.get("RAG_DATA_DIR")
    if override:
        return Path(override)

    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "rag-desktop"

    return Path(__file__).resolve().parent.parent


# ====================== 路径 ======================
BASE_DIR = _resolve_base_dir()
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
DB_PATH = DATA_DIR / "rag.db"                          # 知识库元数据与切片
SETTINGS_PATH = DATA_DIR / "settings.json"             # 模型配置
CHROMA_DIR = DATA_DIR / "chroma_db"                    # 向量库（待接入）
BM25_DIR = DATA_DIR / "bm25_index"

# ====================== 文档切片 ======================
MAX_CHUNK_SIZE = 800          # 单个切片字符上限，超出则按窗口二次切分
CHUNK_OVERLAP = 100           # 二次切分时的重叠长度，保障上下文连贯

# ====================== 检索 ======================
TOP_K = 3                     # 最终送入 LLM 的片段数
CANDIDATE_K = 20              # 粗排候选数（为融合与重排预留）

# 相关度过滤：三道防线，解决"低分噪音片段污染上下文"的问题
SCORE_THRESHOLD_ABS = 0.05    # 绝对下限，过滤近乎无关的结果
SCORE_THRESHOLD_REL = 0.25    # 相对阈值，低于最高分该比例的结果丢弃
MIN_TERM_COVERAGE = 0.5       # 查询词覆盖率下限，解决"只命中一个词就入选"的误召回

# ====================== 文本向量化 ======================
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"    # 中文 ONNX 嵌入模型（需预下载）
EMBEDDING_CACHE_DIR = str(MODELS_DIR)

# ====================== LLM ======================
# 本地与云端均使用 OpenAI 兼容协议，切换时只需改这三项
DEFAULT_LLM_MODE = "local"

LLM_PROFILES = {
    "local": {
        "base_url": "http://127.0.0.1:8080/v1",     # llama-server 默认地址
        "api_key": "sk-no-key-required",            # 本地服务不校验 Key
        "model": "MiniCPM5-1B",
    },
    "cloud": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",                              # 由界面填写
        "model": "deepseek-v4.1-flash",
    },
}

# RAG 生成使用的系统提示词
# 1B 小模型的指令遵循能力有限，此处用显式禁令收紧约束，抑制编造
RAG_SYSTEM_PROMPT = (
    "你是知识库助手，任务是依据给定参考资料回答问题。\n"
    "必须遵守以下规则：\n"
    "1. 只使用参考资料中明确写出的信息作答；\n"
    "2. 严禁补充资料中没有的细节，包括但不限于：具体流程、所需凭证、操作步骤、"
    "联系方式、会员等级、积分规则、名词术语；\n"
    "3. 严禁编造资料编号、引用格式或资料数量，资料只有开头声明的那些；\n"
    "4. 若参考资料不足以回答问题，直接回复「资料中未提及」，不要推测；\n"
    "5. 回答简洁，不需要复述全部资料内容，也不需要罗列无关条款。"
)

# 检索无命中时的固定答复。
# 这种情况不交给模型判断：小模型即使认出「没有资料」，也倾向于补一句
# 「建议咨询客服」之类的推测性内容，实测无法靠提示词稳定约束。
# 由代码直接短路，既保证答复确定，也省掉一次无意义的推理。
NO_CONTEXT_REPLY = "资料中未提及。"
