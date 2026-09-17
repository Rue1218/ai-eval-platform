"""协议档原生工具探测：只回填随机测试值，绝不调用业务工具或调度器。"""

import asyncio
import secrets

from .agent.stream import AssistantAttempt
from .llm.contracts import ModelConfig
from .llm.loop_contracts import LlmRequestError, ToolSpec
from .llm.resolver import build_adapter, close_adapter, resolve_request


async def probe_tool_roundtrip(config: ModelConfig) -> dict[str, str]:
    """验证工具参数及结果消费；截断、断流、身份错误和错误回填均不能通过。"""
    adapter = None
    result = {"status": "failed", "effort": config.reasoning_effort if config.reasoning_enabled else "off"}
    try:
        async with asyncio.timeout(min(30.0, config.timeout_s)):
            adapter, _ = build_adapter(config)
            token, answer = secrets.token_hex(8), secrets.token_hex(16)
            tool = ToolSpec("profile_probe_echo", "仅用于连通性探测，返回测试结果，无外部副作用。", {
                "type": "object", "properties": {"token": {"type": "string"}},
                "required": ["token"], "additionalProperties": False,
            })
            messages = [{"role": "user", "content": (
                f"请调用 profile_probe_echo，参数 token 必须为 {token}。"
                "收到工具结果后，只原样回复工具返回的字符串，不添加其它文字。"
            )}]
            for step in range(2):
                request = resolve_request(config, messages=messages, tools=[tool])
                attempt = AssistantAttempt()
                async for chunk in adapter.stream(request):
                    attempt.push(chunk)
                if (attempt.done is None or attempt.incomplete_call_errors() or attempt.protocol_errors()):
                    return {**result, "error_code": "UPSTREAM"}
                if step == 0:
                    calls = attempt.tool_calls
                    if attempt.done.finish_reason != "tool_calls" or len(calls) != 1:
                        return {**result, "error_code": "TOOL_CALL_NOT_OBSERVED"}
                    call = calls[0]
                    if call["name"] != tool.name or call.get("args") != {"token": token}:
                        return {**result, "error_code": "TOOL_ARGUMENTS_INVALID"}
                    # 完整助手消息含协议私有推理状态；使用生产适配器完成第二次序列化。
                    messages.extend([attempt.message(), {
                        "role": "tool", "tool_call_id": call["id"], "name": tool.name, "content": answer,
                    }])
                elif attempt.done.finish_reason != "stop" or attempt.tool_calls or attempt.text.strip() != answer:
                    return {**result, "error_code": "TOOL_RESULT_NOT_CONFIRMED"}
            return {**result, "status": "passed"}
    except LlmRequestError as exc:
        return {**result, "error_code": exc.public_code}
    except TimeoutError:
        return {**result, "error_code": "TIMEOUT"}
    except Exception:
        # 异常可能含上游正文与密钥，仅返回平台安全分类。
        return {**result, "error_code": "UPSTREAM"}
    finally:
        if adapter is not None:
            try:
                await asyncio.wait_for(close_adapter(adapter), timeout=1.0)
            except Exception:
                pass
