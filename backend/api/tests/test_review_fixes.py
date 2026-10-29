"""全项目审查修复的回归测试：只覆盖不依赖外部服务的纯逻辑。"""
import pytest

from app.errors import AppError
from app.harness.execution.dispatch import edit_file_safe
from app.llm.loop_contracts import classify_provider_error
from app.routers.admin import _url_origin
from app.routers.kb import _parse_gold_qa


class ReadTimeout(Exception):
    """模拟 httpx.ReadTimeout：流迭代阶段直接抛出，不是内置 OSError 子类。"""


class RemoteProtocolError(Exception):
    """模拟 httpx.RemoteProtocolError。"""


@pytest.mark.parametrize("error", [ReadTimeout("t"), RemoteProtocolError("p")])
def test_流式传输异常按可重试处理(error):
    result = classify_provider_error(error)
    assert result.retryable is True
    assert result.code == "provider_transport"


def test_overloaded_错误按可重试处理():
    error = RuntimeError("boom")
    error.body = {"error": {"type": "overloaded_error"}}  # type: ignore[attr-defined]
    result = classify_provider_error(error)
    assert result.retryable is True
    assert result.code == "provider_unavailable"


def test_无关异常仍不可重试():
    result = classify_provider_error(ValueError("bad request"))
    assert result.retryable is False


def test_edit_保留_crlf_换行(tmp_path):
    target = tmp_path / "a.txt"
    target.write_bytes(b"line1\r\nline2\r\nline3\r\n")
    edit_file_safe("a.txt", "line2", "LINE2", str(tmp_path))
    assert target.read_bytes() == b"line1\r\nLINE2\r\nline3\r\n"


def test_edit_跨行匹配_crlf_文件(tmp_path):
    target = tmp_path / "a.txt"
    target.write_bytes(b"a\r\nb\r\nc\r\n")
    edit_file_safe("a.txt", "a\nb", "x\ny", str(tmp_path))
    assert target.read_bytes() == b"x\r\ny\r\nc\r\n"


def test_edit_lf_文件保持_lf(tmp_path):
    target = tmp_path / "a.txt"
    target.write_bytes(b"a\nb\n")
    edit_file_safe("a.txt", "a", "z", str(tmp_path))
    assert target.read_bytes() == b"z\nb\n"


def test_黄金_qa_非法_json_返回校验错误而非_500():
    with pytest.raises(AppError) as info:
        _parse_gold_qa(b'[{"question": "x"', filename="qa.json")
    assert info.value.code.value == "VALIDATION"


def test_url_origin_区分域名且忽略大小写与路径():
    assert _url_origin("https://API.example.com/v1") == _url_origin("https://api.example.com/v2")
    assert _url_origin("https://evil.example.net/v1") != _url_origin("https://api.example.com/v1")
    assert _url_origin("") == ("", "")
