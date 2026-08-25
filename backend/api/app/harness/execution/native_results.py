"""原生 ToolCall 的单回合临时结果存储。

完整工具正文只在同一 Agent 图运行期间供下一次模型调用使用。它不能放入
GraphState、RunnableConfig、WS 事件或检查点，避免大文件 read 结果被持久化或
被通用追踪回调误采集。
"""

from __future__ import annotations

from threading import RLock


def runtime_thread_id(configurable: object) -> str:
    """从 RunnableConfig 的受控命名空间提取非空回合标识。"""
    if not isinstance(configurable, dict):
        return ""
    return str(configurable.get("thread_id") or "").strip()


class NativeToolResultStore:
    """按回合隔离原生 ToolResult 正文的进程内存储。

    ``LangGraphAgent`` 在一轮图执行结束后调用 ``clear``。锁用于保护同一 API
    进程中并发 WebSocket 回合，且不把任意可序列化引用泄露给 LangGraph。
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._results: dict[str, dict[str, str]] = {}

    def put(self, thread_id: str, call_id: str, content: str) -> bool:
        """写入一项结果；回合或调用标识无效时拒绝写入。"""
        if not thread_id or not call_id:
            return False
        with self._lock:
            self._results.setdefault(thread_id, {})[call_id] = content
        return True

    def get(self, thread_id: str, call_id: str) -> str | None:
        """读取同一回合、同一调用的完整正文；不存在返回 ``None``。"""
        if not thread_id or not call_id:
            return None
        with self._lock:
            return self._results.get(thread_id, {}).get(call_id)

    def clear(self, thread_id: str) -> None:
        """清理一轮全部正文，防止长 read 结果滞留进程内存。"""
        if not thread_id:
            return
        with self._lock:
            self._results.pop(thread_id, None)
