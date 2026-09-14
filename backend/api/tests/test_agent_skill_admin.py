"""Agent Skill 与 Prompt 管理接口的最小安全回归。"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.errors import AppError, ErrorCode
from app.harness.skills.storage import ensure_skill_files, read_skill_document
from app.main import app
from app.models import User
from app.routers.admin import AgentSkillUpdateIn, put_agent_skill


class _CommitFailureDb:
    """模拟审计事务提交失败，验证文件补偿恢复。"""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.rolled_back = False

    def add(self, item: object) -> None:
        self.added.append(item)

    def commit(self) -> None:
        raise RuntimeError("database unavailable")

    def rollback(self) -> None:
        self.rolled_back = True


def test_agent_skill_management_requires_authentication() -> None:
    """技能目录与文件预览不能在未登录状态下读取。"""
    client = TestClient(app)
    for path in ("/api/admin/skills", "/api/admin/skills/skill-benchmark"):
        response = client.get(path)
        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"


def test_agent_prompt_management_requires_authentication() -> None:
    """协议档提示词预览与保存都必须经过既有成员鉴权。"""
    client = TestClient(app)
    response = client.get("/api/admin/agent-prompts/profile-demo")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"

    response = client.put("/api/admin/agent-prompts/profile-demo", json={"overlay": "团队术语"})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_agent_expert_prompt_management_requires_authentication() -> None:
    """专家目录、提示词预览与保存均须通过既有成员鉴权。"""
    client = TestClient(app)
    for method, path, body in (
        ("get", "/api/admin/experts", None),
        ("get", "/api/admin/experts/testcase-agent/prompt", None),
        ("put", "/api/admin/experts/testcase-agent/prompt", {
            "content": "专家提示词", "expected_revision": "0" * 16,
        }),
    ):
        response = client.get(path) if method == "get" else client.put(path, json=body)
        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"


def test_agent_skill_audit_failure_restores_previous_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """审计提交失败时，必须恢复刚才被替换的 SKILL.md 原内容。"""
    monkeypatch.setenv("AGENT_SKILLS_ROOT", str(tmp_path / "skills"))
    ensure_skill_files()
    before = read_skill_document("skill-benchmark")
    updated = before.content.replace("执行大模型基准评测", "执行团队基准评测", 1)
    db = _CommitFailureDb()

    with pytest.raises(AppError) as error:
        put_agent_skill(
            "skill-benchmark",
            AgentSkillUpdateIn(content=updated, expected_revision=before.revision),
            SimpleNamespace(client=None),
            db,
            User(id="user-demo", username="demo", password_hash="masked"),
        )

    assert error.value.code == ErrorCode.INTERNAL
    assert "已恢复原内容" in error.value.message
    assert db.rolled_back is True
    assert read_skill_document("skill-benchmark").content == before.content
