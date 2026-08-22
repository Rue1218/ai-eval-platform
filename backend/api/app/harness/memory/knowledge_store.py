"""知识记忆公开实现入口；具体 SQL 保持在 pgvector 适配器内。"""

from .long_term_pgvector import PgvectorKnowledgeMemoryPort

__all__ = ["PgvectorKnowledgeMemoryPort"]
