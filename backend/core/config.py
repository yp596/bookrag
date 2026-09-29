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

# 模型目录（只读资源）与数据目录分开：数据要可写、随用户走，
# 模型是随包分发的只读文件，打包后位于 resources/backend/models。
# 经 RAG_MODELS_DIR 由主进程指定，独立运行时回落到 exe 同级的 models/。
_models_override = os.environ.get("RAG_MODELS_DIR")
if _models_override:
    MODELS_DIR = Path(_models_override)
elif getattr(sys, "frozen", False):
    # 冻结态：PyInstaller onedir 的 exe 在 <pkg>/rag-backend.exe，
    # 资源在同级 _internal/ 或 exe 同级目录，这里按后者放置模型
    MODELS_DIR = Path(sys.executable).resolve().parent / "models"
else:
    MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
DB_PATH = DATA_DIR / "rag.db"                          # 知识库元数据与切片
SETTINGS_PATH = DATA_DIR / "settings.json"             # 模型配置
CHROMA_DIR = DATA_DIR / "chroma_db"                    # 向量库（待接入）
BM25_DIR = DATA_DIR / "bm25_index"
VECTOR_DIR = DATA_DIR / "vector_cache"                 # 各库向量矩阵（kb_id.npz）

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

# ====================== 向量检索 ======================
# 余弦相似度不能用绝对阈值苛求——同领域中文句子对普遍有 0.3+ 的基础相似度。
# 但仍需要一道「明显跑题」的下限：否则任何查询都能找到"相对最像"的片段，
# 无关问题也会污染上下文。
VECTOR_MIN_SIMILARITY = 0.45  # 相对阈值：低于最高分该比例的向量结果丢弃
VECTOR_MIN_SCORE = 0.55       # 绝对下限：低于此相似度视为无关，直接丢弃

# 向量量化：float32 → int8，内存降 75%。
# 归一化后各维度值域 [-1, 1]，int8 量化精度足够（误差 < 0.4%）。
VECTOR_QUANTIZE = True

# Qdrant 向量库配置
USE_QDRANT = False              # 是否使用 Qdrant 替代 Chroma
QDRANT_DIR = DATA_DIR / "qdrant"  # Qdrant 本地存储路径

# RRF（倒数排序融合）常数。值越大，靠前名次的优势越平缓。
# 60 是原论文与工业界常用取值，对名次差异不敏感、抗单路噪声。
RRF_K = 60

# ====================== 精排 Rerank ======================
# RRF 只看名次不看分数：BM25 第一名 10 分、第二名 2 分（5 倍差距），
# 与向量第一 0.75、第二 0.70（几乎打平），在 RRF 里被抹成同样的名次差。
# 长文档下同词复现多、各路分差悬殊时排序不稳，因此粗排（RRF 取候选）
# 之后再用三路原始信号的加权做一次精排，取回分数强弱的信息。
# 零新依赖、零模型下载：权重是经验值，类型一变可能要调，故做成配置项。
RERANK_ENABLED = True        # 精排总开关，关闭则回退到纯 RRF 截断
RERANK_W_BM25 = 0.4          # BM25 归一化分权重（词面精确性）
RERANK_W_VECTOR = 0.4        # 向量相似度权重（语义接近性）
RERANK_W_COVERAGE = 0.2      # 查询词覆盖率权重（三者之和为 1）
RERANK_PHRASE_BONUS = 0.15   # 查询原短语在片段中逐字出现时的额外加分

# CrossEncoder 真重排（可选第二阶段，默认关闭保轻量）：
# 加权精排之后再用【问题+片段】成对模型打分，对反义/长难句更准。
# 失败一律回退加权精排，绝不影响主链路。
CROSS_RERANK_ENABLED = False  # 总开关，开启后才尝试加载模型
CROSS_RERANK_MODEL = "ms-marco-TinyBERT-L-2-v2"  # 约 40MB ONNX，存 MODELS_DIR/rerank

# ====================== 文本向量化 ======================
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"    # 中文 ONNX 嵌入模型（需预下载）
EMBEDDING_CACHE_DIR = str(MODELS_DIR)

# ====================== 对话历史 ======================
# 历史只做展示层持久化（重启后记录还在），不送回模型做多轮：
# 本地 1B 小模型的指令遵循本就吃紧，多轮上下文只会放大编造 drift。
HISTORY_MAX_PER_KB = 200    # 单会话最多保留的消息条数，超限按时间裁掉最旧的
HISTORY_FETCH_DEFAULT = 100  # 前端拉取的默认轮次

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
