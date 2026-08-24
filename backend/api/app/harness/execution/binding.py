"""Harness 执行层：附件参数绑定（M5 阶段 2，EX-2）。

``bind_attachments`` 校验参数中的 ``file_id`` 归属当前用户，返回绑定后的
安全参数字典；无 file_id 时不额外限制。DB 查询以 duck typing 方式解耦
（可注入夹具），资产溯源门禁同源（M6 rules.py 第 6 类）。
"""

from __future__ import annotations

from collections.abc import Mapping

from app.errors import AppError, ErrorCode


def bind_attachments(
    call_args: Mapping[str, object],
    db: object | None,
    user_id: str,
) -> dict[str, object]:
    """校验附件归属并返回安全参数字典（EX-2）。

    - ``file_id`` 存在且不归属当前用户 → AppError(VALIDATION)；
    - 附件记录不存在 → AppError(VALIDATION)；
    - db 为 None 时不查库（供纯单元测试），仍透传参数。
    """
    file_id = call_args.get("file_id")
    if file_id is None or db is None:
        return dict(call_args)
    from app.models import StoredFile

    row = (
        db.query(StoredFile)
        .filter(StoredFile.id == str(file_id), StoredFile.uploaded_by == user_id)
        .first()
    )
    if row is None:
        raise AppError(ErrorCode.VALIDATION, "附件不存在或不属于当前用户")
    return dict(call_args)
