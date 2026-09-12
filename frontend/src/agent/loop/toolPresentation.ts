import type { ToolStatus } from '../../api/agentLoopTypes.ts'
import { taskToolAliases } from './taskPresentation.ts'
/** 精确登记别名；未知工具保持原名，不推断执行能力。 */
export const toolAliases: Record<string, string> = {
  ...taskToolAliases,
  'image.generate': '生成图片',
  'video.create': '创建图生视频',
  'video.status': '查询视频结果',
}
export const statusLabels: Record<ToolStatus, string> = {
  pending: '待派发', waiting_approval: '等待交互', running: '执行中', succeeded: '已完成', failed: '失败',
  denied: '已拒绝', cancelled: '已取消', not_started: '未启动', outcome_unknown: '结果未知',
}
/** 工具链接仅支持 HTTP(S) 和平台绝对路由，拒绝协议相对及脚本 URL。 */
export function safeLink(value: string): string | null {
  if (/^\/(?!\/)/.test(value) && !value.includes('\\')) return value
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null } catch { return null }
}
