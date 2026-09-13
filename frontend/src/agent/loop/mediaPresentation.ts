import type { ToolRun } from '../../api/agentLoopTypes.ts'

/** 已登记媒体工具；未知工具的 JSON 结果一律不尝试解释为可加载资源。 */
const MEDIA_TOOLS = new Set(['image.generate', 'video.create', 'video.status'])
const TEXT_LIMIT = 300
const IMAGE_LIMIT = 4

/** 模型侧安全名 → 注册表短名：服务端对含点号的工具统一生成 platform_ 前缀名。 */
const MEDIA_WIRE_ALIASES: Record<string, string> = {
  platform_image_generate: 'image.generate',
  platform_video_create: 'video.create',
  platform_video_status: 'video.status',
}

/** 事件里的 name 是模型可见的 wire 名；先归一再匹配登记表。 */
export function canonicalMediaToolName(name: string): string {
  return MEDIA_WIRE_ALIASES[name] || name
}

type MediaToolRun = Pick<ToolRun, 'name' | 'status' | 'event' | 'display' | 'registry_name'>

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
export function mediaPreviewFor(tool: MediaToolRun): MediaPreview | null {
  // 调度事件回传的 registry_name 最可信；缺失时按 wire 别名表归一。
  const name = canonicalMediaToolName(tool.registry_name || tool.name)
  if (tool.event !== 'tool.result' || tool.status !== 'succeeded' || !MEDIA_TOOLS.has(name)) return null
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
  const isImage = name === 'image.generate'
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

/** 汇总同一轮的安全媒体结果，由总结区统一展示，工具卡不再承载图片或视频预览。 */
export function mediaPreviewsFor(tools: Iterable<MediaToolRun>): MediaPreview[] {
  const byMedia = new Map<string, MediaPreview>()
  for (const tool of tools) {
    const preview = mediaPreviewFor(tool)
    if (!preview) continue
    // 同一视频任务的多次查询合并为一条；图片按地址集合去重（重试不产生重复卡）。
    const key = preview.kind === 'image'
      ? `image:${preview.imageUrls.join(',')}`
      : `video:${preview.upstreamTaskId || preview.videoUrl || ''}`
    const existing = byMedia.get(key)
    if (!existing || (!existing.videoUrl && preview.videoUrl)) byMedia.set(key, preview)
  }
  return [...byMedia.values()]
}
