"""跨测试文件共享的非夹具辅助。

``enable_hybrid_engine`` 供「直接调用」风格的测试使用（这些测试在函数体内
调用辅助而非通过夹具参数注入），与 ``conftest.engine_on`` 夹具共享同一实现。
"""

from app.config import settings


def enable_hybrid_engine(monkeypatch) -> None:
    """开启混合引擎主开关（L1 CoT 默认关闭，纯 L0 可复现）。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
