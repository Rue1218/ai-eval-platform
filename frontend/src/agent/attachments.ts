/**
 * 附件暂存域：后缀白名单、准入校验与预览 URL 生命周期（2026-09-11 抽离）。
 *
 * 从 `Agent.vue` 抽出可单测的纯逻辑与资源追踪；上传编排（`api.files.upload`、
 * 提示与暂存架状态更新）仍留在组件。
 */

/** 与后端 files 白名单对齐；未知后缀一律拒绝，不猜测 MIME。 */
export const ALLOWED_ATTACHMENT_SUFFIXES = new Set([
  '.md', '.txt', '.html', '.pdf', '.json', '.yaml', '.yml', '.xlsx', '.xls', '.csv', '.jsonl',
  '.doc', '.docx', '.wav', '.mp3', '.png', '.jpg', '.jpeg', '.webp', '.gif',
])

/** 单附件上限 20MB；空文件同样拒绝。 */
export const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024

/** 后缀是否在白名单内（大小写不敏感；无后缀拒绝）。 */
export function hasAllowedAttachmentSuffix(name: string): boolean {
  const dotIndex = name.lastIndexOf('.')
  return dotIndex >= 0 && ALLOWED_ATTACHMENT_SUFFIXES.has(name.slice(dotIndex).toLowerCase())
}

/** 附件准入校验：通过返回 null，否则返回拒绝类别（调用方合成统一提示文案）。 */
export function attachmentRejectionReason(file: { name: string; size: number }): string | null {
  if (!file.size) return '空文件'
  if (file.size > MAX_ATTACHMENT_BYTES) return '超过 20MB'
  if (!hasAllowedAttachmentSuffix(file.name)) return '格式不支持'
  return null
}

/** 预览 URL 追踪器：只撤销由本追踪器创建的 object URL，避免误放他人资源。 */
export interface PreviewTracker {
  create(file: Blob): string
  release(url: string | undefined): void
  revokeAll(): void
  readonly size: number
}

export function createPreviewTracker(
  create: (file: Blob) => string = file => URL.createObjectURL(file),
  revoke: (url: string) => void = url => URL.revokeObjectURL(url),
): PreviewTracker {
  const urls = new Set<string>()
  return {
    create(file: Blob): string {
      const url = create(file)
      urls.add(url)
      return url
    },
    release(url: string | undefined) {
      if (!url || !urls.has(url)) return
      revoke(url)
      urls.delete(url)
    },
    revokeAll() {
      for (const url of urls) revoke(url)
      urls.clear()
    },
    get size() {
      return urls.size
    },
  }
}
