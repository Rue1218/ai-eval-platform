"""大模型调用层日志：只记录协议、模型、耗时和错误类型。"""

from __future__ import annotations

import logging
import sys

from app.runtime.trace import current_trace, format_trace_prefix

logger = logging.getLogger("ai-eval.llm")


def _prefixed(message: str) -> str:
    """为模型层日志附加当前链路标识，不附加任何凭据。"""
    trace = current_trace()
    if trace is None:
        return message
    return f"{format_trace_prefix(trace)} {message}"


def llm_trace(message: str) -> None:
    """输出模型层运行日志；保留 ``[agent]`` 前缀兼容现有部署采集。"""
    line = f"[agent] {_prefixed(message)}"
    print(line, file=sys.stderr, flush=True)
    logger.info("%s", message)


def llm_exception(message: str, exc: BaseException) -> None:
    """输出服务端模型层异常，浏览器只接收归一化错误码。"""
    line = f"[agent] {_prefixed(message)} type={type(exc).__name__}"
    print(line, file=sys.stderr, flush=True)
    logger.exception("%s", message)
