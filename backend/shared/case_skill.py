"""API、Worker 与对话工具共用的用例 Skill 分层加载器。"""

from pathlib import Path

SKILL_ID = "functional-test-design"
SKILL_VERSION = "1.0.0"
UPSTREAM_COMMIT = "8910672e674853caf0e68dbffc59c39869990203"
SKILL_ROOT = Path(__file__).with_name("case_skills") / SKILL_ID
RESOURCE_FILES = {
    "workflow": "SKILL.md",
    "design": "references/design.md",
    "cases": "references/cases.md",
    "inputs": "references/inputs.md",
    "flows": "references/flows.md",
    "review": "references/review.md",
}


def skill_metadata(skill_id: str = SKILL_ID) -> dict:
    """发现阶段只读到头部结束，不读取正文或任何参考文件。"""
    if skill_id != SKILL_ID:
        raise ValueError("未找到已安装的用例生成技能")
    fields = {}
    with (SKILL_ROOT / "SKILL.md").open(encoding="utf-8") as handle:
        if handle.readline().strip() != "---":
            raise ValueError("用例生成技能头部无效")
        size = 0
        for line in handle:
            size += len(line)
            if size > 4096:
                raise ValueError("用例生成技能头部超限")
            if line.strip() == "---":
                break
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
        else:
            raise ValueError("用例生成技能头部不完整")
    if not fields.get("description") or not fields.get("license"):
        raise ValueError("用例生成技能缺少描述或许可")
    return {
        "id": SKILL_ID, "name": "功能测试设计", "description": fields["description"],
        "version": SKILL_VERSION, "license": fields["license"],
        "source_url": f"https://github.com/jaktestowac/awesome-copilot-for-testers/tree/{UPSTREAM_COMMIT}/skills/designing-functional-tests",
    }


def read_skill_section(section: str, skill_id: str = SKILL_ID) -> dict:
    """只允许读取登记章节，模型不能传路径或读取任意服务器文件。"""
    metadata = skill_metadata(skill_id)
    if section == "catalog":
        return {"skills": [metadata]}
    if section not in RESOURCE_FILES:
        raise ValueError("未知的用例技能章节")
    path = SKILL_ROOT / RESOURCE_FILES[section]
    if not path.is_file():
        raise ValueError("用例技能资源缺失")
    content = path.read_text(encoding="utf-8")
    if section == "workflow":
        content = content.split("---", 2)[-1].strip()
    return {"skill": metadata, "section": section, "content": content}


def load_skill_context(stage: str, weights: dict[str, int] | None = None, skill_id: str = SKILL_ID) -> tuple[str, list[str]]:
    """按当前阶段与已选策略披露资源，不提前加载其他阶段或策略细节。"""
    if stage not in {"design", "cases", "review"}:
        raise ValueError("未知的用例生成阶段")
    sections = ["workflow", stage]
    if stage == "cases":
        selected = weights or {}
        if selected.get("boundary", 0) or selected.get("equivalence", 0):
            sections.append("inputs")
        if selected.get("state", 0) or selected.get("scenario", 0):
            sections.append("flows")
    texts = [read_skill_section(section, skill_id)["content"] for section in sections]
    return "\n\n".join(texts), sections
