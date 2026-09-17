"""/api/profiles/fetch-models 端点及 fetch_remote_models 统一适配单测。"""

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from app.adapters import fetch_remote_models


def test_fetch_remote_models_openai_format():
    """测试解析标准 OpenAI /v1/models 格式。"""
    mock_data = {
        "data": [
            {"id": "gpt-4o", "owned_by": "openai"},
            {"id": "mimo-v2.5-pro", "owned_by": "xiaomi"},
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("app.adapters.urlopen", return_value=mock_resp):
        models = fetch_remote_models(
            protocol="openai_chat",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        assert len(models) == 2
        assert models[0]["id"] == "gpt-4o"
        assert models[1]["id"] == "mimo-v2.5-pro"


def test_fetch_remote_models_preserves_cursorapi_parameters():
    """CursorAPI 模型目录的参数维度必须原样交给前端构造模型规格。"""
    mock_data = {
        "data": [
            {
                "id": "grok-4.6",
                "display_name": "Cursor Grok 4.6",
                "owned_by": "cursorapi",
                "parameters": [
                    {"id": "effort", "values": ["Low", "Medium", "High"]},
                    {"id": "fast", "values": ["false", "true"]},
                ],
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("app.adapters.urlopen", return_value=mock_resp):
        models = fetch_remote_models(
            protocol="openai_chat",
            base_url="https://cursorapi.example.com/v1",
            api_key="sk-test",
        )

    assert models == [
        {
            "id": "grok-4.6",
            "name": "Cursor Grok 4.6",
            "owned_by": "cursorapi",
            "parameters": [
                {"id": "effort", "values": ["Low", "Medium", "High"]},
                {"id": "fast", "values": ["false", "true"]},
            ],
        }
    ]


def test_fetch_remote_models_ollama_format():
    """测试解析 Ollama /api/tags 格式。"""
    mock_data = {
        "models": [
            {"name": "llama3:latest"},
            {"name": "qwen2.5:7b"},
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("app.adapters.urlopen", return_value=mock_resp):
        models = fetch_remote_models(
            protocol="openai_chat",
            base_url="http://localhost:11434",
        )
        assert len(models) == 2
        assert models[0]["id"] == "llama3:latest"
        assert models[1]["id"] == "qwen2.5:7b"


def test_fetch_remote_models_anthropic_format():
    """测试解析真实 Anthropic /v1/models 格式（含 display_name 与 id）。"""
    mock_data = {
        "data": [
            {
                "type": "model",
                "id": "claude-3-7-sonnet-20250219",
                "display_name": "Claude 3.7 Sonnet",
                "created_at": "2025-02-19T00:00:00Z",
            },
            {
                "type": "model",
                "id": "claude-3-5-haiku-20241022",
                "display_name": "Claude 3.5 Haiku",
                "created_at": "2024-10-22T00:00:00Z",
            },
        ],
        "has_more": False,
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("app.adapters.urlopen", return_value=mock_resp):
        models = fetch_remote_models(
            protocol="anthropic_messages",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test",
        )
        assert len(models) == 2
        assert models[0]["id"] == "claude-3-5-haiku-20241022"
        assert models[0]["name"] == "Claude 3.5 Haiku"
        assert models[0]["owned_by"] == "anthropic"
        assert models[1]["id"] == "claude-3-7-sonnet-20250219"
        assert models[1]["name"] == "Claude 3.7 Sonnet"
        assert models[1]["owned_by"] == "anthropic"


def test_fetch_remote_models_error_raising():
    """测试当端点网络或服务异常时抛出 AppError 而非假数据。"""
    import pytest

    from app.errors import AppError, ErrorCode

    with patch("app.adapters.urlopen", side_effect=Exception("connection refused")):
        with pytest.raises(AppError) as exc_info:
            fetch_remote_models(
                protocol="anthropic_messages",
                base_url="https://api.anthropic.com",
                api_key="sk-ant-test",
            )
        assert exc_info.value.code == ErrorCode.UPSTREAM


def test_service_base_url_suffix_stripping():
    """测试 _service_base_url 智能剥离 /v1/models、/models、/chat/completions 等后缀。"""
    from app.adapters import _service_base_url

    assert _service_base_url("https://api.anthropic.com/v1/models") == "https://api.anthropic.com"
    assert _service_base_url("https://api.anthropic.com/v1/models/") == "https://api.anthropic.com"
    assert _service_base_url("https://api.anthropic.com/models") == "https://api.anthropic.com"
    assert _service_base_url("https://api.anthropic.com/v1/messages") == "https://api.anthropic.com"
    assert _service_base_url("https://api.openai.com/v1/chat/completions") == "https://api.openai.com"
    assert _service_base_url("https://api.openai.com/v1/models") == "https://api.openai.com"
    assert _service_base_url("https://api.openai.com/v1") == "https://api.openai.com"
    assert _service_base_url("https://dashscope.aliyuncs.com/compatible-mode/v1") == "https://dashscope.aliyuncs.com/compatible-mode"
    # DeepSeek 官方 Anthropic 兼容端点：子路径必须保留，仅剥离端点级后缀
    assert _service_base_url("https://api.deepseek.com/anthropic") == "https://api.deepseek.com/anthropic"
    assert _service_base_url("https://api.deepseek.com/anthropic/v1/messages") == "https://api.deepseek.com/anthropic"


def test_anthropic_model_list_roots():
    """测试 Anthropic 子路径网关的宿主根候选推导（DeepSeek / 智谱形态）。"""
    from app.adapters import _anthropic_model_list_roots

    assert _anthropic_model_list_roots("https://api.deepseek.com/anthropic") == [
        "https://api.deepseek.com"
    ]
    assert _anthropic_model_list_roots("https://open.bigmodel.cn/api/anthropic") == [
        "https://open.bigmodel.cn/api",
        "https://open.bigmodel.cn",
    ]
    # 已是宿主根时不产生额外候选
    assert _anthropic_model_list_roots("https://api.anthropic.com") == []


def test_fetch_remote_models_deepseek_anthropic_subpath_fallback():
    """Anthropic 子路径无模型列表时，回退宿主根 /v1/models 获取（DeepSeek /anthropic 场景）。"""
    mock_data = {
        "data": [
            {"id": "deepseek-v4-pro", "owned_by": "deepseek"},
            {"id": "deepseek-v4-flash", "owned_by": "deepseek"},
        ]
    }
    seen: list[str] = []

    def fake_urlopen(req, timeout=None):
        seen.append(req.full_url)
        if "/anthropic" in req.full_url:
            raise HTTPError(url=req.full_url, code=404, msg="Not Found", hdrs={}, fp=None)
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("app.adapters.urlopen", side_effect=fake_urlopen):
        models = fetch_remote_models(
            protocol="anthropic_messages",
            base_url="https://api.deepseek.com/anthropic",
            api_key="sk-ds-test",
        )

    assert {m["id"] for m in models} == {"deepseek-v4-pro", "deepseek-v4-flash"}
    # 子路径候选失败后必须尝试宿主根
    assert any(url.endswith("/anthropic/v1/models") for url in seen)
    assert "https://api.deepseek.com/v1/models" in seen


def test_fetch_remote_models_404_not_found():
    """测试当端点返回 404 时抛出 NOT_FOUND 并附带友好提示。"""
    from urllib.error import HTTPError

    import pytest

    from app.errors import AppError, ErrorCode

    err = HTTPError(url="https://api.example.com/v1/models", code=404, msg="Not Found", hdrs={}, fp=None)
    with patch("app.adapters.urlopen", side_effect=err):
        with pytest.raises(AppError) as exc_info:
            fetch_remote_models(
                protocol="openai_chat",
                base_url="https://api.example.com/v1/models",
                api_key="sk-test",
            )
        assert exc_info.value.code == ErrorCode.NOT_FOUND
        assert "404" in exc_info.value.message


def test_resolve_env_api_key_for_url(tmp_path, monkeypatch):
    """测试根据 Base URL 与协议从 .env 解析 API Key。"""
    from app.profile_env import resolve_env_api_key_for_url, resolve_env_base_url

    env_file = tmp_path / ".env"
    env_file.write_text(
        'AI_PROFILE_MY_VENDOR_BASE_URL="https://my-vendor.example.com/v1"\n'
        'AI_PROFILE_MY_VENDOR_API_KEY="sk-vendor-12345"\n'
        'MIMO_API_KEY="mimo-token-abc"\n'
        'MIMO_BASE_URL="https://token-plan-cn.xiaomimimo.com"\n'
        'DEEPSEEK_API_KEY="deepseek-token-xyz"\n'
        'DEEPSEEK_BASE_URL="https://api.deepseek.com"\n'
        'OPENAI_BASE_URL="https://api.openai.com/v1"\n'
        'OPENAI_API_KEY="sk-openai-global"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("app.config.settings.profile_env_file", str(env_file))

    # 1. 匹配 profile Base URL
    key = resolve_env_api_key_for_url("https://my-vendor.example.com")
    assert key == "sk-vendor-12345"

    # 2. 匹配显式配置的 Xiaomi Mimo 端点，不再用域名子串猜测。
    key_mimo = resolve_env_api_key_for_url("https://token-plan-cn.xiaomimimo.com")
    assert key_mimo == "mimo-token-abc"

    # 3. 匹配显式配置的 DeepSeek 端点。
    key_ds = resolve_env_api_key_for_url("https://api.deepseek.com/v1")
    assert key_ds == "deepseek-token-xyz"

    # 4. 默认 Base URL
    base = resolve_env_base_url("openai_chat")
    assert base == "https://api.openai.com/v1"
