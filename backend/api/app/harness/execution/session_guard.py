"""Harness 执行层：受控数据库 Session 守卫（M5 阶段 4，EX-6）。

执行器只在自己的 ``Session`` 内重新加载和提交 ORM 对象；本模块提供统一
上下文管理器与运行时断言，阻止把已绑定到其它 Session 的 ORM 实例跨层传递。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager

from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import UnmappedInstanceError

from app.db import SessionLocal
from app.errors import AppError, ErrorCode


@contextmanager
def with_managed_session() -> Iterator[object]:
    """创建、提交、回滚并关闭一个由执行器独立管理的数据库 Session。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def assert_no_orm_leak(obj: object) -> None:
    """断言对象及其常见容器成员不携带已绑定的 ORM Session。"""
    if obj is None:
        return
    try:
        bound_session = object_session(obj)
    except UnmappedInstanceError:
        bound_session = None
    if bound_session is not None:
        raise AppError(ErrorCode.INTERNAL, "禁止跨 Session 传递 ORM 对象")
    if isinstance(obj, Mapping):
        for value in obj.values():
            assert_no_orm_leak(value)
    elif isinstance(obj, Sequence) and not isinstance(obj, str | bytes | bytearray):
        for value in obj:
            assert_no_orm_leak(value)
