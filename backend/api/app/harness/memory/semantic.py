"""Harness 语义记忆占位（M3，MEM-5）。

pgvector + LightRAG 属演进项，未接入前 ``retrieve`` 直接抛
``AppError(VALIDATION)``；接入前 ``kind=rag`` 任务必须失败，**不得 mock
``succeeded``**（MEM-5 红线）。接入后显式带来源（source_id/版本），与
``acl.py`` 协作过滤。
"""

from __future__ import annotations

from app.errors import AppError, ErrorCode


def retrieve(query: str) -> list:
    """语义记忆检索占位：未接入，抛 AppError(VALIDATION)。"""
    raise AppError(ErrorCode.VALIDATION, "RAG 语义记忆未接入")
