"""Worker 侧模型：从共享包 ``backend/shared/models.py``（单一事实源）导入。

历史上这里是 api 模型的手写最小副本，曾因漂移（Task.created_by 悬空外键）
在 flush 时抛 NoReferencedTableError 导致任务无法领取；现已统一为 re-export。
Worker 不执行 DDL，表结构由 api 侧 Alembic 迁移维护。
"""

from shared.models import (  # noqa: F401
    Base,
    CaseItem,
    CaseSet,
    Dataset,
    DatasetRow,
    EvalItem,
    MemoryKnowledge,
    PgVector,
    ProtocolProfile,
    Report,
    Session,
    Setting,
    StoredFile,
    Task,
    TaskEvent,
    UsageLedger,
    User,
    WsEvent,
    utcnow,
    uuid_str,
)
