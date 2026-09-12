"""backend/api 测试共享夹具（收敛重复定义）。

收敛前 ``tmp_root`` 在 3 个测试文件、``hybrid_on`` 在 2 个文件内逐字重复定义；
本模块为上述夹具的唯一事实源。直接调用风格（非夹具）的辅助见 ``tests/_helpers.py``。
"""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from tests._helpers import enable_hybrid_engine


@pytest.fixture
def client() -> TestClient:
    """真实 app 的 HTTP 客户端（未登录态，用于鉴权与契约测试）。"""
    return TestClient(app)


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    """把 Agent 工作区根指向临时目录（预创建目录）并返回该路径。"""
    root = tmp_path / "workspaces"
    root.mkdir()
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(root))
    return root


@pytest.fixture
def hybrid_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """开启混合引擎主开关（L1 CoT 默认关闭，纯 L0 可复现）。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    monkeypatch.setattr(settings, "hybrid_router_cot_enabled", False)


@pytest.fixture
def engine_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """仅开启混合引擎主开关（供 DAG/TAOR 图级测试使用）。"""
    enable_hybrid_engine(monkeypatch)
