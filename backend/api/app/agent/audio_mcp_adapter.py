"""可注入的音频 MCP 调用边界。

本模块只定义平台与具体 MCP transport 之间的稳定契约。真实 MCP Server
的 transport、工具名和 wire schema 尚未确定，因此这里不实现网络、stdio
或 MCP SDK 调用，也不猜测远程响应结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..errors import AppError, ErrorCode
from .log import agent_trace


@dataclass(frozen=True)
class AudioMcpRequest:
    """发送给具体 transport 的规范化音频请求。"""

    ref_bytes: bytes
    ref_mime: str
    text: str
    style: str = ""


@dataclass(frozen=True)
class AudioMcpResponse:
    """具体 transport 返回的规范化音频结果。"""

    data: bytes
    mime_type: str | None = None


class AudioMcpTransport(Protocol):
    """具体 MCP transport 的最小同步接口。"""

    def invoke(self, request: AudioMcpRequest, *, timeout_s: float) -> object:
        """调用远程工具并返回原始或规范化结果。"""
        ...


def _audio_bytes(value: object, *, field: str) -> bytes:
    if isinstance(value, bytes):
        data = value
    elif isinstance(value, bytearray | memoryview):
        data = bytes(value)
    else:
        raise AppError(ErrorCode.UPSTREAM, f"音频 MCP 返回的{field}无效")
    if not data:
        raise AppError(ErrorCode.UPSTREAM, "音频 MCP 返回空音频")
    return data


def normalize_request(
    *,
    ref_bytes: bytes | bytearray | memoryview,
    ref_mime: str,
    text: str,
    style: str = "",
) -> AudioMcpRequest:
    """校验并规范化传给 transport 的请求，不序列化为猜测的 MCP JSON。"""
    try:
        reference = _audio_bytes(ref_bytes, field="参考音频")
    except AppError:
        raise AppError(ErrorCode.VALIDATION, "参考音频不能为空且必须是二进制") from None
    if not isinstance(ref_mime, str) or not ref_mime.strip():
        raise AppError(ErrorCode.VALIDATION, "参考音频 MIME 类型无效")
    mime = ref_mime.strip().lower()
    if not mime.startswith("audio/"):
        raise AppError(ErrorCode.VALIDATION, "参考音频必须是音频 MIME 类型")
    if not isinstance(text, str) or not text.strip():
        raise AppError(ErrorCode.VALIDATION, "请输入要合成的文本")
    if not isinstance(style, str):
        raise AppError(ErrorCode.VALIDATION, "音频风格参数无效")
    return AudioMcpRequest(
        ref_bytes=reference,
        ref_mime=mime,
        text=text.strip(),
        style=style.strip(),
    )


def normalize_response(value: object) -> AudioMcpResponse:
    """只接受 transport 已明确归一化的 bytes 结果，拒绝猜测远程 Schema。"""
    if isinstance(value, AudioMcpResponse):
        data = _audio_bytes(value.data, field="数据")
        mime_type = value.mime_type.strip().lower() if isinstance(value.mime_type, str) else value.mime_type
        if mime_type is not None and (not isinstance(mime_type, str) or not mime_type.startswith("audio/")):
            raise AppError(ErrorCode.UPSTREAM, "音频 MCP 返回的 MIME 类型无效")
        return AudioMcpResponse(data=data, mime_type=mime_type)
    return AudioMcpResponse(data=_audio_bytes(value, field="数据"))


def synthesize_via_mcp(
    *,
    ref_bytes: bytes | bytearray | memoryview,
    ref_mime: str,
    text: str,
    style: str = "",
    transport: AudioMcpTransport,
    timeout_s: float = 90.0,
) -> bytes:
    """通过注入的 MCP transport 合成音频并返回二进制内容。

    transport 的具体 MCP 握手、工具调用和响应解析由后续供应商适配层实现；
    本函数只负责平台边界的输入校验、错误归一化和结果校验。
    """
    if not isinstance(timeout_s, int | float) or isinstance(timeout_s, bool) or timeout_s <= 0:
        raise AppError(ErrorCode.VALIDATION, "音频 MCP 超时参数无效")
    request = normalize_request(
        ref_bytes=ref_bytes,
        ref_mime=ref_mime,
        text=text,
        style=style,
    )
    try:
        response = transport.invoke(request, timeout_s=float(timeout_s))
        return normalize_response(response).data
    except AppError:
        raise
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "音频 MCP 调用超时") from exc
    except OSError as exc:
        raise AppError(ErrorCode.UPSTREAM, "音频 MCP 连接失败") from exc
    except Exception as exc:
        agent_trace(f"音频 MCP 调用内部异常 type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "音频 MCP 调用失败") from exc
