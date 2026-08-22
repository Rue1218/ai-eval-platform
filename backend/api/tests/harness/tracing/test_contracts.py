"""Harness 架构契约：内部 ErrorClass、静态 Schema 与线上入口归属。"""

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
FORBIDDEN_CONTEXT_MODULES = {"redis", "sqlalchemy", "app.llm", "app.adapters", "app.models"}
LEGACY_COORDINATOR_PATHS = (
    "app/agent/harness.py",
    "app/agent/react.py",
    "app/agent/plan.py",
    "app/agent/context.py",
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


def test_context_layer_only_depends_on_contracts_and_memory_port():
    """Context 负责编译和计量，不得重新查询 ORM 或调用 Redis、模型客户端。"""
    for path in (HARNESS_ROOT / "context").glob("*.py"):
        imported = _imported_modules(path)
        overlap = imported & FORBIDDEN_CONTEXT_MODULES
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


def test_ws_routes_to_new_session_runtime():
    """线上 WS 入口必须直接使用新编排总控，不能再经旧 Agent 桥接。"""
    imported = _imported_modules(API_ROOT / "app" / "routers" / "ws.py")
    assert "harness.orchestration.session_runtime" in imported


def test_legacy_agent_runtime_modules_are_removed():
    """旧 Harness / ReAct / Plan / Context 模块不得以兼容壳残留，防止双轨重新出现。"""
    for rel in LEGACY_COORDINATOR_PATHS:
        assert not (API_ROOT / rel).exists(), rel

    for path in (API_ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "app.agent.harness" not in text, path
        assert "app.agent.react" not in text, path
        assert "app.agent.plan" not in text, path
        assert "app.agent.context" not in text, path
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            assert node.module not in {
                "app.agent.harness",
                "app.agent.react",
                "app.agent.plan",
                "app.agent.context",
            }, path
            if node.module == "app.agent":
                imported_names = {alias.name for alias in node.names}
                assert not ({"harness", "react", "plan", "context"} & imported_names), path


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
    variants = schema["oneOf"]
    single = next(item for item in variants if "arguments" in item["properties"])
    batch = next(item for item in variants if "tool_calls" in item["properties"])
    assert "trace_id" not in single["properties"]
    assert "span_id" not in single["properties"]
    assert single["properties"]["arguments"]["type"] == "object"
    items = batch["properties"]["tool_calls"]["items"]
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
