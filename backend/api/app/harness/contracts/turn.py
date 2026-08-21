"""回合终态：写入 harness_turns.status；对外 WS 不新增字段。"""

from enum import StrEnum


class TurnStatus(StrEnum):
    """一个用户 Turn 的持久化状态。

    ``CANCELLING`` 是取消调度已发出、尚未收敛的中间态；``CANCELLED`` 才是终态。
    ``FINALIZING_STREAM`` 归阶段 3，本枚举不包含。
    """

    INIT = "INIT"
    EXECUTING = "EXECUTING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    FINISHED = "FINISHED"
    FAILED_STOP = "FAILED_STOP"
