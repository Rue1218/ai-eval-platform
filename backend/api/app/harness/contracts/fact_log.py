"""AgentLoop 的最小事实日志端口，不包含主会话投影或数据库写者实现。"""

from typing import Any, Protocol


class FactLog(Protocol):
    """同一运行内有序、提交后可读的事实；session_id 始终表示授权会话。"""

    session_id: str

    def append(self, kind: str, data: dict[str, Any], /) -> dict[str, Any]:
        """原子追加事实并返回含 seq、ts、type、data 的已提交记录。"""
        ...

    def read(self) -> list[dict[str, Any]]:
        """读取本运行的独立有序历史；不得合并其他专家或主会话历史。"""
        ...


class RuntimeLog(FactLog, Protocol):
    """Runtime 所需的作者上下文；持久实现可额外提供原子的 begin_turn。"""

    actor_id: str | None
    command_context: dict[str, Any]


def log_run_id(log: FactLog) -> str | None:
    """主日志无 run_id；子日志必须显式声明非空身份，禁止悄悄回落主域。"""
    value = getattr(log, "run_id", None)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError("子运行日志必须具有非空 run_id")
    return value


def execution_key(log: FactLog) -> str:
    """进程内审批/图命名空间与授权会话分离，主运行保持旧键兼容。"""
    import json

    run_id = log_run_id(log)
    return log.session_id if run_id is None else "subagent:" + json.dumps(
        [log.session_id, run_id], ensure_ascii=True, separators=(",", ":")
    )
