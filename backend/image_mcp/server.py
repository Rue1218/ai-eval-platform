"""Qwen Image 3.0 图像生成 MCP Server（stdio）。

启动后暴露 ``generate_image`` 工具。服务默认使用 stdio 传输，适用于
Claude Desktop、Cursor、Codex 等支持 MCP 的客户端；不要把 API Key 写入
客户端配置文件之外的仓库文件或打印到标准输出。
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP, Image
from mcp.server.fastmcp.exceptions import ToolError

from .client import ImageMcpError, QwenImageClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("qwen-image-mcp")

mcp = FastMCP("qwen-image")


@mcp.tool(
    name="generate_image",
    title="生成图片",
    description=(
        "使用 Qwen Image 3.0 根据中文或英文提示词生成一张图片。"
        "prompt_extend=true 时由模型自动扩展提示词。"
    ),
    structured_output=False,
)
async def generate_image(
    prompt: str,
    image: str | None = None,
    prompt_extend: bool = True,
) -> list[Image | str]:
    """调用 Qwen Image 3.0，并把生成图片作为 MCP image 内容返回。"""
    try:
        result = await QwenImageClient().generate(
            prompt,
            image=image,
            prompt_extend=prompt_extend,
        )
        contents: list[Image | str] = [Image(data=result.data, format=result.image_format)]
        if result.image_url:
            # URL 通常为有时效的临时地址，作为辅助文本返回，不影响图片内容交付。
            contents.append(f"临时图片地址：{result.image_url}")
        return contents
    except ImageMcpError as exc:
        logger.warning("图像生成失败 code=%s", exc.code)
        raise ToolError(exc.message) from exc
    except Exception as exc:
        logger.exception("图像生成内部异常 type=%s", type(exc).__name__)
        raise ToolError("图像生成失败，请稍后重试") from exc


if __name__ == "__main__":
    # MCP stdio 协议占用标准输入/输出，日志仅写 stderr。
    mcp.run("stdio")
