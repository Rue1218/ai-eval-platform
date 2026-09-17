"""同步与异步协议共用的思考档位别名，不替代端点能力探测。"""

import re


def openai_effort(model: str, effort: str) -> str:
    """已知早期推理型号最高为 high，其余兼容端点验证 xhigh 候选。"""
    if effort not in {"max", "xhigh"}:
        return effort
    name = model.strip().lower().rsplit("/", 1)[-1]
    # GPT-5.1-Codex-Max 已支持 xhigh，不能被 GPT-5.1 家族规则误降档。
    legacy = re.match(r"(?:o[134](?:-|$)|gpt-5(?:-|$)|gpt-5\.1(?:-|$))", name)
    return "high" if legacy and not name.startswith("gpt-5.1-codex-max") else "xhigh"
