"""回合状态：写入 harness_turns.status；对外 WS 不新增字段。"""

from enum import StrEnum


class TurnStatus(StrEnum):
    """一个用户 Turn 的持久化状态。

    ``CANCELLING`` 是取消调度已发出、尚未收敛的中间态；``CANCELLED`` 才是终态。
    批次执行与最终流式收尾是内部审计状态，不能据此扩展 WS 事件。
    """

    INIT = "INIT"
    PARSED = "PARSED"
    EXECUTING = "EXECUTING"
    PARALLEL_EXECUTING = "PARALLEL_EXECUTING"
    FEEDBACK_READY = "FEEDBACK_READY"
    FINALIZING_STREAM = "FINALIZING_STREAM"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    FINISHED = "FINISHED"
    FAILED_STOP = "FAILED_STOP"
