import type { Attempt, LoopRecord, LoopUsage, ToolRun } from '../../api/agentLoopTypes.ts'

export interface TurnSummary {
  turnKey: string
  totalTokens: number | null
  totalLatencyMs: number | null
  text: string
  representativeRow: LoopRecord
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
  if ((row as any).turn_id) return `turn_id:${(row as any).turn_id}`
  if ((row as any).turn !== undefined) return `turn:${(row as any).turn}`
  return `key:${row.key}`
}

export interface CalculateTurnSummariesOptions {
  activeTurnId?: string | null
  isBusy?: boolean
  sessionId?: string
}

/**
 * 遍历会话记录，计算每轮对话的聚合指标，并在该轮对话结束时将摘要绑定至该轮最后一行记录。
 * 顺序：复制、重新生成、引用记忆、token消耗、用时。
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

    const text = attempts
      .map(a => (typeof a.text === 'string' ? a.text.trim() : ''))
      .filter(Boolean)
      .join('\n\n')

    const lastRow = turnRows[turnRows.length - 1]
    const representativeRow = attempts[attempts.length - 1] || lastRow

    result.set(lastRow.key, {
      turnKey,
      totalTokens,
      totalLatencyMs,
      text,
      representativeRow,
    })
  }

  return result
}
