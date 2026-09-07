"""原生 ToolCall 的单回合临时结果存储。

完整工具正文只在同一 Agent 图运行期间供下一次模型调用使用。它不能放入
GraphState、RunnableConfig、WS 事件或检查点，避免大文件 read 结果被持久化或
被通用追踪回调误采集。

#2（dsh 改进，上下文压缩事件化首期落地物）：**超大 tool_result 先裁剪再进窗**
——``put`` 对超长正文做长度上限与截断标注（对照 read 模型窗口预算
``READ_MAX_CHARS=600_000`` 同源口径），模型经 ``get`` 只见带标注的截断结果，
防止超大工具结果直接占满窗口且无裁剪留痕。裁剪只发生在进程内临时存储层，
不改动观察/事件的既有脱敏投影纪律。
"""

from __future__ import annotations

from threading import RLock

# 单条工具正文进入临时存储的长度上限（字符）：与 read 模型窗口预算
# （READ_MAX_CHARS=600_000）同源对齐；超限先裁剪再进窗（#2 首期）。
TOOL_RESULT_STORE_MAX_CHARS = 600_000

# 截断标注（模型可见）：声明裁剪事实与保留范围，禁止假装全文在手。
_TRUNCATE_NOTICE = (
    "\n\n[注意：工具结果过长，已截断，仅保留前 {limit} 字符——"
    "如需更多内容请用工具的分页/范围参数分次读取]"
)


def clip_for_store(content: str) -> tuple[str, bool]:
    """按 store 长度上限裁剪并追加截断标注（#2）。

    返回 ``(裁剪后正文, 是否发生截断)``；未超限时原样返回、不追加标注
    （行为默认不变，避免小结果被无谓污染）。
    """
    if content is None:
        return "", False
    if len(content) <= TOOL_RESULT_STORE_MAX_CHARS:
        return content, False
    clipped = content[:TOOL_RESULT_STORE_MAX_CHARS]
    return clipped + _TRUNCATE_NOTICE.format(limit=TOOL_RESULT_STORE_MAX_CHARS), True


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
        # #2：发生截断的 (thread_id, call_id) 留痕（进程内审计，不入检查点）
        self._truncated: set[tuple[str, str]] = set()

    def put(self, thread_id: str, call_id: str, content: str) -> bool:
        """写入一项结果；回合或调用标识无效时拒绝写入。

        #2：超长正文先按 ``clip_for_store`` 裁剪并追加截断标注再存（模型经
        ``get`` 只见带标注的截断结果）。
        """
        if not thread_id or not call_id:
            return False
        stored, truncated = clip_for_store(content)
        with self._lock:
            self._results.setdefault(thread_id, {})[call_id] = stored
            if truncated:
                self._truncated.add((thread_id, call_id))
            else:
                self._truncated.discard((thread_id, call_id))
        return True

    def get(self, thread_id: str, call_id: str) -> str | None:
        """读取同一回合、同一调用的正文（含 #2 截断标注）；不存在返回 ``None``。"""
        if not thread_id or not call_id:
            return None
        with self._lock:
            return self._results.get(thread_id, {}).get(call_id)

    def was_truncated(self, thread_id: str, call_id: str) -> bool:
        """该条结果是否在写入时被 #2 裁剪（可审计留痕）。"""
        if not thread_id or not call_id:
            return False
        with self._lock:
            return (thread_id, call_id) in self._truncated

    def clear(self, thread_id: str) -> None:
        """清理一轮全部正文，防止长 read 结果滞留进程内存。"""
        if not thread_id:
            return
        with self._lock:
            self._results.pop(thread_id, None)
            self._truncated = {pair for pair in self._truncated if pair[0] != thread_id}
