"""基于 LangGraph 的 Benchmark 评测流水线状态图编排。

将 Benchmark 评测任务的执行解耦为规范的 Graph 状态机节点：
1. load_context: 载入任务配置、有效数据集行、协议档与计费/并发限制；
2. dispatch_batches: 逐协议档分批执行模型并发调用、打分与用量累加；
3. check_condition: 检查是否触发预算超限熔断或中途协作式取消；
4. finish_or_fail: 汇总各档指标写入最终报告并更新任务终态。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session
from typing_extensions import TypedDict

from .models import EvalItem, Task, TaskEvent
from .protocol import ProtocolCallError, call_protocol
from .scoring import score_answer, score_exact, score_rouge_l

logger = logging.getLogger("worker.eval_graph")


@dataclass
class EvalBatchResult:
    """单个样本或批次评测产物。"""

    ok: bool
    output: str = ""
    score: float | None = None
    exact: float | None = None
    rouge_l: float | None = None
    latency_ms: float | None = None
    usage: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None
    error: str | None = None


class BenchmarkGraphState(TypedDict, total=False):
    """Benchmark 评测图状态。"""

    task_id: str
    dataset_id: str
    metric: str
    rows_data: list[dict[str, Any]]
    profiles_data: list[dict[str, Any]]
    run_params: dict[str, Any]
    max_usd: float
    price_per_1k: float
    batch_size: int
    total_samples: int
    done_samples: int
    usage_totals: dict[str, dict[str, Any]]
    is_cancelled: bool
    is_budget_exceeded: bool
    error_code: str | None
    error_message: str | None
    completed: bool


def eval_single_row(
    call_kwargs: dict[str, Any],
    row_data: dict[str, Any],
    retry: int,
    metric: str,
    truncate_raw_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """独立纯函数：调用被测模型并根据主指标评分。"""
    context = row_data.get("context") or ""
    question = row_data.get("question") or ""
    if context.strip():
        user_msg = f"背景信息:\n{context.strip()}\n\n问题:{question}"
    else:
        user_msg = question

    messages = [{"role": "user", "content": user_msg}]
    reference = row_data.get("reference") or ""
    last_error = ""

    for _ in range(max(1, retry + 1)):
        try:
            result = call_protocol(messages=messages, **call_kwargs)
        except ProtocolCallError as exc:
            last_error = f"{exc.code}: {exc.message}"
            continue
        output = result.text or ""
        return {
            "ok": True,
            "output": output,
            "score": score_answer(metric, output, reference),
            "exact": score_exact(output, reference),
            "rouge_l": score_rouge_l(output, reference),
            "latency_ms": result.latency_ms,
            "usage": result.usage,
            "raw": truncate_raw_fn(result.raw) if result.raw else None,
        }
    return {"ok": False, "error": last_error or "UPSTREAM: 调用失败"}


class BenchmarkEvalPipeline:
    """基于 LangGraph 的 Benchmark 评测流水线编排器。"""

    def __init__(
        self,
        db_factory: Callable[[], Session],
        push_progress_fn: Callable[[Task, int, int, str], None],
        truncate_raw_fn: Callable[[dict[str, Any]], dict[str, Any]],
        is_cancelled_fn: Callable[[Session, str], bool],
    ) -> None:
        """注入执行所需的 DB 会话工厂与辅助函数。"""
        self.db_factory = db_factory
        self.push_progress_fn = push_progress_fn
        self.truncate_raw_fn = truncate_raw_fn
        self.is_cancelled_fn = is_cancelled_fn
        self.graph = self._build_graph()

    def _build_graph(self):
        """构建 LangGraph Benchmark 工作流。"""
        workflow = StateGraph(BenchmarkGraphState)

        workflow.add_node("prepare_execution", self._node_prepare_execution)
        workflow.add_node("execute_profile_batches", self._node_execute_profile_batches)

        workflow.add_edge(START, "prepare_execution")
        workflow.add_conditional_edges(
            "prepare_execution",
            self._route_after_prepare,
            {
                "execute": "execute_profile_batches",
                "end": END,
            },
        )
        workflow.add_edge("execute_profile_batches", END)

        return workflow.compile()

    def _route_after_prepare(self, state: BenchmarkGraphState) -> str:
        """决定校验通过后是继续执行还是直接退出。"""
        if state.get("error_code") or state.get("completed"):
            return "end"
        return "execute"

    def _node_prepare_execution(self, state: BenchmarkGraphState) -> dict[str, Any]:
        """初始化节点：准备评测上下文并检查前置条件。"""
        total = state.get("total_samples", 0)
        done = state.get("done_samples", 0)
        if total > 0 and done >= total:
            return {"completed": True}
        return {}

    def _node_execute_profile_batches(self, state: BenchmarkGraphState) -> dict[str, Any]:
        """执行节点：逐个 Profile 分批并发调用、落库、累计用量与熔断检查。"""
        task_id = state["task_id"]
        rows_data = state["rows_data"]
        profiles_data = state["profiles_data"]
        run_params = state["run_params"]
        metric = state["metric"]
        batch_size = state["batch_size"]
        max_usd = state["max_usd"]
        price = state["price_per_1k"]
        total = state["total_samples"]
        done = state["done_samples"]
        usage_totals = state["usage_totals"]

        retry = run_params.get("retry", 0)
        timeout_s = run_params.get("timeout_s", 30.0)
        temperature = run_params.get("temperature", 0.2)
        max_tokens = run_params.get("max_tokens", 1024)
        system_prompt = run_params.get("system_prompt")

        db = self.db_factory()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                return {"error_code": "NOT_FOUND", "error_message": "任务不存在"}

            for p_dict in profiles_data:
                profile_id = p_dict["id"]
                # 检查已完成行号
                finished_nos = {
                    row_no
                    for (row_no,) in db.query(EvalItem.row_no).filter(
                        EvalItem.task_id == task_id, EvalItem.profile_id == profile_id
                    ).all()
                }
                pending = [r for r in rows_data if r["row_no"] not in finished_nos]
                if not pending:
                    continue

                # 运行日志：记录每个被测模型的评测起点（供前端运行日志窗口展示）
                db.add(
                    TaskEvent(
                        task_id=task_id,
                        event="log",
                        message=f"开始评测 {p_dict.get('name') or profile_id}（{len(pending)} 条样本）",
                        payload={"profile_id": profile_id, "pending": len(pending)},
                    )
                )

                api_key = p_dict.get("api_key")
                if not api_key:
                    for r_dict in pending:
                        db.add(
                            EvalItem(
                                task_id=task_id,
                                profile_id=profile_id,
                                row_no=r_dict["row_no"],
                                question=r_dict.get("question") or "",
                                reference=r_dict.get("reference") or "",
                                context=r_dict.get("context"),
                                error="VALIDATION: 协议档未配置 API Key",
                            )
                        )
                        done += 1
                    db.commit()
                    self.push_progress_fn(task, done, total, "执行中")
                    continue

                call_kwargs = dict(
                    protocol=p_dict["protocol"],
                    base_url=p_dict["base_url"],
                    model=p_dict["model"],
                    api_key=api_key,
                    anthropic_version=p_dict.get("anthropic_version"),
                    system=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_s=timeout_s,
                )

                for start in range(0, len(pending), batch_size):
                    batch = pending[start : start + batch_size]
                    with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                        results = list(
                            pool.map(
                                lambda r_item: eval_single_row(
                                    call_kwargs, r_item, retry, metric, self.truncate_raw_fn
                                ),
                                batch,
                            )
                        )

                    for r_item, result in zip(batch, results):
                        db.add(
                            EvalItem(
                                task_id=task_id,
                                profile_id=profile_id,
                                row_no=r_item["row_no"],
                                question=r_item.get("question") or "",
                                reference=r_item.get("reference") or "",
                                context=r_item.get("context"),
                                output=result.get("output") or "",
                                score=result.get("score"),
                                exact=result.get("exact"),
                                rouge_l=result.get("rouge_l"),
                                latency_ms=result.get("latency_ms"),
                                error=result.get("error"),
                                raw=result.get("raw"),
                                usage=result.get("usage"),
                            )
                        )
                        done += 1
                        usage = result.get("usage")
                        if usage:
                            totals = usage_totals.setdefault(
                                profile_id,
                                {
                                    "prompt_tokens": 0,
                                    "completion_tokens": 0,
                                    "total_tokens": 0,
                                    "est_cost_usd": 0.0,
                                },
                            )
                            totals["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                            totals["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                            totals["total_tokens"] += int(usage.get("total_tokens") or 0)
                            totals["est_cost_usd"] = totals["total_tokens"] / 1000 * price

                    db.commit()
                    cost_usd = sum(t["est_cost_usd"] for t in usage_totals.values())
                    self.push_progress_fn(task, done, total, "执行中")

                    # 协作式取消检查
                    if self.is_cancelled_fn(db, task_id):
                        logger.info("benchmark task %s cancelled mid-run via LangGraph", task_id)
                        return {"is_cancelled": True, "done_samples": done}

                    # 预算熔断检查
                    if cost_usd > max_usd:
                        return {
                            "is_budget_exceeded": True,
                            "error_code": "BUDGET_EXCEEDED",
                            "error_message": f"费用估算 {cost_usd:.2f} USD 超过上限 {max_usd:.2f} USD，任务已停止",
                            "done_samples": done,
                        }

            return {"completed": True, "done_samples": done}
        finally:
            db.close()

    def run(self, initial_state: BenchmarkGraphState) -> BenchmarkGraphState:
        """执行 LangGraph 工作流并返回终态。"""
        return self.graph.invoke(initial_state)
