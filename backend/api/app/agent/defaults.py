"""确认卡 / TaskSpec 默认值单一事实源。

前后端各存一份：本模块供 ``confirm_spec.py`` 拼装确认卡；前端
``frontend/src/schemas/confirmCard.ts`` 必须与本文件字段对齐。
改默认值必须双端同步。取值对齐 PRD §5.2.2（``sample_size`` 为
min(1000, 全集) 的上限预填）与 API.md §5。

REST ``RunConfig`` 字段缺省仍为 ``None``（表示请求可省略该键），
与本模块「确认卡预填」不是同一层语义，禁止把 REST 可选与预填默认混为一谈。
"""

from __future__ import annotations

from typing import Any

# 评测运行段预填（PRD 5.2.2）
DEFAULT_RUN: dict[str, Any] = {
    "sample_size": 1000,
    "concurrency": 4,
    "timeout_s": 60,
    "retry": 1,
    "temperature": 0,
    "max_tokens": 1024,
    "system_prompt": "",
    "k": 5,
    "use_judge": False,
    "judge_profile_id": None,
}

# 派生压测段预填（with_stress=true 时使用）
DEFAULT_STRESS: dict[str, Any] = {
    "env": "test",
    "qps": 10,
    "duration_s": 120,
    "sla_p99_ms": None,
}

DEFAULT_WITH_STRESS = False
DEFAULT_RAG_MODE: list[str] = ["hybrid"]


def default_task_spec(kind: str = "benchmark") -> dict[str, Any]:
    """返回确认卡 TaskSpec 预填骨架（缺资产 ID，由用户或规划槽位补齐）。

    ``case_source`` 只挂在 ``testcase`` 上：空 ``{text: ""}`` 会触发
    ``CaseSource`` 二选一门禁，质量任务确认时误报「缺少用例来源」。
    """
    spec: dict[str, Any] = {
        "kind": kind,
        "profile_ids": [],
        "dataset_id": None,
        "kb_id": None,
        "gold_qa_id": None,
        "rag_mode": list(DEFAULT_RAG_MODE),
        "run": dict(DEFAULT_RUN),
        "with_stress": DEFAULT_WITH_STRESS,
        "stress": dict(DEFAULT_STRESS),
    }
    if kind == "testcase":
        spec["case_source"] = {"text": ""}
    return spec
