"""阶段 0 契约隔离：内部 ErrorClass、静态 Schema、活路径零引用。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.errors import ErrorCode
from app.harness.contracts.errors import ErrorClass, map_error_class_to_code
from app.harness.contracts.memory import MemoryQuery

API_ROOT = Path(__file__).resolve().parents[3]
HARNESS_ROOT = API_ROOT / "app" / "harness"
FORBIDDEN_MODULES = {"redis", "sqlalchemy", "app.llm", "app.adapters", "app.models"}
LIVE_PATHS_MUST_NOT_IMPORT_HARNESS = (
    "app/routers/ws.py",
)
LIVE_PATHS_MUST_REEXPORT_HARNESS = (
    "app/llm.py",
    "app/agent/mcp_tools.py",
    "app/agent/mcp_registry.py",
    "app/agent/react.py",
    "app/agent/harness.py",
)


def _imported_modules(path: Path) -> set[str]:
    """读取模块的绝对 import 名，供隔离断言。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.add(node.module.split(".")[0])
    return names


def test_map_error_class_follows_architecture_6_2():
    """§6.2：仅预算/确认/上游映射到 10 大码，其余只作 observation。"""
    assert map_error_class_to_code(ErrorClass.BUDGET_EXHAUSTED, deadline=True) is ErrorCode.TIMEOUT
    assert map_error_class_to_code(ErrorClass.BUDGET_EXHAUSTED, deadline=False) is ErrorCode.VALIDATION
    assert map_error_class_to_code(ErrorClass.NEED_APPROVAL) is ErrorCode.NEED_APPROVAL
    assert map_error_class_to_code(ErrorClass.UPSTREAM_TIMEOUT) is ErrorCode.TIMEOUT
    assert map_error_class_to_code(ErrorClass.UPSTREAM_ERROR) is ErrorCode.UPSTREAM
    assert map_error_class_to_code(ErrorClass.DONE_TOOL_CONFLICT) is None
    assert map_error_class_to_code(ErrorClass.CANCELLED) is None
    assert map_error_class_to_code(ErrorClass.MISSING_TOOL) is None


def test_error_code_enum_still_has_ten_codes():
    """内部 ErrorClass 不得把对外码扩成第二套协议。"""
    assert len(ErrorCode) == 10


def test_contracts_forbid_io_and_llm_imports():
    """契约层无 Redis / SQLAlchemy / LLM SDK。"""
    for path in (HARNESS_ROOT / "contracts").glob("*.py"):
        imported = _imported_modules(path)
        overlap = imported & FORBIDDEN_MODULES
        assert not overlap, f"{path.name} 引入了 {overlap}"


def test_app_py_does_not_assemble_runtime():
    """装配根不得在阶段 0 连接 Redis 或缓存 Turn。"""
    path = HARNESS_ROOT / "app.py"
    imported = _imported_modules(path)
    assert not (imported & FORBIDDEN_MODULES)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assigned = {
        node.targets[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert "_RUNTIME" not in assigned
    assert "get_runtime" not in functions
    assert "build_runtime" not in functions


def test_ws_and_session_harness_do_not_import_harness():
    """WS 收包循环不直接引用六层包；总控经 agent.harness 注入 token。"""
    for rel in LIVE_PATHS_MUST_NOT_IMPORT_HARNESS:
        text = (API_ROOT / rel).read_text(encoding="utf-8")
        assert "app.harness" not in text, rel


def test_phase1_reexport_modules_import_harness():
    """阶段 1 薄再导出必须指向 harness 正文。"""
    for rel in LIVE_PATHS_MUST_REEXPORT_HARNESS:
        text = (API_ROOT / rel).read_text(encoding="utf-8")
        assert "app.harness" in text, rel


def test_execution_and_feedback_do_not_import_llm():
    """执行层与反馈层不得持有模型客户端。"""
    forbidden = {"app.harness.llm", "app.llm", "app.adapters"}
    for folder in ("execution", "feedback"):
        for path in (HARNESS_ROOT / folder).rglob("*.py"):
            imported = _imported_modules(path)
            overlap = imported & forbidden
            assert not overlap, f"{path} 引入了 {overlap}"


def test_react_output_schema_forbids_trace_and_cot():
    """静态 Schema 不含 trace，也不含 CoT 指令。"""
    path = HARNESS_ROOT / "prompts" / "react-output.schema.json"
    raw = path.read_text(encoding="utf-8")
    assert "请逐步" not in raw
    assert "chain of thought" not in raw.lower()
    schema = json.loads(raw)
    properties = schema.get("properties", {})
    assert "trace_id" not in properties
    assert "span_id" not in properties
    assert properties["arguments"]["type"] == "object"
    items = properties["tool_calls"]["items"]
    assert items.get("additionalProperties") is False
    assert "trace_id" not in items["properties"]
    assert "span_id" not in items["properties"]


def test_memory_query_requires_trace_id():
    """MemoryQuery 必须携带非空 trace_id，禁止默认空串。"""
    with pytest.raises(ValidationError):
        MemoryQuery(query_text="status")
    with pytest.raises(ValidationError):
        MemoryQuery(query_text="status", trace_id="  ")
    query = MemoryQuery(query_text="status", trace_id="T-1")
    assert query.trace_id == "T-1"


def test_no_lightrag_adapter_file():
    """V1.0 首期禁止创建 long_term_lightrag.py。"""
    assert not (HARNESS_ROOT / "memory" / "long_term_lightrag.py").exists()
