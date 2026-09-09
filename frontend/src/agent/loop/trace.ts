import type { Data, LoopFrame } from '../../api/agentLoopTypes.ts'
import { identity } from './reducer.ts'
/** 轨迹源 seq 从 0 开始；持久诊断与语义 cursor 分开保存。 */
export interface TraceState { events: Data[]; seen: Set<number>; seq: number; catalog: Data | null; denied: boolean }
export function createTrace(): TraceState { return { events: [], seen: new Set(), seq: -1, catalog: null, denied: false } }
export function applyTrace(state: TraceState, frame: LoopFrame): void {
  if (state.denied) return
  if (frame.type === 'schema.catalog') state.catalog = frame.data
  if (frame.type !== 'trace.event') return
  const event = frame.data.event
  if (!Number.isSafeInteger(event?.seq) || event.seq < 0 || state.seen.has(event.seq)) return
  state.seen.add(event.seq); state.seq = Math.max(state.seq, event.seq)
  state.events.push(event)
}
/** 复制前再次深层脱敏，不保存 nonce、spec_hash、完整请求头或隐藏状态。 */
export function safePacket(value: any): any {
  if (Array.isArray(value)) return value.map(safePacket)
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !/^(nonce|spec_hash|raw|header|headers|system|system_segments|messages|protocol_state|provider_options|reasoning_content|reasoning|reasoning_preview)$/i.test(key))
    .map(([key, item]) => [key, /authorization|api[_-]?key|cookie|password|secret|credential|(^|[_-])token($|[_-])/i.test(key) ? '[已脱敏]' : safePacket(item)]))
  return typeof value === 'string' ? value.replace(/\bbearer\s+[a-z0-9._~+/=-]{8,}|\bsk-[a-z0-9._-]{8,}/gi, '[已脱敏]') : value
}
/** 本地 JSON Pointer 引用解析，未知引用保留提示，不向任意地址请求 Schema。 */
export function schemaRef(root: Data, ref: string): any {
  if (!ref.startsWith('#/')) return null
  return ref.slice(2).split('/').reduce((value: any, part) => value?.[part.replace(/~1/g, '/').replace(/~0/g, '~')], root) ?? null
}
export function category(type: string): string {
  // 按事件命名空间分类，approval.requested 的后缀不能误命中模型 request。
  const namespace = type.split(/[./]/)[0]
  if (['assistant', 'request', 'step'].includes(namespace)) return 'model'
  if (['tool', 'execution'].includes(namespace)) return 'tool'
  if (namespace === 'question') return 'question'
  if (['approval', 'task_confirmation'].includes(namespace)) return 'approval'
  if (namespace === 'task') return 'task'
  return 'lifecycle'
}

/** 每次模型请求和工具调用各占一个语义行，保留全部传输层供检查器关联。 */
export function semanticTraceRows(facts: LoopFrame[]): Array<LoopFrame & { layers: LoopFrame[] }> {
  const groups = new Map<string, LoopFrame & { layers: LoopFrame[] }>()
  for (const frame of facts) {
    const key = frame.type.startsWith('tool.') && frame.correlation.call_id ? `tool:${identity(frame, true)}`
      : frame.type.startsWith('assistant.') && frame.correlation.attempt_id ? `model:${identity(frame)}` : `cursor:${frame.cursor}`
    const old = groups.get(key)
    if (old) {
      old.layers.push(frame)
      old.data = { ...old.data, ...frame.data, display: { ...old.data.display, ...frame.data.display } }
    } else groups.set(key, { ...frame, data: { ...frame.data }, layers: [frame] })
  }
  return [...groups.values()]
}
