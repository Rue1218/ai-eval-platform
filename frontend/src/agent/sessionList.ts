/**
 * Agent 会话列表派生逻辑：状态点样式与提示、状态筛选（2026-09-11 抽离）。
 *
 * 从 `Agent.vue` 抽出纯函数：loop 会话的状态点判定、悬停提示、
 * 筛选文案与过滤。组件内保留包装（读取响应式依赖），渲染行为不变。
 */

/** loop 会话状态点输入：只取判定所需字段，避免依赖整个 store（兼容 LoopState）。 */
export interface LoopDotInput {
  connection?: string
  activeTurn?: unknown
  /** 任务表：仅读取 status 字段，兼容 LoopState.tasks（LoopRecord）。 */
  tasks?: Record<string, unknown>
  phase?: string
}

/** 进行中的任务状态（含等待用例确认）；终态不在此列。 */
const RUNNING_TASK_STATUSES = ['running', 'queued', 'awaiting_case_confirm']

/** D5 状态点多态：loop 会话（engine_version=agent_loop_v2）。 */
export function loopSessionDot(value: LoopDotInput | undefined, activeTaskStatus?: string): string {
  // 无 store 状态时仅按快照 active_task 判断（原实现只认 running/queued）。
  if (!value) return ['running', 'queued'].includes(activeTaskStatus || '') ? 'running' : 'ready'
  if (value.connection !== 'online') return 'offline'
  if (
    value.activeTurn
    || Object.values(value.tasks || {}).some(
      task => RUNNING_TASK_STATUSES.includes((task as { status?: string } | undefined)?.status || ''),
    )
  ) return 'running'
  return value.phase === 'error' ? 'failed' : value.phase === 'completed' ? 'succeeded' : 'ready'
}

/** 状态点悬停提示：loop 会话。 */
export function loopSessionTooltip(value: LoopDotInput | undefined): string {
  if (!value) return 'AgentLoop 会话'
  if (value.connection !== 'online') return '连接中断，状态待同步'
  return value.activeTurn ? 'Agent 回合进行中' : 'Agent 回合已结束；Worker 状态独立'
}

/** 状态筛选展示文案：all | running | ready | succeeded | failed。 */
export function sessionStatusFilterLabel(key: string): string {
  switch (key) {
    case 'running': return '进行中'
    case 'ready': return '就绪'
    case 'succeeded': return '成功'
    case 'failed': return '失败'
    default: return '状态'
  }
}

/** 按状态点筛选会话；'all' 原样返回（不复制）。 */
export function filterSessionsByStatus<T>(sessions: T[], filter: string, dotOf: (session: T) => string): T[] {
  return filter === 'all' ? sessions : sessions.filter(session => dotOf(session) === filter)
}
