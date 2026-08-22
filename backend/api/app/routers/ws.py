"""Agent WebSocket 占位入口。

旧 Agent/Harness 收包循环已移除。新模型调用、Harness 和 Agent 范式确定后，
再按 API 契约重新接入；重建设计期间明确拒绝建立旧会话。
"""

from fastapi import APIRouter, WebSocket

router = APIRouter(tags=["ws"])


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket) -> None:
    """拒绝旧 Agent 连接，避免新旧两套运行时并存。"""
    await websocket.close(code=4406, reason="Agent 正在重建设计")
