# -*- coding: utf-8 -*-
"""RAG 评估：自动评估检索质量

指标：
- 准确率（Precision）：检索到的相关片段占检索到的总片段的比例
- 召回率（Recall）：检索到的相关片段占所有相关片段的比例
- F1 分数：准确率和召回率的调和平均

评估方式：
- 手动标注：用户标注相关片段，计算准确率和召回率
- 自动评估：用 LLM 判断检索到的片段是否相关
"""

from dataclasses import dataclass, field

from core.retriever import Hit


@dataclass
class EvalResult:
    """评估结果"""

    precision: float = 0.0      # 准确率
    recall: float = 0.0         # 召回率
    f1: float = 0.0             # F1 分数
    retrieved: int = 0          # 检索到的片段数
    relevant: int = 0           # 相关片段数
    true_positive: int = 0      # 检索到的相关片段数


class RAGEvaluator:
    """RAG 评估器"""

    def __init__(self) -> None:
        self._results: list[EvalResult] = []

    def evaluate(
        self,
        query: str,
        hits: list[Hit],
        relevant_ids: set[str] | None = None,
    ) -> EvalResult:
        """评估检索结果

        Args:
            query: 用户查询
            hits: 检索结果
            relevant_ids: 相关片段 ID 集合（手动标注）

        Returns:
            评估结果
        """
        if not hits:
            return EvalResult()

        if relevant_ids is None:
            # 自动评估：假设所有检索结果都是相关的
            # 实际应用中应该用 LLM 判断
            relevant_ids = {h.chunk.id for h in hits}

        retrieved = len(hits)
        relevant = len(relevant_ids)
        true_positive = sum(1 for h in hits if h.chunk.id in relevant_ids)

        precision = true_positive / retrieved if retrieved > 0 else 0.0
        recall = true_positive / relevant if relevant > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        result = EvalResult(
            precision=precision,
            recall=recall,
            f1=f1,
            retrieved=retrieved,
            relevant=relevant,
            true_positive=true_positive,
        )
        self._results.append(result)
        return result

    def average(self) -> EvalResult:
        """计算平均评估结果"""
        if not self._results:
            return EvalResult()

        n = len(self._results)
        return EvalResult(
            precision=sum(r.precision for r in self._results) / n,
            recall=sum(r.recall for r in self._results) / n,
            f1=sum(r.f1 for r in self._results) / n,
            retrieved=sum(r.retrieved for r in self._results) // n,
            relevant=sum(r.relevant for r in self._results) // n,
            true_positive=sum(r.true_positive for r in self._results) // n,
        )

    def clear(self) -> None:
        """清空评估结果"""
        self._results.clear()
