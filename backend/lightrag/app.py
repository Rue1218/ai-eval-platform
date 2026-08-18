import os

from fastapi import FastAPI
from pydantic import BaseModel

# LightRAG 服务骨架。
#
# M3 真实集成时替换为官方 LightRAG（MIT，锁 tag）API：
#   pip install lightrag-hku[api]
#   uvicorn lightrag.api.lightrag_server:app
# 本文件提供与 PRD F-RAG-01 一致的内部契约占位：
#   POST /query  -> {text, contexts:[{id,text}]}
#   GET  /health -> 健康检查
# 平台适配层把 LightRAG 原生 query API 映射成上述结构，不把 LightRAG 伪装成 OpenAI Chat。

app = FastAPI(title="LightRAG (stub)", version="0.1.0")


class QueryRequest(BaseModel):
    query: str
    mode: str = "hybrid"  # naive / local / global / hybrid
    top_k: int = 5


class Context(BaseModel):
    id: str
    text: str


class QueryResponse(BaseModel):
    text: str
    contexts: list[Context]


@app.get("/health")
def health():
    return {"status": "ok", "backend": "stub"}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    # 骨架版：不调用真实 LightRAG，直接返回空上下文。
    # TODO(M3): 接入 LightRAG QueryParam，按 req.mode 执行 naive/local/global/hybrid 查询。
    _ = (req.query, req.mode, req.top_k)
    return QueryResponse(text="", contexts=[])
