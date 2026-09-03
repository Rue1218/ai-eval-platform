"""Harness 提示词工程层（M1）：系统策略、阶段输出协议与注入安全。"""

from .protocols import (
    PLAN_SCHEMA,
    PLAN_VERSION,
    REACT_SCHEMA,
    REACT_VERSION,
    REFLECT_SCHEMA,
    REFLECT_VERSION,
    ROUTER_SCHEMA,
    ROUTER_VERSION,
    ProtocolName,
    ProtocolResult,
    check_version,
    parse_plan_protocol,
    parse_react,
    parse_reflect,
    parse_router,
)
from .safety import (
    INJECTION_PATTERNS,
    INJECTION_TEST_CASES,
    assert_user_text_safe,
    run_injection_tests,
)
from .system import (
    SYSTEM_PROMPT_TEMPLATE,
    SystemSection,
    SystemVars,
    assert_no_secret_leak,
    assert_no_takeover,
    build_system_prompt,
)

# 兼容导出：协议名 → 版本映射（供 M4 引用）
PROTOCOL: dict[str, str] = {
    "plan": PLAN_VERSION,
    "react": REACT_VERSION,
    "reflect": REFLECT_VERSION,
    "router": ROUTER_VERSION,
}

__all__ = [
    "INJECTION_PATTERNS",
    "INJECTION_TEST_CASES",
    "PLAN_SCHEMA",
    "PLAN_VERSION",
    "PROTOCOL",
    "REACT_SCHEMA",
    "REACT_VERSION",
    "REFLECT_SCHEMA",
    "REFLECT_VERSION",
    "ROUTER_SCHEMA",
    "ROUTER_VERSION",
    "SYSTEM_PROMPT_TEMPLATE",
    "ProtocolName",
    "ProtocolResult",
    "SystemSection",
    "SystemVars",
    "assert_no_secret_leak",
    "assert_no_takeover",
    "assert_user_text_safe",
    "build_system_prompt",
    "check_version",
    "parse_plan_protocol",
    "parse_react",
    "parse_reflect",
    "parse_router",
    "run_injection_tests",
]
