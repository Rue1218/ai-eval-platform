import type { Attempt, LoopRecord, LoopUsage, ToolRun } from '../../api/agentLoopTypes.ts'

export interface TurnSummary {
  turnKey: string
  totalTokens: number | null
  totalLatencyMs: number | null
  /** 本轮最终可读回答；执行过程文字不能进入复制或引用记忆。 */
  summaryText: string
  /** 本轮最后一个未发起工具调用的助手输出，作为可操作的总结。 */
  summaryRow: Attempt
  /** 除总结外的助手尝试均为过程，供页面以 ReAct 过程样式呈现。 */
  processRows: Attempt[]
}

export function tokenValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0
}

export function answerTokens(row: LoopRecord): number | null {
  const usage = row.usage as LoopUsage | undefined
  if (!usage) return null
  const total = tokenValue(usage.total_tokens)
  return total > 0 ? total : tokenValue(usage.prompt_tokens) + tokenValue(usage.completion_tokens)
}

export function formatTokens(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}K`
  return String(Math.round(value))
}

export function formatDuration(value: unknown): string {
  const milliseconds = tokenValue(value)
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(milliseconds >= 10_000 ? 0 : 1)} s`
}

export function getTurnIdentifier(row: LoopRecord): string {
  if (row.correlation?.turn_id) return `turn_id:${row.correlation.turn_id}`
  if (row.correlation?.turn !== undefined) return `turn:${row.correlation.turn}`
  const legacy = row as { turn_id?: string; turn?: number }
  if (legacy.turn_id) return `turn_id:${legacy.turn_id}`
  if (legacy.turn !== undefined) return `turn:${legacy.turn}`
  return `key:${row.key}`
}

/** 工具调用由服务端持久投影，不能根据回答文字或 step 序号猜测过程状态。 */
function hasToolCalls(row: Attempt): boolean {
  return Array.isArray(row.tool_calls) && row.tool_calls.length > 0
}

export interface CalculateTurnSummariesOptions {
  activeTurnId?: string | null
  isBusy?: boolean
  sessionId?: string
}

/**
 * 遍历会话记录，计算每轮对话的聚合指标，并在该轮对话结束时将总结绑定至该轮最后一行记录。
 * 带工具调用的助手尝试以及总结前的任何助手尝试均为 ReAct 过程；仅最后一条不带工具调用的
 * 助手输出属于可复制、重新生成和引用记忆的总结。指标仍覆盖该轮全部模型尝试。
 */
export function calculateTurnSummaries(
  allRows: LoopRecord[],
  options: CalculateTurnSummariesOptions = {},
): Map<string, TurnSummary> {
  const result = new Map<string, TurnSummary>()
  if (!allRows.length) return result

  const turnMap = new Map<string, LoopRecord[]>()
  for (const row of allRows) {
    const turnKey = getTurnIdentifier(row)
    let list = turnMap.get(turnKey)
    if (!list) {
      list = []
      turnMap.set(turnKey, list)
    }
    list.push(row)
  }

  const { activeTurnId = null, isBusy = false, sessionId = '' } = options

  for (const [turnKey, turnRows] of turnMap.entries()) {
    const attempts = turnRows.filter((r): r is Attempt => r.role !== 'user' && !('status' in r && 'name' in r))
    if (!attempts.length) continue

    // 正在活跃运行中的轮次不展示结尾总结
    const isThisTurnActive = Boolean(
      activeTurnId && (
        turnRows.some(r =>
          (r.correlation?.turn_id && r.correlation.turn_id === activeTurnId)
          || (r.correlation?.turn !== undefined && `${sessionId}:${r.correlation.turn}` === activeTurnId)
          || (r.correlation?.turn !== undefined && String(r.correlation.turn) === activeTurnId)
        )
      )
    )
    if (isThisTurnActive) continue

    const allAttemptsEnded = attempts.every(a => a.ended)
    if (!allAttemptsEnded) continue

    const hasRunningTools = turnRows.some(r =>
      'status' in r && 'name' in r
      && ((r as ToolRun).status === 'running' || (r as ToolRun).status === 'pending' || (r as ToolRun).status === 'waiting_approval')
    )
    if (hasRunningTools) continue

    // 若这是最后一轮且全局仍在 busy 状态，则判定未结束
    const isLatestTurn = turnKey === getTurnIdentifier(allRows[allRows.length - 1])
    if (isLatestTurn && isBusy) continue

    let totalTokens: number | null = null
    let totalLatencyMs: number | null = null

    for (const a of attempts) {
      const tokens = answerTokens(a)
      if (tokens !== null) {
        totalTokens = (totalTokens ?? 0) + tokens
      }
      const lat = tokenValue(a.latency_ms)
      if (lat > 0) {
        totalLatencyMs = (totalLatencyMs ?? 0) + lat
      }
    }

    const lastRow = turnRows[turnRows.length - 1]
    // 只有最后一个已提交的助手输出且未发起工具调用才是本轮总结；若最后一步仍在调用工具或失败，
    // 不能回退到更早的过程文字并把它冒充总结。
    const summaryRow = attempts[attempts.length - 1]
    if (hasToolCalls(summaryRow) || summaryRow.outcome === 'failed' || summaryRow.error_code) continue
    const summaryText = typeof summaryRow.text === 'string' ? summaryRow.text.trim() : ''
    const processRows = attempts.filter(attempt => attempt.key !== summaryRow.key)

    result.set(lastRow.key, {
      turnKey,
      totalTokens,
      totalLatencyMs,
      summaryText,
      summaryRow,
      processRows,
    })
  }

  return result
}
