# AI 测试与评估平台 — Qwen Image 图像生成 MCP 接入说明

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.3 |
| 审查日期 | 2026-08-20 |
| 接入范围 | 平台 API Agent Host 内部短工具 `image.generate`；保留独立 stdio 兼容实现 |
| 配置模型 | 通过 `QWEN_IMAGE_MODEL` 注入 |

## 1. 说明

平台现在按 `audio.voiceclone` 的方式，通过内部 `mcp_tools` 暴露 `image.generate`，调用 DashScope 多模态生成接口，并把生成结果落盘为平台文件。除纯文本输入外，工具支持从本轮上传的 png/jpg/jpeg/webp/gif 图片中自动选择参考图。`backend/image_mcp` 保留为独立 stdio 兼容实现，不是平台运行必需项。

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

## 2. 平台配置与启动方式

平台只需在仓库根目录 `.env` 填写配置，API 容器会通过 Compose 注入：

```text
QWEN_IMAGE_API_URL=https://ws-2jjtk1qzvfbov9p0.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
QWEN_IMAGE_API_KEY=你的 DashScope API Key
QWEN_IMAGE_MODEL=qwen-image-3.0
```

在 Agent 对话中上传图片并输入“生成图片/根据参考图改图”等提示词，平台会自动调用内部 `image.generate`；不需要单独安装或启动 stdio MCP。独立兼容实现的配置见 `backend/image_mcp/README.md`。

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

## V1.3 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/api/app/agent/imagegen.py` | 按 `audio.voiceclone` 的内部短工具方式接入 Qwen Image，支持文本或本轮图片附件生图 |
| `backend/api/app/agent/defaults.py` / `mcp_tools.py` / `plan.py` / `react.py` / `harness.py` | 注册、规划注入、独立线程执行和图片结果交付 |
| `backend/api/app/config.py` / `docker-compose.yml` / `backend/api/app/routers/files.py` | Qwen 环境变量注入与图片附件白名单 |
| `frontend/src/views/Agent.vue` / `frontend/src/styles/base.css` | 图片附件上传、工具卡预览和下载 |
| `backend/api/tests/test_imagegen.py` | 内部图像短工具单元测试 |
