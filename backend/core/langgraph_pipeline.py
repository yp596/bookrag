# -*- coding: utf-8 -*-
"""LangGraph 多轮检索图

实现：
1. 多轮检索-判断-再检索循环
2. 多 Agent 分工协作（检索 Agent + 生成 Agent）
3. 人工审批节点（在生成前暂停）
4. 断点续传（通过 checkpointer 持久化）
"""

from typing import TypedDict, Annotated, Sequence
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage
import operator


# ---------- 状态定义 ----------
class RetrievalState(TypedDict):
    """检索状态"""
    question: str                    # 当前问题（可能被改写）
    original_question: str           # 原始问题
    round_idx: int                   # 当前轮次
    max_rounds: int                  # 最大轮次
    hits: Annotated[Sequence, operator.add]  # 累积的检索结果
    rewritten: bool                  # 是否已改写问题
    approved: bool                   # 人工审批结果


# ---------- 节点定义 ----------
def retrieve_node(state: RetrievalState) -> dict:
    """检索 Agent：执行检索"""
    # 实际实现中调用 retriever
    # 这里返回模拟结果
    return {"round_idx": state["round_idx"] + 1}


def judge_node(state: RetrievalState) -> dict:
    """判断 Agent：判断是否充分"""
    # 实际实现中调用 LLM 判断
    return {"rewritten": True}


def rewrite_node(state: RetrievalState) -> dict:
    """改写 Agent：改写问题"""
    return {"question": f"{state['question']}（改写）"}


def approval_node(state: RetrievalState) -> dict:
    """人工审批节点：暂停等待用户确认"""
    # LangGraph 的 interrupt 机制会在这里暂停
    return {"approved": True}


def generate_node(state: RetrievalState) -> dict:
    """生成 Agent：生成最终答案"""
    return {}


# ---------- 条件路由 ----------
def should_continue(state: RetrievalState) -> str:
    """判断是否继续检索"""
    if state["round_idx"] >= state["max_rounds"]:
        return "generate"
    if len(state.get("hits", [])) >= 3:
        return "generate"
    return "rewrite"


def check_approval(state: RetrievalState) -> str:
    """检查审批结果"""
    if state.get("approved", False):
        return "generate"
    return "retrieve"


# ---------- 图构建 ----------
def build_graph():
    """构建多轮检索图"""
    graph = StateGraph(RetrievalState)

    # 添加节点
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("judge", judge_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("approval", approval_node)
    graph.add_node("generate", generate_node)

    # 添加边
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "judge")
    graph.add_conditional_edges("judge", should_continue, {
        "rewrite": "rewrite",
        "generate": "approval",
    })
    graph.add_edge("rewrite", "retrieve")
    graph.add_conditional_edges("approval", check_approval, {
        "generate": "generate",
        "retrieve": "retrieve",
    })
    graph.add_edge("generate", END)

    # 编译图（带 checkpointer 支持断点续传）
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


# ---------- 使用示例 ----------
async def run_multi_turn_retrieval(question: str, max_rounds: int = 3):
    """运行多轮检索"""
    graph = build_graph()

    initial_state = {
        "question": question,
        "original_question": question,
        "round_idx": 0,
        "max_rounds": max_rounds,
        "hits": [],
        "rewritten": False,
        "approved": False,
    }

    # 运行图
    result = await graph.ainvoke(initial_state)
    return result
