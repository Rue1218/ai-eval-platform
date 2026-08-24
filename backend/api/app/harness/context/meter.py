"""Harness 上下文工程层：ContextMeter 投影（M2 阶段 3，CX-7）。

只读 ``GET /api/sessions/{id}/messages`` 的 ``context_meter`` 字段投影前端
可读 meter；**本层只投影，不重算 token / 窗口占比**（CX-7：前端不自行
计算，服务端数据源提供）。``context_meter`` 为 null 时返回 None（前端不渲染
容量仪表）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict


class ContextMeter(TypedDict, total=False):
    """ContextMeter 投影，只读 context_meter 字段（CX-7）。"""

    token_used: int
    token_limit: int
    window_ratio: float
    compacted: bool


def project_meter(context_meter: Mapping[str, object] | None) -> ContextMeter | None:
    """从会话 messages 的 context_meter 字段投影前端可读 meter。

    - ``null``/空 → None（前端不渲染容量仪表）；
    - 缺失键回退：token_used=0、token_limit=0、window_ratio=0.0、compacted=False。
    """
    if not context_meter:
        return None
    token_limit = int(context_meter.get("token_limit") or 0)
    token_used = int(context_meter.get("token_used") or 0)
    ratio = float(context_meter.get("window_ratio") or 0.0)
    if token_limit > 0 and "window_ratio" not in context_meter:
        ratio = round(token_used / token_limit, 4)
    return ContextMeter(
        token_used=token_used,
        token_limit=token_limit,
        window_ratio=ratio,
        compacted=bool(context_meter.get("compacted", False)),
    )
