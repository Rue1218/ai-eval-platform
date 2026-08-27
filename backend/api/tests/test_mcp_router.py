from app.models import User
from app.routers.mcp import get_tool_code, health_check, list_all_tools


def test_list_all_tools_returns_native_and_mcp():
    user = User(id="u-admin", username="admin", role="admin")
    res = list_all_tools(user=user)
    assert "items" in res
    assert len(res["items"]) >= 10
    read_tool = next(item for item in res["items"] if item["name"] == "read")
    assert "parameters_schema" in read_tool
    assert "output_schema" in read_tool
    assert "code_details" in read_tool
    assert read_tool["code_details"]["source_file"]

def test_health_check_returns_channel_statuses():
    user = User(id="u-admin", username="admin", role="admin")
    res = health_check(user=user)
    assert res["ok"] is True
    assert "native" in res["channels"]
    assert "internal_mcp" in res["channels"]
    assert "external_gateway" in res["channels"]

def test_get_tool_code_returns_source_and_snippet():
    user = User(id="u-admin", username="admin", role="admin")
    code_res = get_tool_code(tool_name="read", user=user)
    assert code_res["name"] == "read"
    assert "def _read_handler" in code_res["code_snippet"]

