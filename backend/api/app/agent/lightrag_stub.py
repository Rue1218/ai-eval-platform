"""LightRAG 接入占位。

M3 之前：任何查询 / 评测入口都必须走 ``assert_lightrag_ready``，抛统一 AppError，
并在控制台打印，避免对话或 Worker 假装 RAG 成功。

M3 接入时：将 ``LIGHTRAG_ENABLED`` 置 True，在 ``query_lightrag`` 内请求
Compose 服务 ``lightrag:9621`` 的原生 ``POST /query``，适配为
``{text, contexts[{id,text}]}``。禁止把 LightRAG 伪装成 OpenAI Chat。
"""

from ..errors import AppError, ErrorCode
from .log import agent_trace

# M3 接真查询时改为 True，并实现下方 query_lightrag 的 HTTP 分支
LIGHTRAG_ENABLED = False

_NOT_READY_MESSAGE = "RAG / LightRAG 尚未接入（计划 M3），当前请使用基准评测"


def assert_lightrag_ready(*, reason: str) -> None:
    """LightRAG 未就绪时抛 ``VALIDATION``，并打印到控制台。

    ``reason`` 仅用于排障（如 ws_intent_rag / worker_rag / page_kb），不含用户隐私。
    """
    try:
        agent_trace(f"LightRAG 检查 reason={reason} enabled={LIGHTRAG_ENABLED}")
        if LIGHTRAG_ENABLED:
            return
        raise AppError(
            ErrorCode.VALIDATION,
            _NOT_READY_MESSAGE,
            fields={"feature": "lightrag", "enabled": False, "reason": reason},
        )
    except AppError:
        raise
    except Exception as exc:
        agent_trace(f"LightRAG 就绪检查异常: {type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "LightRAG 就绪检查失败") from exc


def query_lightrag(*, query: str, mode: str = "hybrid", top_k: int = 5) -> dict:
    """查询入口。现阶段必失败；M3 在 ``LIGHTRAG_ENABLED`` 为 True 后补 HTTP。

    返回形状（将来）：``{"text": str, "contexts": [{"id": str, "text": str}]}``。
    """
    try:
        assert_lightrag_ready(reason="query_lightrag")
        # M3：在此调用 http://lightrag:9621/query ，解析后 return
        _ = (query, mode, top_k)
        raise AppError(ErrorCode.INTERNAL, "LightRAG 已启用但查询实现尚未编写")
    except AppError:
        raise
    except Exception as exc:
        agent_trace(f"LightRAG 查询异常: {type(exc).__name__}")
        raise AppError(ErrorCode.UPSTREAM, "LightRAG 查询失败") from exc
