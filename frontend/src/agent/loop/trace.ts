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
  // 参考页只有四类业务筛选；问答/规格确认属于授权，任务/执行属于工具工作。
  const namespace = type.split(/[./]/)[0]
  if (['assistant', 'request'].includes(namespace)) return 'model'
  if (['tool', 'execution', 'task'].includes(namespace)) return 'tool'
  if (['approval', 'question', 'task_confirmation'].includes(namespace)) return 'approval'
  return 'lifecycle'
}

export type SemanticTraceRow = LoopFrame & { layers: LoopFrame[] }

/** 请求快照与助手提交分别成行；同一工具或授权生命周期仍聚合为一条业务记录。 */
export function semanticTraceRows(facts: LoopFrame[]): SemanticTraceRow[] {
  const groups = new Map<string, LoopFrame[]>()
  for (const frame of facts) {
    const interactionId = typeof frame.data.interaction_id === 'string' ? frame.data.interaction_id : ''
    const key = frame.type.startsWith('tool.') && frame.correlation.call_id ? `tool:${identity(frame, true)}`
      : /^(approval|question|task_confirmation)\./.test(frame.type) && (interactionId || frame.correlation.call_id)
        ? `approval:${frame.type.split('.')[0]}:${interactionId || identity(frame, true)}`
        : frame.type === 'assistant.start' && frame.correlation.attempt_id ? `request:${identity(frame)}`
          : /^assistant\.(message|end)$/.test(frame.type) && frame.correlation.attempt_id ? `assistant:${identity(frame)}`
            : `cursor:${frame.cursor}`
    const layers = groups.get(key) ?? []
    layers.push(frame)
    groups.set(key, layers)
  }
  const preferred = ['assistant.message', 'tool.call', 'approval.requested', 'question.requested',
    'task_confirmation.requested', 'turn.end', 'step.end']
  return [...groups.values()].map(layers => {
    const primary = preferred.map(type => layers.find(layer => layer.type === type)).find(Boolean) ?? layers[0]
    const data = layers.reduce<Data>((value, layer) => ({
      ...value, ...layer.data, display: { ...value.display, ...layer.data.display },
    }), {})
    return { ...primary, data, layers }
  }).sort((left, right) => (left.layers[0].cursor ?? 0) - (right.layers[0].cursor ?? 0))
}
