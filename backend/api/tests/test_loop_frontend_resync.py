"""浏览器缺口重订阅不得取消正在执行的控制者回合。"""

import asyncio

from tests.test_loop_ws_handler import FakeService, connect, disconnect, until


def test_same_connection_resubscribe_preserves_controller():
    """同会话重订阅保留 owner 和 attach；只有最终断连触发取消。"""
    async def scenario():
        """驱动真实 WS handler 的命令与回放循环。"""
        service = FakeService()
        socket, connection, task = await connect(service)
        await socket.push("turn.submit", {"client_message_id": "m", "content": "run"}, request_id="submit")
        await until(lambda: service.effects == 1)
        await socket.push("subscribe", {"after_cursor": 0}, request_id="resync")
        await until(lambda: sum(f["type"] == "replay.completed" for f in socket.sent) == 2)
        assert service.owner == connection.connection_id
        assert service.cancelled == 0 and service.detached == []
        await disconnect(socket, task)
        assert service.cancelled == 1

    asyncio.run(scenario())
