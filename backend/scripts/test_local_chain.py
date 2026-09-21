# -*- coding: utf-8 -*-
"""端到端链路测试（使用 core 正式模块）

验证：文档切片 -> BM25 检索（含停用词与覆盖率过滤）-> LLM 生成 -> 引用来源

前置：本地 llama-server 已启动
    llama-server.exe -m models/MiniCPM5-1B-F16.gguf -c 4096 -ngl 99 --port 8080

运行：
    .venv/Scripts/python.exe scripts/test_local_chain.py
"""

import sys
from pathlib import Path

# 让脚本能直接 import core 包
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core import RAGPipeline        # noqa: E402
from core.pipeline import Answer    # noqa: E402

SAMPLE_DOCUMENT = """
本公司产品售后服务政策说明

一、保修条款
本产品保修期为三年，自购买之日起计算。在保修期内，因产品自身质量问题导致的故障，
本公司提供免费维修服务。人为损坏、进水、私自拆机等情况不在保修范围内。

二、退货政策
签收后七天内可申请无理由退货，商品需保持完好且包装完整。超过七天但不足三十天的，
可申请换货。定制类商品一经售出不予退换。

三、配送说明
全国范围内包邮，新疆、西藏等偏远地区需额外收取运费。正常情况下三到五个工作日送达，
节假日可能顺延。

四、发票问题
下单时可申请开具电子发票，发货后不支持补开纸质发票。如需增值税专用发票，
请在下单时联系客服单独申请。

五、会员权益
年费会员享受全场九折优惠，并且不限次数免运费。会员权益自开通之日起一年内有效，
到期后需续费方可继续享受。
"""

QUESTIONS = [
    "产品保修几年？",         # 应命中「保修条款」
    "怎么退货？",             # 应命中「退货政策」
    "会员有什么优惠？",        # 应命中「会员权益」
    "支持货到付款吗？",        # 资料中不存在，应无命中且不编造
]


def print_answer(question: str, ans: Answer) -> None:
    print("\n" + "=" * 64)
    print(f"【提问】{question}")
    if ans.sources:
        print(f"【检索】命中 {ans.retrieved} 条：")
        for i, hit in enumerate(ans.sources, 1):
            print(f"      {i}. {hit.chunk.title[:24]} | 得分 {hit.score:.3f} | 覆盖率 {hit.coverage:.2f}")
    else:
        print("【检索】无命中（已被相关度过滤拦下）")
    print("【回答】")
    print(ans.text.strip())


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    pipeline = RAGPipeline(llm_mode="local")

    # ---- 1. 导入文档 ----
    n = pipeline.add_text(SAMPLE_DOCUMENT, source="售后服务政策.txt")
    print(f"【1】文档导入完成：{n} 个切片，共 {pipeline.chunk_count} 片")

    # ---- 2. 问答 ----
    for q in QUESTIONS:
        ans = pipeline.ask(q)
        print_answer(q, ans)

    # ---- 3. 流式输出验证 ----
    print("\n" + "=" * 64)
    print("【流式输出验证】提问：发票怎么开？")
    stream, hits = pipeline.ask_stream("发票怎么开？")
    print(f"【检索】命中 {len(hits)} 条（引用来源可在流开始前确定）")
    print("【回答】", end="", flush=True)
    for piece in stream:
        print(piece, end="", flush=True)
    print()


if __name__ == "__main__":
    main()
