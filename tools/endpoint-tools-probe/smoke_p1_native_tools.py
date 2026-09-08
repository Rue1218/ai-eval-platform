#!/usr/bin/env python3
"""P1 原生工具装配冒烟探针：直连模型端点验证协议 tools 支持度（DoD②）。

不依赖 api 容器、不进仓库内部模块——用与生产一致的协议（Anthropic Messages /
OpenAI chat / OpenAI Responses）向模型端点发最小 tools 请求，回答 V0.2 评审
标注的「最大外部不确定项」：该端点是否完整实现 tools 下发 / tool_use 返回 /
tool 消息回填配对。

用例：
- A  tools 下发：请求携带 tools → 端点不 400（pass/fail，且记录 usage）；
- B  tool_use 观察：模型在 tools 下是否产出原生 tool_use（observe，不判
  pass/fail——模型选择文本亦属合法）；
- C  回填配对：把 B 的 tool_use 以 tool_result 回填后发起下一轮 → 不 400
  （anthropic_messages / openai_chat；responses 的 function_call_output
  回填格式另立后置项）；
- D  legacy 对照：无 tools 的基线请求 → 2xx（端点可用性对照）。

用法（服务器或任意可达机器；API Key 只从环境变量/参数读，绝不落日志）：
    SMOKE_BASE_URL=http://host:port SMOKE_API_KEY=... SMOKE_MODEL=... \\
        python smoke_p1_native_tools.py [--protocol anthropic_messages|openai_chat|openai_responses]

输出：末尾一行 ``SMOKE_RESULT <json>``（status ∈ pass/fail/observe/skip），
便于 ``grep SMOKE_RESULT`` 回传。完整判据与回传模板见
docs/AI测试与评估平台-原生工具装配-P1冒烟清单.md。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

SMOKE_PROMPT = (
    "请先调用 read_file 工具读取文件路径 /work/smoke.txt 的内容，"
    "然后总结该文件的主题与行数。"
)
READ_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"path": {"type": "string", "description": "目标文件路径"}},
    "required": ["path"],
}


def _tool_defs(protocol: str) -> list[dict[str, Any]]:
    if protocol == "anthropic_messages":
        return [
            {
                "name": "read_file",
                "description": "读取 /work 目录下的文本文件",
                "input_schema": READ_TOOL_SCHEMA,
            }
        ]
    if protocol == "openai_chat":
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "读取 /work 目录下的文本文件",
                    "parameters": READ_TOOL_SCHEMA,
                },
            }
        ]
    return [
        {
            "type": "function",
            "name": "read_file",
            "description": "读取 /work 目录下的文本文件",
            "parameters": READ_TOOL_SCHEMA,
        }
    ]


def _endpoint(base_url: str, protocol: str) -> str:
    base = base_url.rstrip("/")
    if protocol == "anthropic_messages":
        path = "/messages" if base.endswith("/v1") else "/v1/messages"
    elif protocol == "openai_chat":
        path = "/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"
    else:
        path = "/responses" if base.endswith("/v1") else "/v1/responses"
    return base + path


def _headers(base_url: str, api_key: str, protocol: str) -> dict[str, str]:
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {api_key}",
    }
    if protocol == "anthropic_messages":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
        headers.pop("authorization")
    if "http://" not in base_url and "https://" not in base_url:
        raise SystemExit(f"非法 base-url：{base_url}")
    return headers


def _post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return {"http_status": response.status, "body": json.loads(raw)}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return {"http_status": exc.code, "error": raw[:600]}
    except urllib.error.URLError as exc:
        return {"http_status": 0, "error": f"网络错误：{exc.reason}"}


def _summary(protocol: str, data: dict[str, Any]) -> dict[str, Any]:
    """从响应提取脱敏摘要（usage/内容类型/tool_use 名）。"""
    if "error" in data:
        return {"error": data["error"]}
    body = data.get("body") or {}
    out: dict[str, Any] = {"http_status": data.get("http_status")}
    usage = body.get("usage") or {}
    if protocol == "anthropic_messages":
        out["usage"] = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }
        blocks = body.get("content") or []
        out["block_types"] = [block.get("type") for block in blocks]
        tool_use = [b for b in blocks if b.get("type") == "tool_use"]
        out["tool_use"] = [
            {"id": b.get("id"), "name": b.get("name"), "input_keys": sorted((b.get("input") or {}).keys())}
            for b in tool_use
        ]
        out["text_preview"] = "".join(
            b.get("text", "") for b in blocks if b.get("type") == "text"
        )[:200]
    elif protocol == "openai_chat":
        out["usage"] = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }
        choices = body.get("choices") or []
        message = (choices[0] or {}).get("message") or {}
        calls = message.get("tool_calls") or []
        out["tool_use"] = [
            {"id": c.get("id"), "name": (c.get("function") or {}).get("name"),
             "arguments_preview": ((c.get("function") or {}).get("arguments") or "")[:200]}
            for c in calls
        ]
        out["text_preview"] = str(message.get("content") or "")[:200]
    else:
        out["usage"] = {
            "input_tokens": (usage.get("input_tokens") or [{}])[0].get("tokens"),
            "output_tokens": (usage.get("output_tokens") or [{}])[0].get("tokens"),
        }
        items = body.get("output") or []
        out["item_types"] = [item.get("type") for item in items]
        calls = [i for i in items if i.get("type") == "function_call"]
        out["tool_use"] = [
            {"call_id": i.get("call_id"), "name": i.get("name")} for i in calls
        ]
        out["text_preview"] = "".join(
            item.get("content", "") for item in items if item.get("type") == "message"
        )[:200]
    return out


def _user_message(content: str, protocol: str) -> dict[str, Any]:
    return {"role": "user", "content": content}


def _assistant_tool_use_message(protocol: str, tool_use: dict[str, Any]) -> dict[str, Any]:
    """按协议回放首次响应中的 tool_use，构造 assistant 消息（C 用例输入）。"""
    if protocol == "anthropic_messages":
        return {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use["id"],
                    "name": tool_use["name"],
                    "input": {"path": "/work/smoke.txt"},
                }
            ],
        }
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": tool_use["id"],
                "type": "function",
                "function": {
                    "name": tool_use["name"],
                    "arguments": json.dumps({"path": "/work/smoke.txt"}),
                },
            }
        ],
    }


def _tool_result_user_message(protocol: str, tool_use_id: str) -> dict[str, Any]:
    """按协议构造 tool_result 回填消息（C 用例输入）。"""
    if protocol == "anthropic_messages":
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "smoke.txt 内容：p1 smoke marker（第 1 行）。主题：冒烟探针。",
                }
            ],
        }
    return {
        "role": "tool",
        "tool_call_id": tool_use_id,
        "content": "smoke.txt 内容：p1 smoke marker（第 1 行）。主题：冒烟探针。",
    }


def _run_protocol(base_url: str, api_key: str, model: str, protocol: str) -> list[dict[str, Any]]:
    endpoint = _endpoint(base_url, protocol)
    headers = _headers(base_url, api_key, protocol)
    results: list[dict[str, Any]] = []

    def record(case_id: str, status: str, detail: dict[str, Any]) -> None:
        results.append({"id": case_id, "status": status, "detail": detail})

    # A：tools 下发（DoD② 主判据：端点接受 tools 字段）
    body_a: dict[str, Any] = {
        "model": model,
        "max_tokens": 512,
        "tools": _tool_defs(protocol),
        "messages": [_user_message(SMOKE_PROMPT, protocol)],
    }
    if protocol == "openai_responses":
        body_a = {
            "model": model,
            "tools": _tool_defs(protocol),
            "input": SMOKE_PROMPT,
        }
    response_a = _post(endpoint, headers, body_a)
    summary_a = _summary(protocol, response_a)
    status_a = "pass" if summary_a.get("http_status") == 200 else "fail"
    record("A-tools-下发", status_a, summary_a)

    # B：tool_use 观察（模型行为观测，不判 pass/fail）
    tool_uses = (summary_a.get("tool_use") or []) if summary_a.get("http_status") == 200 else []
    record(
        "B-tool_use-观察",
        "observe",
        {"tool_use_count": len(tool_uses), "tool_use": tool_uses[:3]},
    )

    # C：tool_use → tool_result 回填配对后下一轮（P2 回填的最大外部前提）
    if not tool_uses:
        record("C-回填配对", "skip", {"reason": "首次响应无 tool_use，无法构造真实回填对"})
    elif protocol == "openai_responses":
        record(
            "C-回填配对",
            "skip",
            {"reason": "Responses 回填经 function_call_output item，后置专项验证"},
        )
    else:
        first = tool_uses[0]
        body_c: dict[str, Any] = {
            "model": model,
            "max_tokens": 512,
            "messages": [
                _user_message(SMOKE_PROMPT, protocol),
                _assistant_tool_use_message(protocol, first),
                _tool_result_user_message(protocol, str(first.get("id") or "")),
            ],
        }
        response_c = _post(endpoint, headers, body_c)
        summary_c = _summary(protocol, response_c)
        record(
            "C-回填配对",
            "pass" if summary_c.get("http_status") == 200 else "fail",
            summary_c,
        )

    # D：legacy 对照（无 tools 基线可用性）
    body_d: dict[str, Any] = {
        "model": model,
        "max_tokens": 128,
        "messages": [_user_message("请用一句话说明评测平台的主要用途。", protocol)],
    }
    if protocol == "openai_responses":
        body_d = {"model": model, "input": "请用一句话说明评测平台的主要用途。"}
    response_d = _post(endpoint, headers, body_d)
    summary_d = _summary(protocol, response_d)
    record("D-legacy对照", "pass" if summary_d.get("http_status") == 200 else "fail", summary_d)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="P1 原生工具装配端点冒烟探针（DoD②）")
    parser.add_argument(
        "--protocol",
        default=os.environ.get("SMOKE_PROTOCOL", "anthropic_messages"),
        choices=("anthropic_messages", "openai_chat", "openai_responses"),
    )
    parser.add_argument("--base-url", default=os.environ.get("SMOKE_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("SMOKE_API_KEY", ""))
    parser.add_argument("--model", default=os.environ.get("SMOKE_MODEL", ""))
    args = parser.parse_args()
    if not args.base_url or not args.api_key or not args.model:
        parser.error("需要 --base-url/--api-key/--model（或 SMOKE_BASE_URL/SMOKE_API_KEY/SMOKE_MODEL）")

    results = _run_protocol(args.base_url, args.api_key, args.model, args.protocol)
    report = {
        "protocol": args.protocol,
        "model": args.model,
        "endpoint": _endpoint(args.base_url, args.protocol),
        "cases": results,
        "summary": {
            "pass": sum(1 for case in results if case["status"] == "pass"),
            "fail": sum(1 for case in results if case["status"] == "fail"),
            "skip": sum(1 for case in results if case["status"] == "skip"),
            "observe": sum(1 for case in results if case["status"] == "observe"),
        },
    }
    print(f"SMOKE_RESULT {json.dumps(report, ensure_ascii=False)}")
    # A/C/D 任一 fail 即退出码非 0（B 为观察项不计）
    return 1 if report["summary"]["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
