"""供应商识别与能力说明；端点控制 wire 方言，模型品牌不覆盖托管服务。"""

from urllib.parse import urlparse


def detect_provider(base_url: str, model: str, protocol: str) -> str:
    """先按真实主机识别服务，代理端点再按模型回退；不匹配路径或伪造后缀。"""
    host = (urlparse(base_url).hostname or "").lower()
    domains = {
        "nvidia.com": "nvidia", "volces.com": "volcengine",
        "aliyuncs.com": "qwen", "bigmodel.cn": "zhipu", "z.ai": "zhipu",
        "moonshot.cn": "moonshot", "moonshot.ai": "moonshot", "kimi.com": "moonshot",
        "minimaxi.com": "minimax", "minimax.cn": "minimax", "minimax.io": "minimax", "minimax.chat": "minimax",
        "deepseek.com": "deepseek", "anthropic.com": "anthropic",
        "googleapis.com": "google", "openai.com": "openai", "xiaomimimo.com": "mimo",
    }
    for domain, provider in domains.items():
        if host == domain or host.endswith("." + domain):
            return provider
    name = model.lower().split("/")[-1]
    for prefixes, provider in (
        (("deepseek",), "deepseek"), (("qwen", "qwq"), "qwen"),
        (("glm",), "zhipu"), (("kimi", "moonshot"), "moonshot"),
        (("minimax",), "minimax"), (("gemini",), "google"),
        (("doubao",), "volcengine"), (("claude",), "anthropic"), (("mimo",), "mimo"),
    ):
        if name.startswith(prefixes):
            return provider
    return "anthropic" if protocol == "anthropic_messages" else "openai"


def reasoning_note(provider: str, model: str) -> str:
    """只描述可验证的参数语义，避免把平台档位当成厂商原生能力。"""
    name = model.lower()
    if "[" in name and name.endswith("]"):
        return "模型名已包含代理参数；请在协议档的模型参数中调整思考设置。"
    if provider == "minimax":
        return "M2 系列始终思考，无法关闭；M3 支持开关。开启档位等价，不发送未经支持的 effort。"
    if provider in {"zhipu", "moonshot", "nvidia"}:
        return "已支持型号按开关控制思考；low / medium / high / max 等价为开启。固定思考型号不提供 off。"
    if provider == "deepseek":
        return "V4：low → low，medium / high → high，max → max；旧型号只控制思考开关。"
    if provider == "qwen":
        return "支持预算的型号按输出上限分配 20% / 40% / 60% / 80% 思考预算；固定思考或非思考型号限制选项。"
    if provider == "anthropic":
        return "默认 high；新版 Claude 使用自适应思考，旧版按输出上限分配思考预算。max 映射型号支持的最高档。"
    if provider == "google":
        return "Gemini 2.5 使用 token 预算，3 系列使用思考等级；max 映射最高可用等级。部分型号无法关闭思考。"
    if provider == "volcengine":
        return "Seed 1.8 / 2.x 使用原生强度，max 映射 high；其它已知型号按思考开关控制。部署 ID 需核实模型能力。"
    return "按模型能力发送思考参数；max 映射支持的最高档，不支持的选项不可提交。"
