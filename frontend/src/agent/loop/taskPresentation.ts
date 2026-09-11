import type { Data, LoopRecord, ToolRun } from '../../api/agentLoopTypes.ts'

/** 三层工具名与后端 task_contract.py 同步；未知名称绝不推断为 Task 工具。 */
export const taskToolAliases: Record<string, string> = {
  'task.create': 'task.create',
  'task.status': 'task.status',
  'task.cancel': 'task.cancel',
  platform_task_create: 'task.create',
  platform_task_status: 'task.status',
  platform_task_cancel: 'task.cancel',
  'platform.tasks.task.create': 'task.create',
  'platform.tasks.task.status': 'task.status',
  'platform.tasks.task.cancel': 'task.cancel',
}
const registeredTaskToolNames = new Set(['task.create', 'task.status', 'task.cancel'])

/** 将后端显式登记的别名归一为页面展示名。 */
export function canonicalTaskToolName(name: string): string {
  return taskToolAliases[name] || name
}

/** 仅已登记的三种 Task 工具使用专属卡片，普通工具继续走通用工具卡。 */
export function isTaskTool(name: string): boolean {
  return registeredTaskToolNames.has(canonicalTaskToolName(name))
}

/** 工具操作文案来自短名，避免把模型 wire 名或 MCP 全名泄露进主要界面。 */
export const taskActionLabels: Record<string, string> = {
  'task.create': '创建评测任务',
  'task.status': '查询任务状态',
  'task.cancel': '取消评测任务',
}

/** Task 状态文案与 Worker 持久事件保持同源，不以进度百分比合成终态。 */
export const taskStatusLabels: Record<string, string> = {
  awaiting_case_confirm: '等待用例确认',
  queued: '排队中',
  running: '执行中',
  succeeded: '已完成',
  failed: '执行失败',
  cancelled: '已取消',
}

/** 卡片仅消费已脱敏的展示预览；解析失败时仍可使用参数与 Worker 事实。 */
function parsePreview(value: unknown): Data {
  if (typeof value !== 'string' || !value.trim()) return {}
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Data : {}
  } catch {
    return {}
  }
}

/** 空串、对象或数组都不是可信任务 ID，避免把展示文本错误关联到另一张任务卡。 */
function taskIdFrom(value: Data): string | null {
  return typeof value.task_id === 'string' && value.task_id.trim() ? value.task_id : null
}

/** Worker 任务事实可以比工具结果更晚到达；合并时以实时事实覆盖陈旧快照。 */
export interface TaskCardSnapshot {
  action: string
  taskId: string | null
  kind: string | null
  status: string | null
  progress: Data | null
  reportId: string | null
  message: string | null
}

/** 组合调用安全预览与关联 task.* 事实，供专属卡片显示真实状态。 */
export function taskCardSnapshot(tool: ToolRun, task: LoopRecord | null | undefined): TaskCardSnapshot {
  const argumentsPreview = parsePreview(tool.display.arguments_preview)
  const resultPreview = parsePreview(tool.display.result_preview)
  const taskData = task && typeof task === 'object' ? task as Data : {}
  const progress = taskData.progress && typeof taskData.progress === 'object' && !Array.isArray(taskData.progress)
    ? taskData.progress as Data
    : resultPreview.progress && typeof resultPreview.progress === 'object' && !Array.isArray(resultPreview.progress)
      ? resultPreview.progress as Data
      : null
  const message = typeof progress?.message === 'string'
    ? progress.message
    : typeof resultPreview.message === 'string'
      ? resultPreview.message
      : typeof taskData.message === 'string'
        ? taskData.message
        : null
  return {
    action: canonicalTaskToolName(tool.name),
    taskId: taskIdFrom(taskData) || taskIdFrom(resultPreview) || taskIdFrom(argumentsPreview),
    kind: typeof taskData.kind === 'string' ? taskData.kind : typeof resultPreview.kind === 'string' ? resultPreview.kind : null,
    status: typeof taskData.status === 'string' ? taskData.status : typeof resultPreview.status === 'string' ? resultPreview.status : null,
    progress,
    reportId: typeof taskData.report_id === 'string' ? taskData.report_id : typeof resultPreview.report_id === 'string' ? resultPreview.report_id : null,
    message,
  }
}

/** 非法、缺失和越界进度均不渲染为完成，防止视觉状态先于 Worker 终态。 */
export function taskProgressPercent(progress: Data | null): number | null {
  const value = progress?.percent
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return Math.min(100, Math.max(0, value))
}
