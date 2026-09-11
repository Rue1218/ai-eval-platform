"""Harness 执行层：工具 JSON Schema 受限子集校验（M5，EX-1/EX-5）。

从 ``registry.py`` 拆出（2026-09-11 巨型文件治理）：纯函数、无状态，供
注册期契约校验（``ToolRegistry.register``）与运行期参数/展示投影校验
（``dispatch.execute_raw`` / ``loop_tools`` / ``toolnode``）共用。
只支持平台已实现、可本地确定解释的关键字子集；新增 MCP 工具不得静默携带
未校验的组合/引用规则，需要扩展时先实现校验语义并补测试。
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# 工具参数只接受平台已实现、可本地确定解释的 JSON Schema 子集。新增 MCP 工具
# 不得静默携带未校验的组合/引用规则；需要扩展时先实现校验语义并补测试。
_SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "description",
        "properties",
        "required",
        "additionalProperties",
        "enum",
        "items",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
    }
)
_SUPPORTED_JSON_TYPES = frozenset(
    {"object", "array", "string", "integer", "number", "boolean", "null"}
)


def required_parameter_names(schema: Mapping[str, object]) -> tuple[str, ...]:
    """提取工具 JSON Schema 的必填参数名，供既有 Gate 保持同一事实来源。

    完整的类型与范围校验由 ``validate_tool_arguments`` 完成；这里仅向既有
    Gate 提供必填字段投影，避免工具注册表与门禁各自维护一份 required 列表。
    """
    required = schema.get("required")
    if not isinstance(required, list | tuple):
        return ()
    return tuple(str(name) for name in required if isinstance(name, str) and name)


def validate_tool_schema(schema: Mapping[str, object]) -> str | None:
    """在注册期拒绝执行器尚未实现语义的 JSON Schema 关键字。"""
    return _validate_schema_definition(schema, "arguments")


def _validate_schema_definition(schema: Mapping[str, object], path: str) -> str | None:
    """递归验证 Schema 子集本身，避免运行时对未知规则静默放行。"""
    unsupported = sorted(str(key) for key in schema if key not in _SUPPORTED_SCHEMA_KEYWORDS)
    if unsupported:
        return f"{path} 包含不支持的关键字：{', '.join(unsupported)}"

    expected = schema.get("type")
    expected_types = (expected,) if isinstance(expected, str) else expected
    if expected is not None:
        if not isinstance(expected_types, list | tuple) or not expected_types:
            return f"{path}.type 必须是受支持的类型或非空类型列表"
        invalid_types = [str(item) for item in expected_types if item not in _SUPPORTED_JSON_TYPES]
        if invalid_types:
            return f"{path}.type 包含不支持的类型：{', '.join(invalid_types)}"

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            return f"{path}.properties 必须是对象"
        for key, child in properties.items():
            if not isinstance(key, str) or not key:
                return f"{path}.properties 包含无效参数名"
            if not isinstance(child, Mapping):
                return f"{path}.{key} 必须是 Schema 对象"
            error = _validate_schema_definition(child, f"{path}.{key}")
            if error:
                return error

    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list | tuple) or any(
            not isinstance(name, str) or not name for name in required
        ):
            return f"{path}.required 必须是非空字符串列表"
        if len(set(required)) != len(required):
            return f"{path}.required 不能包含重复参数"
        # JSON Schema 的 required 只能引用同层 properties 中已声明的字段。
        # 注册期拒绝拼写错误，避免执行期把永远无法满足的契约静默带入模型调用。
        declared = properties if isinstance(properties, Mapping) else {}
        missing = [name for name in required if name not in declared]
        if missing:
            return f"{path}.required 包含未声明字段：{', '.join(missing)}"

    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, bool):
        return f"{path}.additionalProperties 仅支持布尔值"

    enum = schema.get("enum")
    if enum is not None and not isinstance(enum, list | tuple):
        return f"{path}.enum 必须是数组"

    items = schema.get("items")
    if items is not None:
        if not isinstance(items, Mapping):
            return f"{path}.items 必须是 Schema 对象"
        error = _validate_schema_definition(items, f"{path}.items")
        if error:
            return error

    for key in ("minItems", "maxItems"):
        value = schema.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            return f"{path}.{key} 必须是非负整数"
    min_items = schema.get("minItems")
    max_items = schema.get("maxItems")
    if isinstance(min_items, int) and isinstance(max_items, int) and min_items > max_items:
        return f"{path}.minItems 不能大于 maxItems"

    for key in ("minLength", "maxLength"):
        value = schema.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            return f"{path}.{key} 必须是非负整数"
    min_length = schema.get("minLength")
    max_length = schema.get("maxLength")
    if isinstance(min_length, int) and isinstance(max_length, int) and min_length > max_length:
        return f"{path}.minLength 不能大于 maxLength"

    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            return f"{path}.pattern 必须是字符串"
        try:
            re.compile(pattern)
        except re.error:
            return f"{path}.pattern 不是有效正则表达式"

    for key in ("minimum", "maximum"):
        value = schema.get(key)
        if value is not None and (
            not isinstance(value, int | float) or isinstance(value, bool)
        ):
            return f"{path}.{key} 必须是数字"
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if (
        isinstance(minimum, int | float)
        and not isinstance(minimum, bool)
        and isinstance(maximum, int | float)
        and not isinstance(maximum, bool)
        and minimum > maximum
    ):
        return f"{path}.minimum 不能大于 maximum"
    return None


def validate_tool_arguments(schema: Mapping[str, object], arguments: Mapping[str, object]) -> str | None:
    """校验内部工具使用的受限 JSON Schema，失败返回脱敏中文原因。

    平台工具当前只需要 object/properties/required、基础标量类型、枚举和范围
    约束。校验器刻意不执行 schema 中的任意代码，也不支持远程 ``$ref``，从而
    保证模型参数只能在 ToolNode 的受控本地边界内被解释。
    """
    return _validate_schema_value(arguments, schema, "arguments")


def validate_tool_output(schema: Mapping[str, object], data: Mapping[str, object]) -> str | None:
    """按 ``output_schema`` 校验 handler 返回的展示投影，失败返回脱敏中文原因。

    与 ``validate_tool_arguments`` 共用同一受限子集校验器；不校验 ``latency_ms``
    等运行期注入字段，只比对 handler 声明的展示投影键。返回 ``None`` 表示通过。
    空 Schema（显式 ``{}``）视为「无结构化投影」，跳过比对。
    """
    if not schema:
        return None
    return _validate_schema_value(data, schema, "output")


def _validate_schema_value(value: object, schema: Mapping[str, object], path: str) -> str | None:
    """递归校验一个 JSON 值，覆盖内部短工具声明的安全子集。"""
    expected = schema.get("type")
    expected_types = (expected,) if isinstance(expected, str) else expected
    if isinstance(expected_types, list | tuple) and expected_types:
        if not any(_matches_json_type(value, str(item)) for item in expected_types):
            labels = "/".join(str(item) for item in expected_types)
            return f"参数 {path} 类型无效，应为 {labels}"

    enum = schema.get("enum")
    if isinstance(enum, list | tuple) and value not in enum:
        return f"参数 {path} 不在允许范围内"

    if isinstance(value, Mapping):
        required = required_parameter_names(schema)
        missing = [name for name in required if name not in value]
        if missing:
            return f"缺少必填参数：{', '.join(missing)}"
        properties = schema.get("properties")
        properties_map = properties if isinstance(properties, Mapping) else {}
        if schema.get("additionalProperties") is False:
            unexpected = [str(key) for key in value if key not in properties_map]
            if unexpected:
                return f"包含未允许的参数：{', '.join(unexpected)}"
        for key, child in value.items():
            child_schema = properties_map.get(key)
            if not isinstance(child_schema, Mapping):
                continue
            error = _validate_schema_value(child, child_schema, str(key))
            if error:
                return error

    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            return f"参数 {path} 元素数不能少于 {min_items}"
        if isinstance(max_items, int) and len(value) > max_items:
            return f"参数 {path} 元素数不能多于 {max_items}"
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, child in enumerate(value):
                error = _validate_schema_value(child, item_schema, f"{path}[{index}]")
                if error:
                    return error

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            return f"参数 {path} 长度不能小于 {min_length}"
        if isinstance(max_length, int) and len(value) > max_length:
            return f"参数 {path} 长度不能大于 {max_length}"
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and not re.search(pattern, value):
            return f"参数 {path} 格式无效"

    if isinstance(value, int | float) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int | float) and value < minimum:
            return f"参数 {path} 不能小于 {minimum}"
        if isinstance(maximum, int | float) and value > maximum:
            return f"参数 {path} 不能大于 {maximum}"
    return None


def _matches_json_type(value: object, expected: str) -> bool:
    """避免 Python ``bool`` 被误判为 JSON integer。"""
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)
