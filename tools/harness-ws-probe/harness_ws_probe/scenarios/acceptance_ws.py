"""V1.9/G4-G5 工作区绑定 + L1 workflow 确认卡验收（REST + WS 组合）。"""

from __future__ import annotations

import json
from typing import Any

from ..client import ProbeClient
from ..errors import ProbeError
from ..expect import ExpectMatcher, ProbeAssertion
from .acceptance import AcceptanceReport, MAX_WAIT_TURN, _now, drain, _payload

NOT_FOUND = "00000000-0000-0000-0000-000000000000"


async def http_json(
    client: ProbeClient, method: str, path: str, body: Any = None
) -> tuple[int, dict[str, Any]]:
    http = client._http
    if http is None:
        await client.login()
        http = client._http
    response = await http.request(method, path, json=body)
    try:
        data = json.loads(response.text) if response.text else {}
    except json.JSONDecodeError:
        data = {"raw": response.text[:200]}
    if not isinstance(data, dict):
        data = {"raw": str(data)[:200]}
    return response.status_code, data


def _is_validation(code: int, data: dict[str, Any]) -> bool:
    return code >= 400 and str(data.get("code")) == "VALIDATION"


async def run_workflow_confirm(
    client: ProbeClient, report: AcceptanceReport, *, allow_enqueue: bool
) -> None:
    """L1 workflow 确认卡：自然语言触发 → 取消或入队。"""
    text = (
        "帮我创建一个 benchmark 评测任务：用 Alibaba Qwen (qwen-plus) 协议档 "
        "做 1 条样本的评测，先给我确认卡，不要直接入队"
    )
    mark = len(client.trace.frames)
    try:
        await client.send_user_message(text)
        try:
            await client.wait_event("confirm", timeout_s=MAX_WAIT_TURN)
        except ProbeError:
            pass
        await drain(client, 0.4)
        cards = [
            f for f in client.trace.frames[mark:]
            if f.dir == "down" and f.event == "confirm"
        ]
        if not cards:
            report.record("L1 workflow 确认卡触发", "NA", "Router 未走 workflow/W5")
            return
        ExpectMatcher(client.trace).card_payload_clean("confirm")
        payload = _payload(cards[-1])
        kind = payload.get("kind")
        if not kind:
            raise ProbeAssertion("confirm 卡缺少 kind")
        if allow_enqueue:
            await client.send_confirm_ack(
                True, {"run": {"sample_size": 1}, "with_stress": False}
            )
            await client.wait_event("confirm_ack", timeout_s=30)
            ExpectMatcher(client.trace).confirm_enqueued()
            report.record("L1 workflow confirm_ack 入队", "PASS", f"kind={kind}")
        else:
            await client.send_confirm_ack(False)
            await client.wait_event("confirm_ack", timeout_s=30)
            ExpectMatcher(client.trace).confirm_cancelled()
            report.record("L1 workflow 确认卡取消", "PASS", f"kind={kind}")
    except (ProbeAssertion, ProbeError) as exc:
        report.record("L1 workflow 确认卡路径", "FAIL", str(exc))


async def run_workspace_bind(client: ProbeClient, report: AcceptanceReport) -> None:
    """V1.75/1.76 用户工作区与会话绑定验收（BLK-4/防穿越/WS 建连）。"""
    ws_id: str | None = None
    bound_id: str | None = None
    try:
        code, data = await http_json(client, "POST", "/api/workspaces", {"name": f"probe-acc-{_now()}"})
        if code >= 400:
            report.record("V1.9 POST /api/workspaces", "FAIL", f"HTTP {code} {data}")
            return
        ws_id = str(data.get("id") or "")
        report.record("V1.9 POST /api/workspaces", "PASS", ws_id)

        code, data = await http_json(
            client, "POST", "/api/sessions",
            {
                "title": "acceptance-bound",
                "visibility": "private",
                "engine_version": "legacy",
                "workspace_id": ws_id,
                "scope_path": "probe_sub",
            },
        )
        if code >= 400 or not data.get("workspace_id"):
            report.record("V1.76 会话绑定创建", "FAIL", f"HTTP {code} {data}")
        else:
            bound_id = str(data.get("id") or "")
            fields = {
                "workspace_id": data.get("workspace_id"),
                "scope_path": data.get("scope_path"),
                "workspace_name": data.get("workspace_name"),
            }
            if data.get("scope_path") != "probe_sub" or not fields["workspace_name"]:
                report.record("V1.76 会话绑定创建", "FAIL", f"字段缺失 {fields}")
            else:
                report.record("V1.76 会话绑定创建", "PASS", str(fields))

        code, data = await http_json(
            client, "POST", "/api/sessions",
            {"title": "bound-team", "visibility": "team", "workspace_id": ws_id},
        )
        if not _is_validation(code, data):
            report.record("V1.76 BLK-4 team+绑定拒绝", "FAIL", f"HTTP {code} {data}")
        else:
            report.record("V1.76 BLK-4 team+绑定拒绝", "PASS")

        code, data = await http_json(
            client, "POST", "/api/sessions",
            {"title": "bound-none", "workspace_id": NOT_FOUND},
        )
        if not _is_validation(code, data):
            report.record("V1.76 不存在工作区 fail-closed", "FAIL", f"HTTP {code} {data}")
        else:
            report.record("V1.76 不存在工作区 fail-closed", "PASS")

        if bound_id:
            code, data = await http_json(
                client, "PUT", f"/api/sessions/{bound_id}/sharing", {"visibility": "team"}
            )
            if not _is_validation(code, data):
                report.record("V1.76 绑定会话转 team 拒绝", "FAIL", f"HTTP {code} {data}")
            else:
                report.record("V1.76 绑定会话转 team 拒绝", "PASS")
            try:
                await client.disconnect()
                await client.connect(session_id=bound_id, last_event_id=0)
                await drain(client, 0.5)
                ExpectMatcher(client.trace).vocab_version_consistent()
                report.record("V1.76 绑定会话 legacy WS 建连", "PASS")
            except (ProbeAssertion, ProbeError) as exc:
                report.record("V1.76 绑定会话 legacy WS 建连", "FAIL", str(exc))
            finally:
                await client.disconnect()

        code, data = await http_json(client, "GET", f"/api/workspaces/{ws_id}/files")
        if code >= 400:
            report.record("V1.75 files 一层浏览", "FAIL", f"HTTP {code} {data}")
        else:
            count = len(data.get("entries") or [])
            report.record("V1.75 files 一层浏览", "PASS", f"entries={count}")

        code, data = await http_json(client, "GET", f"/api/workspaces/{ws_id}/files?path=..%2F..")
        if not _is_validation(code, data):
            report.record("V1.75 files 防穿越", "FAIL", f"HTTP {code} {data}")
        else:
            report.record("V1.75 files 防穿越", "PASS")

        report.record("G4/G5 沙箱档位策略", "NA", "runner policy 属 Worker 侧，黑盒 WS 不可观测")
    except Exception as exc:  # noqa: BLE001 —— 验收套件必须继续并上报
        report.record("V1.9/G5 工作区绑定套件", "FAIL", f"{type(exc).__name__}: {exc}")
    finally:
        try:
            if bound_id:
                await http_json(client, "DELETE", f"/api/sessions/{bound_id}")
            if ws_id:
                await http_json(client, "DELETE", f"/api/workspaces/{ws_id}")
                await http_json(client, "DELETE", f"/api/workspaces/{ws_id}?purge=true")
        except Exception:  # noqa: BLE001 —— 兜底清理失败只记录
            report.record("工作区/会话兜底清理", "FAIL", "清理失败，需人工处理")
