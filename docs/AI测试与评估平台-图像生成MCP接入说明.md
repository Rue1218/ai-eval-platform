# AI 测试与评估平台 — Qwen Image 图像生成 MCP 接入说明

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.2 |
| 审查日期 | 2026-08-20 |
| 接入范围 | 独立 stdio MCP，不纳入平台 V1.0 外部 MCP REST/WS 契约 |
| 配置模型 | 通过 `QWEN_IMAGE_MODEL` 注入 |

## 1. 说明

本 MCP 暴露 `generate_image` 工具，调用 DashScope 多模态生成接口，并将上游返回的临时图片 URL 下载后转成 MCP `image` 内容返回。除纯文本输入外，工具现在支持传入一张参考图；`image` 可以是公网 URL、Data URI 或服务端本地图片路径。本地路径会在请求前转成 Data URI。

官方接口的图文输入使用同一个 user message 的 `content` 数组，同时放入 `image` 和 `text` 内容块。[Qwen Image 3.0 图像生成与编辑 API 参考](https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference)

```json
{
  "model": "qwen-image-3.0",
  "input": {
    "messages": [
      {
        "role": "user",
        "content": [
          {"image": "https://example.com/reference.png"},
          {"text": "请基于参考图生成一张油画风格图片"}
        ]
      }
    ]
  },
  "parameters": {"prompt_extend": true}
}
```

URL、API Key 和模型 ID 从仓库根目录 `.env` 或进程环境读取，分别对应 `QWEN_IMAGE_API_URL`、`QWEN_IMAGE_API_KEY` 和 `QWEN_IMAGE_MODEL`。API Key 也兼容 curl 示例中的 `DASHSCOPE_API_KEY`；如果两者同时存在，优先使用 `QWEN_IMAGE_API_KEY`。代码、日志和文档均不保存真实密钥；用户此前提供的密钥若已经暴露，应在供应商控制台轮换。

## 2. 启动方式

在仓库根目录 `.env` 填写配置，然后安装 `backend/image_mcp/requirements.txt` 并运行：

```text
QWEN_IMAGE_API_URL=https://ws-2jjtk1qzvfbov9p0.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
QWEN_IMAGE_API_KEY=你的 DashScope API Key
QWEN_IMAGE_MODEL=qwen-image-3.0
```

```powershell
python -m backend.image_mcp.server
```

完整客户端配置、参数和错误说明见 `backend/image_mcp/README.md`。

## 3. 错误处理

| 场景 | MCP 工具错误 |
| --- | --- |
| 缺少 URL、Key 或模型 ID，或超时配置非法 | `CONFIG` |
| `prompt` 为空或过长 | `VALIDATION` |
| 上游 4xx/5xx、连接失败、响应结构异常 | `UPSTREAM` |
| 上游请求或图片下载超时 | `TIMEOUT` |

上游错误只保留状态码或通用说明，不回显响应原文、请求头或 API Key。

## 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/image_mcp/client.py` | Qwen Image 请求组装、响应解析、图片下载、大小校验和错误归一 |
| `backend/image_mcp/server.py` | FastMCP stdio 服务与支持文本+图像输入的 `generate_image` 工具注册 |
| `backend/image_mcp/requirements.txt` | 独立 MCP 运行依赖 |
| `backend/image_mcp/README.md` | 安装、环境变量和客户端配置示例 |
| `backend/image_mcp/tests/test_client.py` | 不调用真实上游的客户端单元测试 |

## V1.2 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/image_mcp/client.py` | 自动加载仓库根目录 `.env`，从环境变量读取 URL、API Key 和模型 ID；缺失配置时拒绝发起请求 |
| `backend/image_mcp/requirements.txt` | 增加 `python-dotenv`，支持独立 MCP 自动加载 `.env` |
| `backend/image_mcp/README.md` / `.env.example` | 补充三项 Qwen Image 配置示例 |
| `backend/image_mcp/tests/test_client.py` | 增加环境变量配置读取测试并更新模型配置测试 |
