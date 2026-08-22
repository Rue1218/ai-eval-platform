"""知识记录的 ACL 与相似度辅助函数；具体 SQL 仅在 pgvector Store 内执行。"""

from __future__ import annotations

import math
import re
from typing import Any


def record_is_authorized(*, acl_user_ids: Any, user_id: str) -> bool:
    """没有用户白名单时按租户 ACL 放行；有白名单时必须精确命中。"""
    return not isinstance(acl_user_ids, list) or not acl_user_ids or user_id in acl_user_ids


def lexical_score(query_text: str, content: str) -> float:
    """未配置 Embedding 时的保守词项回退，避免把所有知识视作同等相关。"""
    query_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", query_text.lower()))
    content_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", content.lower()))
    if not query_terms or not content_terms:
        return 0.0
    return len(query_terms & content_terms) / math.sqrt(len(query_terms) * len(content_terms))


def vector_score(query_embedding: list[float] | None, embedding: list[float] | None) -> float | None:
    """计算余弦相似度；维度不一致时返回 None 并由词项分数回退。"""
    if not query_embedding or not embedding or len(query_embedding) != len(embedding):
        return None
    numerator = sum(left * right for left, right in zip(query_embedding, embedding, strict=True))
    left_norm = math.sqrt(sum(item * item for item in query_embedding))
    right_norm = math.sqrt(sum(item * item for item in embedding))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else None
