"""Harness 冻结常量：确认卡默认值、槽位、短工具名单、窗口与预算。"""

from __future__ import annotations

from copy import deepcopy

from .long_tasks import LONG_MCP_TOOLS

# 确认卡数字默认值对齐 PRD 5.2.2 与 API.md TaskSpec
DEFAULT_RUN: dict = {
    "sample_size": 1000,
    "concurrency": 4,
    "timeout_s": 60,
    "retry": 1,
    "temperature": 0,
    "max_tokens": 1024,
    "system_prompt": "",
    "k": 5,
    "use_judge": False,
}

DEFAULT_STRESS: dict = {
    "env": "test",
    "qps": 10,
    "duration_s": 120,
    "sla_p99_ms": None,
}

# 确认卡字段键名集合（规划 slots 只允许这些键）
CONFIRM_SLOT_KEYS = frozenset(
    {
        "kind",
        "profile_ids",
        "dataset_id",
        "kb_id",
        "gold_qa_id",
        "rag_mode",
        "run",
        "with_stress",
        "stress",
        "case_source",
        "parent_task_id",
        "session_id",
    }
)

INTENT_ENUM = frozenset(
    {
        "benchmark",
        "rag",
        "testcase",
        "report",
        "cancel",
        "rerun",
        "inspect",
        "compact",
        "chat",
    }
)

SKILL_ID_ENUM = frozenset(
    {"skill-benchmark", "skill-rag", "skill-testcase", "skill-stress"}
)

DELIVERY_ENUM = frozenset({"confirm", "clarify", "text", "action"})

# 短工具清单与 mcp_tools / MCP 路由同源（名称冻结）
SHORT_TOOLS = frozenset(
    {
        "model.list",
        "task.get",
        "task.create",
        "task.cancel",
        "dispatch.overview",
        "dataset.list",
        "report.get",
        "kb.list",
        "testcase.confirm",
        "audio.voiceclone",
        "image.generate",
    }
)

WRITE_TOOLS = frozenset({"task.create", "task.cancel"})
READONLY_LIST_TOOLS = frozenset(
    {"model.list", "dataset.list", "kb.list", "task.get", "report.get", "dispatch.overview"}
)

TOOL_TITLES: dict[str, str] = {
    "model.list": "列出协议档",
    "dataset.list": "列出数据集",
    "kb.list": "列出知识库",
    "task.get": "查询任务",
    "report.get": "读取报告",
    "task.create": "创建任务",
    "task.cancel": "取消任务",
    "dispatch.overview": "调度概览",
    "testcase.confirm": "确认用例入库",
    "audio.voiceclone": "音色克隆配音",
    "image.generate": "Qwen Image 生图",
}

# 各 kind 必填槽位（G2）；with_stress 另要求 stress 段
REQUIRED_SLOTS: dict[str, tuple[str, ...]] = {
    "benchmark": ("profile_ids", "dataset_id"),
    "rag": ("kb_id", "gold_qa_id"),
    "testcase": ("case_source",),
}

DEFAULT_TOOLS_BY_INTENT: dict[str, list[str]] = {
    "benchmark": ["model.list", "dataset.list"],
    "rag": ["kb.list"],
    "inspect": [],
    "chat": [],
    "compact": [],
    "cancel": ["task.get"],
    "rerun": ["task.get"],
    "report": ["report.get"],
    "testcase": [],
}

# 模型调用预算（HAR-INT-02）：规划1 + 重试1 + 补规划1 + 复核核对1
MAX_MODEL_CALLS = 4
DEFAULT_TOOL_ROUNDS = 4
HARD_MAX_TOOL_ROUNDS = 5
TURN_WALL_CLOCK_S = 180.0
MODEL_TIMEOUT_S = 30.0

# 上下文窗口
WINDOW = 20
KEEP_RECENT = 6
SUMMARY_MAX_CHARS = 2000
COMPACT_INPUT_MAX = 12000

# 观察摘要
LIST_SUMMARY_LIMIT = 20
OBSERVATION_JSON_MAX = 4000

# 会话非终态（占槽）
ACTIVE_STATUSES = frozenset({"queued", "running", "awaiting_case_confirm"})
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})

# 只读工具并行开关：预留，M1 默认关
PARALLEL_READONLY_TOOLS = False

# 不改会话标题的控制命令
NO_TITLE_COMMANDS = frozenset({"compact", "help", "stop"})


def default_run() -> dict:
    """返回评测运行参数默认值的深拷贝。"""
    return deepcopy(DEFAULT_RUN)


def default_stress() -> dict:
    """返回压测参数默认值的深拷贝。"""
    return deepcopy(DEFAULT_STRESS)


def is_long_tool(name: str) -> bool:
    """是否为 Worker 专用长工具。"""
    return (name or "").strip() in LONG_MCP_TOOLS
