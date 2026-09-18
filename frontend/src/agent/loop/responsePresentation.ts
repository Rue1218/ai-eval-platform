import type { LoopRecord, ToolRun } from '../../api/agentLoopTypes.ts'

/** 供应商正文阶段仅用于展示，不改变 AgentLoop 步数或工具调度。 */
export interface TextPart { output_index: number; phase: 'commentary' | 'final_answer' | null; text: string }

/** 缺少阶段的旧消息沿用整段正文；损坏快照不用于替换已展示内容。 */
export function responseParts(row: LoopRecord): TextPart[] {
  if (Array.isArray(row.text_parts) && row.text_parts.length && row.text_parts.every((part: TextPart) =>
    part && Number.isSafeInteger(part.output_index) && part.output_index >= 0
    && [null, 'commentary', 'final_answer'].includes(part.phase) && typeof part.text === 'string',
  )) return row.text_parts
  return row.text ? [{ output_index: 0, phase: null, text: row.text }] : []
}

/** 显式过程不可混入复制/引用记忆的最终答案，未声明阶段保持旧语义。 */
export function finalResponseText(row: LoopRecord): string {
  const parts = responseParts(row)
  return parts.filter(part => part.phase !== 'commentary').map(part => part.text).join('\n\n').trim()
}

/** 规范工作区相对路径；拒绝绝对路径、编码穿越、控制符和伪协议。 */
function relativePath(value: unknown): string | null {
  if (typeof value !== 'string' || !value || /[\\:%?#]/.test(value) || value.startsWith('/')) return null
  if ([...value].some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) return null
  const parts = value.split('/').filter(part => part !== '.')
  if (parts.some(part => !part || part === '..')) return null
  return parts.join('/') || null
}

/** 文件入口基于同一回合真实 write 回执，下载端点继续校验属主和文件边界。 */
export function writtenFiles(rows: LoopRecord[], row: LoopRecord, workspaceId?: string | null, scopePath?: string | null): Array<{ path: string; url: string }> {
  if (!workspaceId) return []
  const scope = !scopePath || scopePath === '.' ? '' : relativePath(scopePath)
  if (scope === null) return []
  const files = new Map<string, string>()
  for (const candidate of rows) {
    const tool = candidate as ToolRun
    const sameTurn = row.correlation.turn_id
      ? candidate.correlation.turn_id === row.correlation.turn_id
      : row.correlation.turn !== undefined && candidate.correlation.turn === row.correlation.turn
    if (!sameTurn || tool.status !== 'succeeded' || tool.synthetic || tool.display?.registry_name !== 'write') continue
    const path = relativePath(tool.display.file_path)
    if (!path) continue
    const fullPath = scope ? `${scope}/${path}` : path
    // 括号等 encodeURIComponent 默认保留字符也编码，避免破坏 Markdown 链接边界。
    const encodedPath = encodeURIComponent(fullPath).replace(/[!'()*]/g, character => `%${character.charCodeAt(0).toString(16).toUpperCase()}`)
    files.set(path, `/api/workspaces/${encodeURIComponent(workspaceId)}/files/raw?path=${encodedPath}&download=true`)
  }
  return [...files].map(([path, url]) => ({ path, url }))
}

/** 只转换与已确认产物精确匹配的 sandbox 引用，不用文件名模糊匹配。 */
export function artifactLinks(files: Array<{ path: string; url: string }>): Record<string, string> {
  const result: Record<string, string> = {}
  for (const file of files) {
    result[`sandbox:/mnt/data/${file.path}`] = file.url
    result[`sandbox:/${file.path}`] = file.url
  }
  return result
}
