import type { Attempt, Connection, Data, InteractionRecord, LoopFrame, LoopRecord, TaskPlanDisplay, ToolRun } from '../../api/agentLoopTypes.ts'

/** 一个会话独占三套游标；持久事实不受瞬态诊断缓冲大小限制。 */
export interface LoopState {
  sessionId: string; cursor: number; connection: Connection; ready: boolean; activeTurn: string | null
  phase: string; cancelling: boolean; error: string; controlled: boolean
  messages: Record<string, LoopRecord>; attempts: Record<string, Attempt>; tools: Record<string, ToolRun>
  interactions: Record<string, InteractionRecord>; tasks: Record<string, LoopRecord>; executions: Record<string, LoopRecord>
  turns: Record<string, LoopRecord>; facts: LoopFrame[]; receipts: Record<string, LoopFrame>; taskPlan: TaskPlanDisplay | null; title?: string
}
/** 新建空会话时 cursor 必须从零开始，禁止仅从 localStorage 恢复游标。 */
export function createLoopState(sessionId: string): LoopState {
  return { sessionId, cursor: 0, connection: 'connecting', ready: false, activeTurn: null, phase: 'idle',
    cancelling: false, error: '', controlled: false, messages: {}, attempts: {}, tools: {}, interactions: {},
    tasks: {}, executions: {}, turns: {}, facts: [], receipts: {}, taskPlan: null }
}
/** 身份包含会话、回合、attempt、call，工具重名或 call_id 跨轮复用均不冲突。 */
export function identity(frame: Pick<LoopFrame, 'session_id' | 'correlation'>, tool = false): string {
  const c = frame.correlation
  return JSON.stringify([frame.session_id, c.turn_id ?? c.turn, c.attempt_id, ...(tool ? [c.call_id] : [])])
}
function record(frame: LoopFrame, key: string): LoopRecord {
  return { key, first_cursor: frame.cursor ?? Number.MAX_SAFE_INTEGER, correlation: { ...frame.correlation }, event: frame.type, timestamp: frame.ts }
}
/** 流片段可能先于持久 start 到达，之后只校正首次顺序，不替换稳定对象。 */
function attemptFor(state: LoopState, frame: LoopFrame): Attempt {
  const key = identity(frame)
  const value = state.attempts[key] ??= { ...record(frame, key), text: '', reasoning: '', ended: false, chunks: {} }
  if (frame.cursor) value.first_cursor = Math.min(value.first_cursor, frame.cursor)
  return value
}
function toolFor(state: LoopState, frame: LoopFrame): ToolRun {
  const key = identity(frame, true)
  const value = state.tools[key] ??= { ...record(frame, key), name: frame.data.name || '未知工具', status: 'pending', display: {} }
  if (frame.cursor) value.first_cursor = Math.min(value.first_cursor, frame.cursor)
  return value
}
/** 只接受后端已验证并持久化的完整计划快照，拒绝工具调用草稿或畸形回放数据。 */
function taskPlanFromFrame(data: Data): TaskPlanDisplay | null {
  const raw = data.plan
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const plan = raw as Data
  const goal = typeof plan.goal === 'string' ? plan.goal.trim() : ''
  const description = typeof plan.description === 'string' ? plan.description.trim() : goal
  if (!goal || !Array.isArray(plan.steps) || plan.steps.length < 1 || plan.steps.length > 12) return null
  const seen = new Set<string>()
  const steps: TaskPlanDisplay['steps'] = []
  for (const rawStep of plan.steps) {
    if (!rawStep || typeof rawStep !== 'object' || Array.isArray(rawStep)) return null
    const step = rawStep as Data
    const title = typeof step.title === 'string' ? step.title.trim() : ''
    const status = step.status
    if (!title || title.length > 300 || seen.has(title.toLocaleLowerCase()) || !['pending', 'in_progress', 'completed'].includes(String(status))) return null
    seen.add(title.toLocaleLowerCase())
    steps.push({ title, status: status as TaskPlanDisplay['steps'][number]['status'] })
  }
  const counts = {
    pending: steps.filter(step => step.status === 'pending').length,
    in_progress: steps.filter(step => step.status === 'in_progress').length,
    completed: steps.filter(step => step.status === 'completed').length,
  }
  if (counts.in_progress > 1) return null
  return { goal, description, steps, counts }
}
/** 成功应用连续事实才提交 cursor；restricted 占位也消费序号。 */
export function applyFrame(state: LoopState, frame: LoopFrame): 'applied' | 'duplicate' | 'gap' {
  if (frame.protocol_version !== 2) throw new Error('不支持的 Agent 协议版本')
  if (frame.session_id && frame.session_id !== state.sessionId) throw new Error('会话身份不匹配')
  if (frame.durability === 'persistent') {
    if (!Number.isSafeInteger(frame.cursor) || frame.cursor! < 1) throw new Error('无效持久游标')
    if (frame.cursor! <= state.cursor) return 'duplicate'
    if (frame.cursor !== state.cursor + 1) return 'gap'
  }
  const d = frame.data, c = frame.correlation, kind = frame.type
  const turnId = c.turn_id ?? (c.turn ? `${state.sessionId}:${c.turn}` : '')
  if (frame.durability === 'transient') {
    if (!c.attempt_id || !turnId || !kind.startsWith('assistant.')) return 'duplicate'
    if (state.turns[turnId]?.event === 'turn.end') return 'duplicate'
    const a = attemptFor(state, frame)
    if (a.ended || !Number.isSafeInteger(d.chunk_index) || d.chunk_index < 0) return 'duplicate'
    if (d.chunk_index <= (a.chunks[kind] ?? -1)) return 'duplicate'
    a.chunks[kind] = d.chunk_index
    if (kind === 'assistant.text.delta') {
      a.text += d.text ?? ''
      if (Array.isArray(d.text_parts)) a.text_parts = d.text_parts
      else if (Number.isSafeInteger(d.output_index) && d.output_index >= 0) {
        a.text_parts ??= []
        let part = a.text_parts.find((item: Data) => item.output_index === d.output_index)
        if (!part) {
          part = {output_index:d.output_index,phase:d.phase ?? null,text:''}
          a.text_parts.push(part)
        }
        part.text += d.text ?? ''
        if (d.phase != null) part.phase = d.phase
      }
      state.phase = 'answering'
    }
    if (kind === 'assistant.reasoning.delta') { a.reasoning += d.text ?? ''; state.phase = 'thinking' }
    return 'applied'
  }
  if (kind.startsWith('command.') && frame.request_id) state.receipts[frame.request_id] = frame
  if (kind === 'subscribed') {
    state.controlled = Boolean(
      d.controller?.active
      && (d.controller?.owned_by_connection ?? d.controller?.owned_by_actor),
    )
  }
  if (kind === 'replay.completed') state.ready = true
  if (kind === 'user.message') {
    const key = d.client_message_id || `user:${frame.cursor}`
    state.messages[key] = { ...record(frame, key), ...d, role: 'user' }
  }
  if (kind === 'turn.start' || kind === 'turn.end') {
    const value = state.turns[turnId] ??= record(frame, turnId)
    Object.assign(value, d, { event: kind })
    if (kind === 'turn.start') { state.activeTurn = turnId; state.phase = 'model'; state.error = '' }
    else {
      if (state.activeTurn === turnId) { state.activeTurn = null; state.cancelling = false; state.controlled = false; state.phase = d.reason || 'completed' }
      for (const a of Object.values(state.attempts)) if (a.correlation.turn_id === turnId || a.correlation.turn === c.turn) a.ended = true
      for (const i of Object.values(state.interactions)) if (i.correlation.turn_id === turnId) { i.resolved = true; delete i.nonce; delete i.spec_hash }
    }
  }
  if (kind.startsWith('assistant.') && c.attempt_id) {
    const a = attemptFor(state, frame)
    Object.assign(a, d, { event: kind, correlation: { ...a.correlation, ...c } })
    // 增量可先于持久 start 到达，迟到的开始事件不能覆盖已经观测的输出状态。
    if (kind === 'assistant.start' && !a.ended) state.phase = a.text ? 'answering' : a.reasoning ? 'thinking' : 'model'
    if (kind === 'assistant.message') { a.text = d.content ?? ''; a.reasoning = d.reasoning_preview ?? ''; a.ended = true }
    if (kind === 'assistant.end') a.ended = true
    if (kind === 'assistant.retry') state.phase = 'retry_wait'
  }
  if (kind.startsWith('tool.') && c.call_id) {
    const t = toolFor(state, frame)
    const display = { ...t.display, ...d.display }
    Object.assign(t, d, { display, event: kind })
    if (kind === 'tool.dispatch') { t.status = 'running'; state.phase = 'tools' }
  }
  if (kind === 'task_plan.updated') {
    // 计划只能由成功 task 的同事务事件更新，抽屉不再消费 tool.call/result 的草稿。
    const plan = taskPlanFromFrame(d)
    if (plan) state.taskPlan = plan
  }
  if (/^(approval|question|task_confirmation)\.(requested|resolved)$/.test(kind) && c.call_id) {
    const tool = toolFor(state, frame)
    const key = d.interaction_id || `${tool.key}:${kind.split('.')[0]}:restricted`
    const i = state.interactions[key] ??= { ...record(frame, key), interaction_id: key, kind: kind.split('.')[0], resolved: false }
    Object.assign(i, d, { event: kind })
    if (kind.endsWith('.resolved')) { i.resolved = true; i.submitting = false; delete i.nonce; delete i.spec_hash; state.phase = 'tools' }
    else { tool.status = 'waiting_approval'; state.phase = 'waiting_interaction'; if (d.restricted) { delete i.nonce; delete i.spec_hash } }
  }
  if (kind.startsWith('task.') && c.task_id) {
    const value = state.tasks[c.task_id] ??= record(frame, c.task_id)
    // report/100% progress 不能覆盖持久 task.end，也不能自己合成 succeeded。
    const terminal = value.event === 'task.end'
    const status = value.status
    Object.assign(value, d, { event: terminal ? 'task.end' : kind })
    if (terminal) value.status = status
  }
  if (kind.startsWith('execution.') && d.execution_id) {
    state.executions[d.execution_id] = { ...record(frame, d.execution_id), ...d }
  }
  if (kind === 'runtime.error') state.error = d.message || '回合运行失败'
  if (kind === 'session.updated' && d.title) state.title = d.title
  if (frame.durability === 'persistent') { state.facts.push(frame); state.cursor = frame.cursor! }
  return 'applied'
}
/** 快照在 H 原子替换，timeline 是唯一事实源，不再追加旧 messages 数组。 */
export function restoreSnapshot(sessionId: string, cursor: number, snapshot: Data): LoopState {
  if (!Number.isSafeInteger(cursor) || cursor < 0 || !Array.isArray(snapshot.timeline)) throw new Error('快照缺少已授权时间线')
  const state = createLoopState(sessionId)
  for (const frame of snapshot.timeline as LoopFrame[]) {
    if (frame.durability !== 'persistent' || !Number.isSafeInteger(frame.cursor) || frame.cursor! <= state.cursor || frame.cursor! > cursor) throw new Error('快照游标乱序或超出高水位')
    // 保留窗口可能缺旧号：快照已由同一事务验证，按保留的首次事实重建。
    state.cursor = frame.cursor! - 1
    applyFrame(state, frame)
  }
  state.cursor = cursor
  state.controlled = Boolean(
    snapshot.controller?.active
    && (snapshot.controller?.owned_by_connection ?? snapshot.controller?.owned_by_actor),
  )
  return state
}
/** 消息、模型 attempt 和工具各自只出现一次，按首个持久位置展示。 */
export function conversationRows(state: LoopState): LoopRecord[] {
  return [...Object.values(state.messages), ...Object.values(state.attempts), ...Object.values(state.tools)]
    .sort((a, b) => a.first_cursor - b.first_cursor)
}
