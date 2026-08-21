"""Agent 控制台追踪。只打运行状态，禁止输出 API Key、Cookie、密码。"""

import logging
import sys

logger = logging.getLogger("ai-eval.agent")


def _prefixed(message: str) -> str:
    """若当前任务已绑定 TraceContext，自动带上 trace_id/span_id/turn_id。"""
    if message.startswith("trace_id="):
        return message
    try:
        from app.harness.contracts.trace import current_trace, format_trace_prefix

        trace = current_trace()
        if trace is not None:
            return f"{format_trace_prefix(trace)} {message}"
    except Exception:
        pass
    return message


def agent_trace(message: str) -> None:
    """同步打印到进程控制台（Docker logs 可见），并写入 logger。

    调用方必须自行保证 ``message`` 不含密钥；本函数不做脱敏以外的过滤。
    已绑定的 TraceContext 由本函数自动写入前缀，禁止依赖人工拼接。
    """
    line = f"[agent] {_prefixed(message)}"
    print(line, file=sys.stderr, flush=True)
    logger.info("%s", message)


def agent_exception(message: str, exc: BaseException) -> None:
    """把未预期异常打到控制台（含 traceback），供 Docker logs 排查。"""
    line = f"[agent] {_prefixed(message)} type={type(exc).__name__}"
    print(line, file=sys.stderr, flush=True)
    logger.exception("%s", message)
