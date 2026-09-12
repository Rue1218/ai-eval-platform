"""时间格式化工具：前端可解析的 UTC ISO 字符串（``...Z`` 后缀）唯一实现。

收敛前 ``routers/ws.py`` 与 ``harness/memory/preference.py`` 各存一份
``_iso`` 实现；本模块为唯一事实源。
"""

from datetime import UTC, datetime


def iso_utc(value: datetime | None = None) -> str:
    """把数据库时间统一转换为前端可解析的 UTC ISO 字符串；缺省取当前时间。"""
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat().replace("+00:00", "Z")
