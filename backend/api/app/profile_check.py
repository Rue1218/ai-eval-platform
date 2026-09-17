"""连通检查使用对话同源的流式请求，只判断本次模型端点能否响应。"""

import asyncio
import time

from .llm.contracts import ModelConfig
from .llm.loop_contracts import Done, LlmRequestError, ReasoningDelta, TextDelta
from .llm.resolver import build_adapter, close_adapter, resolve_request


async def _check_model_connection(config: ModelConfig) -> dict:
    """等待首个有效输出即关闭流；超时与错误不写回已验证能力。"""
    started = time.perf_counter()
    adapter = stream = None
    try:
        async with asyncio.timeout(config.timeout_s):
            request = resolve_request(config, messages=[{"role": "user", "content": "请简短回复 pong。"}])
            adapter, _ = build_adapter(config)
            stream = adapter.stream(request)
            async for event in stream:
                responded = isinstance(event, TextDelta | ReasoningDelta) and bool(event.text.strip())
                completed = isinstance(event, Done) and event.finish_reason in {"stop", "length"}
                if responded or completed:
                    return {"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000), "model": config.model}
            return {"ok": False, "code": "UPSTREAM", "message": "模型流未返回有效输出或正常终态，请检查协议与流式支持"}
    except LlmRequestError as exc:
        # SDK 异常已经由运行时分类为平台固定文案，不向浏览器传递上游原文。
        return {"ok": False, "code": exc.public_code, "message": str(exc)}
    except TimeoutError:
        return {"ok": False, "code": "TIMEOUT", "message": "本次连通测试等待响应超时；模型冷启动或高强度思考可能需要更长时间"}
    except Exception:
        return {"ok": False, "code": "UPSTREAM", "message": "本次模型探测未完成，请检查配置或稍后重试"}
    finally:
        # 提前收到输出也必须关闭异步生成器，触发适配器 finally 释放 HTTP 流。
        for resource, close in ((stream, lambda item: item.aclose()), (adapter, close_adapter)):
            if resource is not None:
                try:
                    await asyncio.wait_for(close(resource), timeout=1.0)
                except Exception:
                    pass


def check_model_connection(config: ModelConfig) -> dict:
    """同步 REST 路由在线程池调用，不阻塞 API 事件循环。"""
    return asyncio.run(_check_model_connection(config))
