"""协议档环境文件 CRUD、原子回滚和多供应商变量隔离测试。"""

from pathlib import Path

from app.config import settings
from app.profile_env import (
    read_global_llm_env,
    read_profile_env,
    remove_profile_env,
    restore_snapshot,
    write_profile_env,
)


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
    assert read_profile_env("anthropic-profile").model == "claude-sonnet-4"
    assert read_global_llm_env().model == "gpt-4.1"
    assert "SECRET_KEY=server-secret" in env_file.read_text(encoding="utf-8")


def test_profile_env_delete_and_restore(tmp_path: Path, monkeypatch):
    """删除协议档变量后可恢复快照，确保数据库事务失败不会留下半套配置。"""
    env_file = tmp_path / ".env"
    monkeypatch.setattr(settings, "profile_env_file", str(env_file))
    write_profile_env("p-1", base_url="https://example.test", model="m-1", api_key="k-1")

    snapshot = remove_profile_env("p-1")
    assert read_profile_env("p-1").base_url is None
    restore_snapshot(snapshot)
    restored = read_profile_env("p-1")
    assert restored.base_url == "https://example.test"
    assert restored.model == "m-1"
    assert restored.api_key == "k-1"
