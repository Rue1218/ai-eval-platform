"""/api/profiles/fetch-models 端点及 fetch_remote_models 统一适配单测。"""

import json
from unittest.mock import MagicMock, patch

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


def test_fetch_remote_models_anthropic_preset_fallback():
    """测试 Anthropic 协议兜底返回主流 Claude 家族模型列表。"""
    with patch("app.adapters.urlopen", side_effect=Exception("not found")):
        models = fetch_remote_models(
            protocol="anthropic_messages",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test",
        )
        assert len(models) >= 3
        ids = [m["id"] for m in models]
        assert "claude-3-7-sonnet-20250219" in ids


def test_resolve_env_api_key_for_url(tmp_path, monkeypatch):
    """测试根据 Base URL 与协议从 .env 解析 API Key。"""
    from app.profile_env import resolve_env_api_key_for_url, resolve_env_base_url

    env_file = tmp_path / ".env"
    env_file.write_text(
        'AI_PROFILE_MY_VENDOR_BASE_URL="https://my-vendor.example.com/v1"\n'
        'AI_PROFILE_MY_VENDOR_API_KEY="sk-vendor-12345"\n'
        'MIMO_API_KEY="mimo-token-abc"\n'
        'DEEPSEEK_API_KEY="deepseek-token-xyz"\n'
        'OPENAI_BASE_URL="https://api.openai.com/v1"\n'
        'OPENAI_API_KEY="sk-openai-global"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("app.config.settings.profile_env_file", str(env_file))

    # 1. 匹配 profile Base URL
    key = resolve_env_api_key_for_url("https://my-vendor.example.com")
    assert key == "sk-vendor-12345"

    # 2. 匹配 Xiaomi Mimo 域名特征
    key_mimo = resolve_env_api_key_for_url("https://token-plan-cn.xiaomimimo.com")
    assert key_mimo == "mimo-token-abc"

    # 3. 匹配 DeepSeek 域名特征
    key_ds = resolve_env_api_key_for_url("https://api.deepseek.com/v1")
    assert key_ds == "deepseek-token-xyz"

    # 4. 默认 Base URL
    base = resolve_env_base_url("openai_chat")
    assert base == "https://api.openai.com/v1"

