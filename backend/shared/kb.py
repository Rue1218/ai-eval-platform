"""知识库域共享工具：文本切块、检索与检索指标计算（api / worker 共用）。

LightRAG 服务目前是空返回 stub。检索策略为「先调 LightRAG，无结果则回退
本地关键词检索」，保证 RAG 评测链路端到端可产出真实报告；M3 替换为
lightrag-hku 后，只要其 ``/query`` 返回非空 contexts 即自动切回。
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request

logger = logging.getLogger("ai-eval.kb")

# 检索返回的最大切块数上限（对齐前端 k ≤ 20 约束）
MAX_K = 20
# 检索默认 Top-K
DEFAULT_K = 5
# 单次切块预览的最大分块数，防止超大文档一次生成海量切块
MAX_CHUNK_PREVIEW = 200
# 调用 LightRAG /query 的超时（秒）：stub 或不可达时快速回退本地检索
LIGHTRAG_TIMEOUT_S = 2.0


def _lightrag_base_url() -> str:
    """读取 LightRAG 服务地址；未配置时返回空串表示禁用上游。"""
    return os.environ.get("LIGHTRAG_BASE_URL", "").strip()


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64,
    doc_id: str = "d",
    limit: int = MAX_CHUNK_PREVIEW,
) -> list[dict]:
    """按字符滑动窗口切块，返回 ``[{chunk_id, doc_id, text, tokens}]``。

    ``chunk_id`` 形如 ``{doc_id}#c01``，与前端「切块流」契约一致。
    ``tokens`` 按字符数粗估（中文一字一 token 的近似）。
    """
    chunk_size = max(64, min(int(chunk_size or 512), 24_000))
    overlap = max(0, min(int(overlap or 0), chunk_size - 1))
    step = chunk_size - overlap

    raw = text or ""
    chunks: list[dict] = []
    start = 0
    n = 0
    while start < len(raw) and n < limit:
        seg = raw[start : start + chunk_size]
        if not seg:
            break
        n += 1
        chunks.append(
            {
                "chunk_id": f"{doc_id}#c{n:02d}",
                "doc_id": doc_id,
                "text": seg,
                "tokens": len(seg),
            }
        )
        start += step
    if not chunks and raw:
        chunks.append(
            {"chunk_id": f"{doc_id}#c01", "doc_id": doc_id, "text": raw, "tokens": len(raw)}
        )
    return chunks


def _query_terms(query: str) -> list[str]:
    """把查询拆成检索词元：拉丁词 + 中文相邻字符二元组。"""
    text = (query or "").strip()
    if not text:
        return []
    terms: list[str] = re.findall(r"[A-Za-z0-9_]+", text.lower())
    han = re.findall(r"[\u4e00-\u9fff]+", text)
    for run in han:
        if len(run) == 1:
            terms.append(run)
        else:
            terms.extend(run[i : i + 2] for i in range(len(run) - 1))
    return [t for t in terms if t]


def _score_chunk(chunk_text_: str, terms: list[str]) -> float:
    """词元命中比例打分：命中词元数 / 总词元数，落在 [0, 1]。"""
    if not terms:
        return 0.0
    low = chunk_text_.lower()
    hits = sum(1 for t in terms if t in low)
    return hits / len(terms)


def _try_lightrag(query: str, mode: str, k: int) -> list[dict] | None:
    """调用 LightRAG ``/query``；返回映射后的上下文列表，不可用返回 None。"""
    base = _lightrag_base_url()
    if not base:
        return None
    try:
        payload = json.dumps(
            {"query": query, "mode": mode or "hybrid", "top_k": min(k, MAX_K)}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{base.rstrip('/')}/query",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=LIGHTRAG_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        contexts = data.get("contexts") or []
        if not contexts:
            return None
        items = []
        for ctx in contexts:
            chunk_id = str(ctx.get("id") or "")
            if not chunk_id:
                continue
            doc_id = chunk_id.split("#", 1)[0]
            items.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "doc_name": doc_id,
                    "text": ctx.get("text") or "",
                    "similarity": None,
                }
            )
        return items or None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        logger.warning("LightRAG /query 不可用，回退本地关键词检索")
        return None


def _local_retrieve(db, kb_id: str, query: str, k: int) -> list[dict]:
    """本地关键词检索：对库内文档正文切块后按词元命中比例取 top-k。"""
    from shared.models import KbDocument  # 延迟导入避免循环依赖

    docs = db.query(KbDocument).filter(KbDocument.kb_id == kb_id).all()
    terms = _query_terms(query)
    scored: list[dict] = []
    for doc in docs:
        for chunk in chunk_text(doc.text, chunk_size=512, overlap=64, doc_id=doc.id):
            score = _score_chunk(chunk["text"], terms)
            if score > 0:
                scored.append(
                    {
                        "chunk_id": chunk["chunk_id"],
                        "doc_id": doc.id,
                        "doc_name": doc.filename,
                        "text": chunk["text"],
                        "similarity": round(score, 4),
                    }
                )
    scored.sort(key=lambda item: item["similarity"], reverse=True)
    return scored[: min(k, MAX_K)]


# 检索引擎来源标识（报告诚实标注降级用）
RETRIEVE_SOURCE_LIGHTRAG = "lightrag"
RETRIEVE_SOURCE_LOCAL = "local"


def retrieve_with_source(
    db, kb_id: str, query: str, mode: str = "hybrid", k: int = 5
) -> tuple[list[dict], str]:
    """执行一次 Top-K 检索并返回引擎来源，供评测报告诚实标注降级。

    返回 ``(items, source)``：``source`` ∈ {lightrag, local}——LightRAG
    可用（返回非空）时为 ``lightrag``；未配置 / 不可达 / 空结果回退本地
    关键词检索时为 ``local``。评测报告必须据此区分引擎来源，禁止把
    本地兜底结果无标注地当作 LightRAG 引擎成绩对外呈现。
    """
    k = max(1, min(int(k or DEFAULT_K), MAX_K))
    items = _try_lightrag(query, mode, k)
    if items is not None:
        return items, RETRIEVE_SOURCE_LIGHTRAG
    return _local_retrieve(db, kb_id, query, k), RETRIEVE_SOURCE_LOCAL


def retrieve(db, kb_id: str, query: str, mode: str = "hybrid", k: int = 5) -> list[dict]:
    """向后兼容封装：只返回 Top-K 检索结果，不暴露引擎来源（REST 目录等场景）。"""
    items, _ = retrieve_with_source(db, kb_id, query, mode=mode, k=k)
    return items


def compute_metrics(retrieved: list[dict], expected_doc_ids: list[str], reference: str = "") -> dict:
    """按「命中文档 ∈ 期望文档」计算单查询检索指标。

    返回 ``{hit_rate, mrr, recall, contain}``；无 expected_doc_ids 时各指标为 0
    （分母口径由调用方通过 ``hit_denominator_note`` 说明）。
    """
    expected = {str(e) for e in (expected_doc_ids or []) if e}
    hit_rate = mrr = recall = contain = 0.0
    if expected:
        hit_idx = next((i for i, item in enumerate(retrieved) if item.get("doc_id") in expected), None)
        if hit_idx is not None:
            hit_rate = 1.0
            mrr = 1.0 / (hit_idx + 1)
        hit_docs = {item.get("doc_id") for item in retrieved if item.get("doc_id") in expected}
        recall = len(hit_docs) / len(expected)
    if reference:
        contain = 1.0 if any((reference or "") in (item.get("text") or "") for item in retrieved) else 0.0
    return {
        "hit_rate": round(hit_rate, 4),
        "mrr": round(mrr, 4),
        "recall": round(recall, 4),
        "contain": round(contain, 4),
    }
