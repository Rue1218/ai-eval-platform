"""API 侧模型：从共享包 ``backend/shared/models.py``（单一事实源）导入。

api 与 worker 共用同一份模型定义，消除双副本漂移；
表结构演进：改 shared/models.py -> alembic autogenerate -> 同 commit 部署。
"""

from shared.models import (  # noqa: F401
    AuditLog,
    Base,
    CaseFolder,
    CaseItem,
    CaseSet,
    Dataset,
    DatasetFolder,
    DatasetRow,
    DispatchEvent,
    DispatchWorker,
    EvalItem,
    Message,
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
