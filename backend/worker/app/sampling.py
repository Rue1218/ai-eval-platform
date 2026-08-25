"""评测抽样夹紧：与 API.md §5 ``sample_size = min(请求值, 1000, 行数)`` 对齐。"""

from __future__ import annotations

SAMPLE_SIZE_CAP = 1000


def clamp_sample_size(requested: object, n_rows: int, cap: int = SAMPLE_SIZE_CAP) -> int:
    """按契约夹紧抽样行数；未指定或非法请求值时按 ``cap`` 与行数取小。"""
    if n_rows <= 0:
        return 0
    if isinstance(requested, bool) or not isinstance(requested, int) or requested <= 0:
        return min(cap, n_rows)
    return min(requested, cap, n_rows)
