"""协议档环境文件 CRUD、原子回滚和多供应商变量隔离测试。"""

from pathlib import Path

from app.config import settings
from app.profile_env import (
    read_global_llm_env,
    read_media_mcp_env,
    read_profile_env,
    remove_profile_env,
    restore_snapshot,
    write_media_mcp_env,
    write_profile_env,
)


def test_profile_env_write_without_fchmod(tmp_path: Path, monkeypatch):
    """Windows 3.12 缺少 fd chmod 时仍能保存并读取真实协议档配置。"""
    from app import profile_env

    monkeypatch.delattr(profile_env.os, "fchmod", raising=False)
    monkeypatch.setattr(settings, "profile_env_file", str(tmp_path / ".env"))
    write_profile_env("windows-test", base_url="https://example.com/v1",
                      model="test-model", api_key="test-only-key")
    actual = read_profile_env("windows-test")
    assert actual.model == "test-model" and actual.api_key == "test-only-key"


def test_profile_env_supports_multiple_profiles_without_key_collision(tmp_path: Path, monkeypatch):
    """不同供应商协议档写入独立变量，Key 中的特殊字符不破坏 dotenv。"""
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET_KEY=server-secret\n", encoding="utf-8")
    monkeypatch.setattr(settings, "profile_env_file", str(env_file))

    write_profile_env(
        "openai-profile",
        base_url="https://api.openai.com/v1",
        model="gpt-4.1",
        api_key="sk-a#b=c",
        embedding_base_url="https://embed.example.com/v1",
        embedding_model="text-embedding-3-large",
        embedding_api_key="embed#key",
        reranker_base_url="https://rerank.example.com/v1",
        reranker_model="bge-reranker-v2-m3",
        reranker_api_key="rerank=key",
        protocol="openai_chat",
        write_global_aliases=True,
    )
    write_profile_env(
        "anthropic-profile",
        base_url="https://api.anthropic.com",
        model="claude-sonnet-4",
        api_key="sk-ant-xyz",
        protocol="anthropic_messages",
        write_global_aliases=False,
    )

    assert read_profile_env("openai-profile").api_key == "sk-a#b=c"
    openai_values = read_profile_env("openai-profile")
    assert openai_values.embedding_base_url == "https://embed.example.com/v1"
    assert openai_values.embedding_model == "text-embedding-3-large"
    assert openai_values.embedding_api_key == "embed#key"
    assert openai_values.reranker_base_url == "https://rerank.example.com/v1"
    assert openai_values.reranker_model == "bge-reranker-v2-m3"
    assert openai_values.reranker_api_key == "rerank=key"
    write_profile_env("openai-profile", model="gpt-4.1-mini")
    preserved_values = read_profile_env("openai-profile")
    assert preserved_values.model == "gpt-4.1-mini"
    assert preserved_values.embedding_model == "text-embedding-3-large"
    assert preserved_values.reranker_model == "bge-reranker-v2-m3"
    assert read_profile_env("anthropic-profile").model == "claude-sonnet-4"
    assert read_global_llm_env().model == "gpt-4.1"
    assert "SECRET_KEY=server-secret" in env_file.read_text(encoding="utf-8")


def test_profile_env_delete_and_restore(tmp_path: Path, monkeypatch):
    """删除协议档变量后可恢复快照，确保数据库事务失败不会留下半套配置。"""
    env_file = tmp_path / ".env"
    monkeypatch.setattr(settings, "profile_env_file", str(env_file))
    write_profile_env(
        "p-1",
        base_url="https://example.test",
        model="m-1",
        api_key="k-1",
        embedding_base_url="https://embed.example.test",
        embedding_model="embed-1",
        embedding_api_key="embed-key",
        reranker_base_url="https://rerank.example.test",
        reranker_model="rerank-1",
        reranker_api_key="rerank-key",
    )

    snapshot = remove_profile_env("p-1")
    assert read_profile_env("p-1").base_url is None
    assert read_profile_env("p-1").embedding_model is None
    assert read_profile_env("p-1").reranker_model is None
    restore_snapshot(snapshot)
    restored = read_profile_env("p-1")
    assert restored.base_url == "https://example.test"
    assert restored.model == "m-1"
    assert restored.api_key == "k-1"
    assert restored.embedding_model == "embed-1"
    assert restored.reranker_model == "rerank-1"
    assert restored.reranker_api_key == "rerank-key"


def test_global_rag_env_write_and_fallback(tmp_path: Path, monkeypatch):
    """测试系统全局唯一的 Embedding 与 Reranker 模型写入及 profile 自动 fallback。"""
    from app.profile_env import read_global_rag_env, write_global_rag_env

    env_file = tmp_path / ".env"
    monkeypatch.setattr(settings, "profile_env_file", str(env_file))

    write_global_rag_env(
        embedding_base_url="https://api.siliconflow.cn/v1",
        embedding_model="BAAI/bge-large-zh-v1.5",
        embedding_api_key="sk-embed-global",
        reranker_base_url="https://api.siliconflow.cn/v1",
        reranker_model="BAAI/bge-reranker-v2-m3",
        reranker_api_key="sk-rerank-global",
    )

    rag_values = read_global_rag_env()
    assert rag_values.embedding_base_url == "https://api.siliconflow.cn/v1"
    assert rag_values.embedding_model == "BAAI/bge-large-zh-v1.5"
    assert rag_values.embedding_api_key == "sk-embed-global"
    assert rag_values.reranker_base_url == "https://api.siliconflow.cn/v1"
    assert rag_values.reranker_model == "BAAI/bge-reranker-v2-m3"
    assert rag_values.reranker_api_key == "sk-rerank-global"

    # 未单独配置 embedding/reranker 的 profile 应自动回退至全局 RAG 配置
    write_profile_env("only-llm", base_url="https://api.openai.com/v1", model="gpt-4o")
    profile_val = read_profile_env("only-llm")
    assert profile_val.base_url == "https://api.openai.com/v1"
    assert profile_val.embedding_model == "BAAI/bge-large-zh-v1.5"
    assert profile_val.reranker_model == "BAAI/bge-reranker-v2-m3"


def test_media_mcp_env_preserves_key_when_only_switching_models(tmp_path: Path, monkeypatch):
    """媒体模型编辑不清除已保存的 Key，读取投影只提供配置事实。"""
    monkeypatch.setattr(settings, "profile_env_file", str(tmp_path / ".env"))
    write_media_mcp_env(
        enabled=True,
        compatible_base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        api_key="test-media-key",
        image_model="qwen-image-3.0-pro",
        video_model="happyhorse-1.1-i2v",
        request_timeout_s=180,
    )
    write_media_mcp_env(image_model="qwen-image-next")

    values = read_media_mcp_env()
    assert values.enabled is True
    assert values.api_key == "test-media-key"
    assert values.image_model == "qwen-image-next"
    assert values.video_model == "happyhorse-1.1-i2v"
    assert values.request_timeout_s == 180
