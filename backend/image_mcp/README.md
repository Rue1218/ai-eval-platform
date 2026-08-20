# Qwen Image 3.0 图像生成 MCP

这是一个独立的 stdio MCP Server，不修改平台现有 REST/WS/MCP 内置短工具契约。

## 安装

```powershell
cd backend/image_mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 配置

只通过环境变量注入 API Key：

```powershell
$env:QWEN_IMAGE_API_KEY = "你的 DashScope API Key"
```

也兼容 curl 示例中的环境变量名：`DASHSCOPE_API_KEY`。如果两者同时存在，优先使用 `QWEN_IMAGE_API_KEY`。

可选配置：

```text
QWEN_IMAGE_API_URL=https://ws-2jjtk1qzvfbov9p0.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
QWEN_IMAGE_TIMEOUT_SECONDS=120
```

不要把真实 Key 写入 Git、README、日志或截图。用户提供的 Key 若已在其他地方公开，建议在 DashScope 控制台立即轮换。

## 启动

从仓库根目录运行：

```powershell
python -m backend.image_mcp.server
```

如果 MCP 客户端要求命令和参数，可配置为：

```json
{
  "mcpServers": {
    "qwen-image": {
      "command": "python",
      "args": ["-m", "backend.image_mcp.server"],
      "cwd": "C:/Users/Toneya/Desktop/ai-eval-platform",
      "env": {
        "QWEN_IMAGE_API_KEY": "${QWEN_IMAGE_API_KEY}"
      }
    }
  }
}
```

工具名为 `generate_image`，参数如下：

- `prompt`：必填，图像提示词；
- `image`：可选，参考图的公网 HTTP(S) URL、`data:image/...;base64,...`，或 MCP 服务所在机器上的本地图片路径；
- `prompt_extend`：可选，默认 `true`，对应 DashScope 请求中的 `parameters.prompt_extend`。

传入 `image` 时，请求中的 `content` 会按 `[{"image": ...}, {"text": ...}]` 发送；不传时仍为纯文本生图。返回值包含 MCP 图片内容；当上游返回临时 URL 时，也会附带该 URL 文本。
