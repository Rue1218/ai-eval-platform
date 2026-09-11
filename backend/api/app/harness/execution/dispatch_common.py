"""Harness 执行层：dispatch 共享底层（预览预算 / 行边界截取 / 网络防护）。

从 dispatch.py 拆出（2026-09-11 巨型文件治理）：read/write/bash/web 多域共用；
网络防护（BLOCKED_NETWORKS / _is_blocked_ip / _reject_internal_target）供
web_fetch 的 SSRF 前置校验使用。
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable

from app.config import settings
from app.errors import AppError, ErrorCode


def preview_char_limit() -> int:
    """ToolCard 浏览器预览上限（字符，完整行边界截取）。

    默认与 read 模型窗口预算（READ_MAX_CHARS）同源对齐，保证「卡片所见 ==
    模型真实读取内容」；部署经 TOOL_PREVIEW_MAX_CHARS 调整（如设 4000 收紧
    回旧版安全窗，避免大文件进入 WS 广播与历史事件）。
    """
    return max(1, int(settings.tool_preview_max_chars))

# handler 可在受控输出生成时调用回调；回调由 ToolNode 注入，未运行在图内时为 None。
ToolOutputCallback = Callable[[str, str, int | None], None]
# 网络工具的阶段回调只描述生命周期，不包含 URL、正文或密钥。
ToolProgressCallback = Callable[[str, str], None]


# SSRF 防护：web_fetch 抓取目标命中以下内网/回环/链路本地/保留地址段即拒绝。
# 含 IPv4 保留段、IPv6 回环/ULA/链路本地/多播与文档地址（RFC 1918/6890/3849 等）。
BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("2001:db8::/32"),
    ipaddress.ip_network("ff00::/8"),
)


def _is_blocked_ip(ip: str) -> bool:
    """判定 IP 是否命中内网/回环/保留地址段；无法识别一律拒绝（fail-closed）。

    IPv4 映射 IPv6（``::ffff:127.0.0.1``）先还原为 IPv4 再判定，防止绕过。
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return any(addr in network for network in BLOCKED_NETWORKS)


def _reject_internal_target(host: str) -> None:
    """SSRF 防护：主机名/IP 解析结果命中内网地址即拒绝（web_fetch 前置校验）。

    覆盖 IP 字面量（含十进制/十六进制/八进制等非标准写法）、域名解析结果与
    IPv4 映射 IPv6；域名先解析校验再发起请求，阻止直连容器内网/回环服务。
    （解析与请求间存在极小 DNS 重绑定窗口，属可接受的残余风险。）
    """
    try:
        ipaddress.ip_address(host)  # host 本身是 IP 字面量
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            raise AppError(ErrorCode.UPSTREAM, "域名解析失败") from None
        resolved = {info[4][0] for info in infos}
        if not resolved:
            raise AppError(ErrorCode.UPSTREAM, "域名解析失败")
        if any(_is_blocked_ip(ip) for ip in resolved):
            raise AppError(ErrorCode.VALIDATION, "禁止访问内网/回环地址")
        return
    if _is_blocked_ip(host):
        raise AppError(ErrorCode.VALIDATION, "禁止访问内网/回环地址")


def clip_at_line_boundary(text: str, max_chars: int) -> tuple[str, bool]:
    """按字符预算截取，只保留完整行；单行超长才截断该行。"""
    if max_chars <= 0:
        return "", True
    if len(text) <= max_chars:
        return text, False
    window = text[:max_chars]
    last_nl = window.rfind("\n")
    if last_nl >= 0:
        return window[: last_nl + 1], True
    return window, True
