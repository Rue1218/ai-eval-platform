"""技能文件存储：统一 ``skills/<skill_id>/SKILL.md`` 规格与按需读取。

技能目录只读取固定大小的 YAML 风格头部以生成 Hint；模型选中某技能后才读取
完整工作流正文。运行环境可通过 ``AGENT_SKILLS_ROOT`` 把可编辑副本放到
``/data/skills``，避免修改镜像内的代码文件后在重建时丢失。
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final

from app.errors import AppError, ErrorCode
from app.harness.prompts.system import assert_no_secret_leak

SKILL_FILENAME: Final[str] = "SKILL.md"
HEADER_READ_LIMIT: Final[int] = 8192
SKILL_IDS: Final[tuple[str, ...]] = (
    "skill-benchmark",
    "skill-testcase",
    "skill-rag",
    "skill-stress",
)
SKILL_KINDS: Final[dict[str, str]] = {
    "skill-benchmark": "benchmark",
    "skill-testcase": "testcase",
    "skill-rag": "rag",
    "skill-stress": "stress",
}
RUNTIME_DISABLED_SKILLS: Final[frozenset[str]] = frozenset({"skill-rag"})
_SKILL_ID_RE: Final[re.Pattern[str]] = re.compile(r"^skill-[a-z0-9-]{1,56}$")
_REQUIRED_HEADER_KEYS: Final[frozenset[str]] = frozenset(
    {"id", "name", "kind", "version", "enabled", "summary"}
)


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    """SKILL.md 头部的轻量目录信息，不包含工作流正文。"""

    skill_id: str
    name: str
    kind: str
    version: str
    enabled: bool
    summary: str


@dataclass(frozen=True, slots=True)
class SkillDocument:
    """供管理页预览的完整技能文件与乐观并发修订标识。"""

    metadata: SkillMetadata
    content: str
    revision: str


def _template_root() -> Path:
    """返回随应用发布的默认技能模板目录。"""
    return Path(__file__).resolve().with_name("files")


def get_skills_root() -> Path:
    """返回运行时技能目录；容器优先使用数据卷中的持久化副本。"""
    configured = os.getenv("AGENT_SKILLS_ROOT", "").strip()
    return Path(configured).resolve() if configured else _template_root()


def _validate_skill_id(skill_id: str) -> str:
    """校验技能 ID，阻断路径穿越及未登记技能的文件访问。"""
    normalized = str(skill_id or "").strip()
    if not _SKILL_ID_RE.fullmatch(normalized) or normalized not in SKILL_KINDS:
        raise AppError(ErrorCode.NOT_FOUND, "技能文件不存在")
    return normalized


def skill_path(skill_id: str) -> Path:
    """返回一个已校验 ID 的运行时 SKILL.md 路径，不创建文件。"""
    return get_skills_root() / _validate_skill_id(skill_id) / SKILL_FILENAME


def ensure_skill_files() -> None:
    """首次启动把内置模板复制到持久化 skills 目录；已有文件绝不覆盖。"""
    target_root = get_skills_root()
    template_root = _template_root()
    for skill_id in SKILL_IDS:
        target = target_root / skill_id / SKILL_FILENAME
        if target.is_file():
            continue
        source = template_root / skill_id / SKILL_FILENAME
        if not source.is_file():
            raise RuntimeError(f"内置技能模板缺失：{skill_id}")
        if target.resolve() == source.resolve():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        os.chmod(target, 0o600)


def skill_file_exists(skill_id: str) -> bool:
    """检查统一技能文件是否存在；调用方据此决定是否可以继续加载。"""
    return skill_path(skill_id).is_file()


def _parse_header(header: str, *, expected_skill_id: str) -> SkillMetadata:
    """解析固定六码头部；不引入通用 YAML 解释器以减少可执行语义。"""
    assert_no_secret_leak(header)
    if not header.startswith("---\n"):
        raise AppError(ErrorCode.VALIDATION, "技能文件头部必须以 --- 开始")
    end = header.find("\n---\n", 4)
    if end < 0:
        raise AppError(ErrorCode.VALIDATION, "技能文件头部不完整或超过读取上限")
    values: dict[str, str] = {}
    for raw_line in header[4:end].splitlines():
        if not raw_line or ":" not in raw_line:
            raise AppError(ErrorCode.VALIDATION, "技能文件头部格式无效")
        key, value = raw_line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key in values or key not in _REQUIRED_HEADER_KEYS or not value:
            raise AppError(ErrorCode.VALIDATION, "技能文件头部字段无效")
        values[key] = value
    if set(values) != _REQUIRED_HEADER_KEYS:
        raise AppError(ErrorCode.VALIDATION, "技能文件头部字段不完整")
    if values["id"] != expected_skill_id:
        raise AppError(ErrorCode.VALIDATION, "技能文件 ID 与目录不一致")
    if values["kind"] != SKILL_KINDS[expected_skill_id]:
        raise AppError(ErrorCode.VALIDATION, "技能文件 kind 与平台任务类型不一致")
    if values["enabled"] not in {"true", "false"}:
        raise AppError(ErrorCode.VALIDATION, "技能文件 enabled 必须为 true 或 false")
    enabled = values["enabled"] == "true"
    if enabled == (expected_skill_id in RUNTIME_DISABLED_SKILLS):
        raise AppError(ErrorCode.VALIDATION, "技能文件启用状态与平台能力状态不一致")
    if len(values["name"]) > 64 or len(values["summary"]) > 240 or len(values["version"]) > 32:
        raise AppError(ErrorCode.VALIDATION, "技能文件头部字段长度超限")
    return SkillMetadata(
        skill_id=expected_skill_id,
        name=values["name"],
        kind=values["kind"],
        version=values["version"],
        enabled=enabled,
        summary=values["summary"],
    )


def _split_document(content: str, *, skill_id: str) -> tuple[SkillMetadata, str]:
    """验证完整文件并分离元数据与工作流正文。"""
    assert_no_secret_leak(content)
    marker = "\n---\n"
    end = content.find(marker, 4)
    if end < 0:
        raise AppError(ErrorCode.VALIDATION, "技能文件头部不完整")
    metadata = _parse_header(content[: end + len(marker)], expected_skill_id=skill_id)
    workflow = content[end + len(marker) :].strip()
    if not workflow.startswith("## 工作流"):
        raise AppError(ErrorCode.VALIDATION, "技能文件正文必须以“## 工作流”开始")
    if len(workflow) > 20000:
        raise AppError(ErrorCode.VALIDATION, "技能文件正文超过 20000 字符上限")
    return metadata, workflow


def read_skill_metadata(skill_id: str) -> SkillMetadata:
    """先验证文件存在，再仅读取头部生成技能 Hint。"""
    target = skill_path(skill_id)
    if not target.is_file():
        raise AppError(ErrorCode.NOT_FOUND, "技能文件不存在")
    with target.open("r", encoding="utf-8") as handle:
        header = handle.read(HEADER_READ_LIMIT)
    return _parse_header(header, expected_skill_id=_validate_skill_id(skill_id))


def list_skill_metadata() -> list[SkillMetadata]:
    """列出已登记技能的轻量目录；不会读取任一技能的工作流正文。"""
    return [read_skill_metadata(skill_id) for skill_id in SKILL_IDS]


def read_skill_document(skill_id: str) -> SkillDocument:
    """读取单个完整技能文件，供管理预览或选中技能的按需工作流加载。"""
    target = skill_path(skill_id)
    if not target.is_file():
        raise AppError(ErrorCode.NOT_FOUND, "技能文件不存在")
    content = target.read_text(encoding="utf-8")
    metadata, _workflow = _split_document(content, skill_id=_validate_skill_id(skill_id))
    return SkillDocument(
        metadata=metadata,
        content=content,
        revision=sha256(content.encode("utf-8")).hexdigest()[:16],
    )


def load_skill_workflow_file(skill_id: str) -> str:
    """选中技能后才读取完整正文，实现工作流的渐进式披露。"""
    document = read_skill_document(skill_id)
    _metadata, workflow = _split_document(document.content, skill_id=document.metadata.skill_id)
    return workflow


def _write_skill_document(target: Path, content: str) -> None:
    """以临时文件替换单个技能文件，避免半写入内容被 Agent 读取。"""
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, target)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _normalize_skill_document(skill_id: str, content: str) -> str:
    """规范化并校验完整技能文件，禁止保存或加载疑似凭据。"""
    normalized = content.replace("\r\n", "\n").strip() + "\n"
    _metadata, _workflow = _split_document(normalized, skill_id=_validate_skill_id(skill_id))
    return normalized


def update_skill_document(skill_id: str, content: str, expected_revision: str) -> SkillDocument:
    """以修订指纹保护并原子写入单个 SKILL.md，禁止跨技能覆盖。"""
    current = read_skill_document(skill_id)
    if expected_revision != current.revision:
        raise AppError(ErrorCode.CONCURRENCY, "技能文件已被其他修改覆盖，请重新预览后再保存")
    normalized = _normalize_skill_document(skill_id, content)
    _write_skill_document(skill_path(skill_id), normalized)
    return read_skill_document(skill_id)


def restore_skill_document(skill_id: str, content: str, expected_revision: str) -> SkillDocument:
    """仅当本次写入仍是最新修订时恢复旧文件，供审计失败补偿使用。"""
    current = read_skill_document(skill_id)
    if current.revision != expected_revision:
        raise AppError(ErrorCode.CONCURRENCY, "技能文件已被其他修改覆盖，无法自动恢复")
    normalized = _normalize_skill_document(skill_id, content)
    _write_skill_document(skill_path(skill_id), normalized)
    return read_skill_document(skill_id)
