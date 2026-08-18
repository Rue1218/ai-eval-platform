import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid_str() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=uuid_str)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="engineer")  # admin / engineer / readonly
    disabled = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=uuid_str)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=uuid_str)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class WsEvent(Base):
    __tablename__ = "ws_events"
    __table_args__ = (Index("ix_ws_events_session_event", "session_id", "event_id"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    event_id = Column(BigInteger, nullable=False)
    event = Column(String, nullable=False)
    payload = Column(JSONB, default=dict)
    ts = Column(DateTime(timezone=True), default=utcnow)


class ProtocolProfile(Base):
    __tablename__ = "protocol_profiles"

    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, nullable=False)
    protocol = Column(String, nullable=False)  # openai_chat / openai_responses / anthropic_messages
    base_url = Column(String, nullable=False)
    model = Column(String, nullable=False)
    encrypted_key = Column(Text, nullable=True)  # 只写不回显
    created_by = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, nullable=False)
    version = Column(Integer, default=1)
    row_count = Column(Integer, default=0)
    created_by = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=uuid_str)
    session_id = Column(String, nullable=True, index=True)
    parent_task_id = Column(String, nullable=True, index=True)
    kind = Column(String, nullable=False)  # benchmark / rag / testcase / stress
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


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=uuid_str)
    task_id = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False)
    metrics = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(JSONB, default=dict)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=True)
    action = Column(String, nullable=False)
    detail = Column(JSONB, default=dict)
    ts = Column(DateTime(timezone=True), default=utcnow)
