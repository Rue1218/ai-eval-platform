"""Harness 兼容导出；结构化模型输出解析已迁移到 ``app.llm``。"""

from app.llm.structured import parse_json_candidates

__all__ = ["parse_json_candidates"]
