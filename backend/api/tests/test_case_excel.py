"""Excel 用例导入解析纯函数单测（不依赖数据库）。"""

from io import BytesIO

import pytest
from openpyxl import Workbook

from app.case_excel import (
    IMPORT_MAX_ROWS,
    build_import_template,
    parse_cases_xlsx,
)
from app.errors import AppError, ErrorCode


def _xlsx_from_rows(rows: list[list[object]], title: str = "用例集") -> bytes:
    """把二维表写成 xlsx 字节，供解析单测使用。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_parse_platform_export_headers():
    # 平台导出列（含用例编号）应按 platform 格式导入，并保留 id
    raw = _xlsx_from_rows(
        [
            ["用例编号", "策略", "优先级", "模块", "用例名称", "前置条件", "步骤", "预期结果", "测试类型", "已映射", "待补全"],
            ["c-1", "正向", "P0", "登录", "账密正确登录", "账号正常", "输入账密", "进入工作台", "核心业务", "是", "否"],
        ]
    )
    cases, fmt, skipped = parse_cases_xlsx(raw)
    assert fmt == "platform"
    assert skipped == 0
    assert len(cases) == 1
    assert cases[0]["id"] == "c-1"
    assert cases[0]["name"] == "账密正确登录"
    assert cases[0]["strategy"] == "正向"
    assert cases[0]["expected"] == "进入工作台"
    assert "mapped" not in cases[0]


def test_parse_standard_testcase_tools_headers():
    # testcase-tools 标准列：用例标题 / 测试步骤 / 用例类型
    raw = _xlsx_from_rows(
        [
            ["用例编号", "所属模块", "用例标题", "优先级", "用例类型", "前置条件", "测试步骤", "预期结果"],
            ["TC-001", "认证模块", "管理员登录成功", "P0", "功能测试", "存在 admin", "POST /login", "HTTP 200"],
        ]
    )
    cases, fmt, skipped = parse_cases_xlsx(raw)
    assert fmt == "standard"
    assert skipped == 0
    assert cases[0]["module"] == "认证模块"
    assert cases[0]["name"] == "管理员登录成功"
    assert cases[0]["steps"] == "POST /login"
    assert cases[0]["test_type"] == "功能测试"
    assert cases[0]["strategy"] == "正向"


def test_parse_simple_module_name_steps_expected():
    # PRD 简化列：模块 / 名称 / 步骤 / 预期；缺策略默认正向、缺优先级默认 FHX
    raw = _xlsx_from_rows(
        [
            ["模块", "名称", "步骤", "预期"],
            ["支付", "余额支付成功", "选择余额并确认", "订单核销成功"],
        ]
    )
    cases, fmt, skipped = parse_cases_xlsx(raw)
    assert fmt == "simple"
    assert skipped == 0
    assert cases[0]["module"] == "支付"
    assert cases[0]["name"] == "余额支付成功"
    assert cases[0]["steps"] == "选择余额并确认"
    assert cases[0]["expected"] == "订单核销成功"
    assert cases[0]["strategy"] == "正向"
    assert cases[0]["priority"] == "FHX"


def test_parse_header_not_on_first_row_and_skip_empty_name():
    # 允许首行写标题；无名称的数据行计入 skipped
    raw = _xlsx_from_rows(
        [
            ["支付模块回归用例"],
            ["模块", "用例名称", "步骤", "预期结果"],
            ["登录", "", "无名称应跳过", "—"],
            ["登录", "验证码登录", "输入验证码", "登录成功"],
        ]
    )
    cases, fmt, skipped = parse_cases_xlsx(raw)
    assert fmt == "simple"
    assert skipped == 1
    assert [item["name"] for item in cases] == ["验证码登录"]


def test_parse_strategy_and_priority_aliases():
    raw = _xlsx_from_rows(
        [
            ["策略", "优先级", "用例名称"],
            ["等价", "高", "金额分档"],
            ["状态迁移", "中", "订单流转"],
            ["negative", "2", "密码错误"],
        ]
    )
    cases, fmt, _skipped = parse_cases_xlsx(raw)
    assert fmt == "platform"
    assert cases[0]["strategy"] == "等价类" and cases[0]["priority"] == "HX"
    assert cases[1]["strategy"] == "状态迁移" and cases[1]["priority"] == "FHX"
    assert cases[2]["strategy"] == "反向" and cases[2]["priority"] == "FHX"


def test_parse_extra_columns_go_to_extras():
    raw = _xlsx_from_rows(
        [
            ["用例名称", "模块", "负责人"],
            ["账密登录", "登录", "张三"],
        ]
    )
    cases, _fmt, _skipped = parse_cases_xlsx(raw)
    assert cases[0]["extras"]["负责人"] == "张三"


def test_parse_rejects_unknown_workbook():
    with pytest.raises(AppError) as exc:
        parse_cases_xlsx(b"not-an-xlsx")
    assert exc.value.code == ErrorCode.VALIDATION


def test_parse_rejects_missing_header():
    raw = _xlsx_from_rows([["随便", "写点"], ["1", "2"]])
    with pytest.raises(AppError) as exc:
        parse_cases_xlsx(raw)
    assert "未识别到用例表头" in exc.value.message


def test_template_round_trip():
    # 模板含示例行，解析后至少得到一条可导入用例
    cases, fmt, skipped = parse_cases_xlsx(build_import_template())
    assert fmt == "platform"
    assert skipped == 0
    assert cases[0]["name"] == "账密正确登录"
    assert cases[0]["strategy"] == "正向"


def test_import_max_rows_constant():
    # 规模闸门保持与实现一致，防止误改成生成上限 80
    assert IMPORT_MAX_ROWS == 2000
