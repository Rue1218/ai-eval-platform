import type { ToolRun } from '../../api/agentLoopTypes.ts'

/** 已登记媒体工具；未知工具的 JSON 结果一律不尝试解释为可加载资源。 */
const MEDIA_TOOLS = new Set(['image.generate', 'video.create', 'video.status'])
const TEXT_LIMIT = 300
const IMAGE_LIMIT = 4

export interface MediaPreview {
  kind: 'image' | 'video'
  status: string
  model: string | null
  upstreamTaskId: string | null
  imageUrls: string[]
  videoUrl: string | null
}

/** 只允许上游产物的 HTTPS 地址，拒绝 data、脚本和含账户信息的链接。 */
export function safeMediaUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : null
  } catch {
    return null
  }
}

function textField(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const text = value.trim().slice(0, TEXT_LIMIT)
  return text || null
}

/** 从既有脱敏结果预览提取固定字段，避免将任意 MCP JSON 当作浏览器内容。 */
export function mediaPreviewFor(tool: Pick<ToolRun, 'name' | 'status' | 'event' | 'display'>): MediaPreview | null {
  if (tool.event !== 'tool.result' || tool.status !== 'succeeded' || !MEDIA_TOOLS.has(tool.name)) return null
  const raw = tool.display.result_preview
  if (typeof raw !== 'string') return null
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const result = value as Record<string, unknown>
  const isImage = tool.name === 'image.generate'
  const imageUrls = isImage && Array.isArray(result.image_urls)
    ? result.image_urls.map(safeMediaUrl).filter((url): url is string => !!url).slice(0, IMAGE_LIMIT)
    : []
  const videoUrl = !isImage ? safeMediaUrl(result.video_url) : null
  const status = textField(result.status) || 'UNKNOWN'
  const preview: MediaPreview = {
    kind: isImage ? 'image' : 'video',
    status,
    model: textField(result.model),
    upstreamTaskId: textField(result.upstream_task_id),
    imageUrls,
    videoUrl,
  }
  return imageUrls.length || videoUrl || preview.upstreamTaskId || preview.model || status !== 'UNKNOWN' ? preview : null
}
