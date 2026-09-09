import type { Attempt, Connection, Data, InteractionRecord, LoopFrame, LoopRecord, ToolRun } from '../../api/agentLoopTypes.ts'

/** 一个会话独占三套游标；持久事实不受瞬态诊断缓冲大小限制。 */
export interface LoopState {
  sessionId: string; cursor: number; connection: Connection; ready: boolean; activeTurn: string | null
  phase: string; cancelling: boolean; error: string; controlled: boolean
  messages: Record<string, LoopRecord>; attempts: Record<string, Attempt>; tools: Record<string, ToolRun>
  interactions: Record<string, InteractionRecord>; tasks: Record<string, LoopRecord>; executions: Record<string, LoopRecord>
  turns: Record<string, LoopRecord>; facts: LoopFrame[]; receipts: Record<string, LoopFrame>; title?: string
}
/** 新建空会话时 cursor 必须从零开始，禁止仅从 localStorage 恢复游标。 */
export function createLoopState(sessionId: string): LoopState {
  return { sessionId, cursor: 0, connection: 'connecting', ready: false, activeTurn: null, phase: 'idle',
    cancelling: false, error: '', controlled: false, messages: {}, attempts: {}, tools: {}, interactions: {},
    tasks: {}, executions: {}, turns: {}, facts: [], receipts: {} }
}
/** 身份包含会话、回合、attempt、call，工具重名或 call_id 跨轮复用均不冲突。 */
export function identity(frame: Pick<LoopFrame, 'session_id' | 'correlation'>, tool = false): string {
  const c = frame.correlation
  return JSON.stringify([frame.session_id, c.turn_id ?? c.turn, c.attempt_id, ...(tool ? [c.call_id] : [])])
}
function record(frame: LoopFrame, key: string): LoopRecord {
  return { key, first_cursor: frame.cursor ?? Number.MAX_SAFE_INTEGER, correlation: { ...frame.correlation }, event: frame.type }
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
    if (kind === 'assistant.text.delta') { a.text += d.text ?? ''; state.phase = 'answering' }
    if (kind === 'assistant.reasoning.delta') { a.reasoning += d.text ?? ''; state.phase = 'thinking' }
    return 'applied'
  }
  if (kind.startsWith('command.') && frame.request_id) state.receipts[frame.request_id] = frame
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
  return state
}
/** 消息、模型 attempt 和工具各自只出现一次，按首个持久位置展示。 */
export function conversationRows(state: LoopState): LoopRecord[] {
  return [...Object.values(state.messages), ...Object.values(state.attempts), ...Object.values(state.tools)]
    .sort((a, b) => a.first_cursor - b.first_cursor)
}
