"""Agent 控制台追踪。只打运行状态，禁止输出 API Key、Cookie、密码。"""

import logging
import sys

logger = logging.getLogger("ai-eval.agent")


def agent_trace(message: str) -> None:
    """同步打印到进程控制台（Docker logs 可见），并写入 logger。

    调用方必须自行保证 ``message`` 不含密钥；本函数不做脱敏以外的过滤。
    """
    line = f"[agent] {message}"
    print(line, file=sys.stderr, flush=True)
    logger.info("%s", message)


def agent_exception(message: str, exc: BaseException) -> None:
    """把未预期异常打到控制台（含 traceback），供 Docker logs 排查。"""
    line = f"[agent] {message} type={type(exc).__name__}"
    print(line, file=sys.stderr, flush=True)
    logger.exception("%s", message)
