"""Worker 侧最小模型副本。

与 backend/api/app/models.py 保持一致的三个表。骨架版为容器隔离而复制；
后续可抽成共享 package（如 ./shared）供 api / worker 共同引用，避免漂移。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=uuid_str)
    session_id = Column(String, nullable=True, index=True)
    parent_task_id = Column(String, nullable=True, index=True)
    kind = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued", index=True)
    config = Column(JSONB, default=dict)
    result = Column(JSONB, default=dict)
    report_id = Column(String, nullable=True)
    created_by = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class TaskEvent(Base):
    __tablename__ = "task_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    event = Column(String, nullable=False)
    payload = Column(JSONB, default=dict)
    ts = Column(DateTime(timezone=True), default=utcnow)


class WsEvent(Base):
    __tablename__ = "ws_events"
    __table_args__ = (Index("ix_ws_events_session_event", "session_id", "event_id"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    event_id = Column(BigInteger, nullable=False)
    event = Column(String, nullable=False)
    payload = Column(JSONB, default=dict)
    ts = Column(DateTime(timezone=True), default=utcnow)


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=uuid_str)
    task_id = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False)
    metrics = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
