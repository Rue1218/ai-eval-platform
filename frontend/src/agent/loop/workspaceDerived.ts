/**
 * AgentWorkspace 派生逻辑：纯函数抽离（2026-09-11）。
 *
 * 从 `AgentWorkspace.vue` 抽出可单测的派生计算：轮次助手分组、会话指标聚合、
 * 草稿选择回落。组件内保留 computed 包装，渲染行为不变。
 */

import type {
  Attempt,
  ConversationMetrics,
  LoopAgent,
  LoopProfile,
  LoopRecord,
  LoopUi,
} from '../../api/agentLoopTypes.ts'
import { getTurnIdentifier, tokenValue } from './turnSummary.ts'

/**
 * 每轮首条助手记录的 key（用于「续写」样式：非首条不重复展示助手头）。
 * 用户消息与工具卡片不参与分组；同一轮内首条命中即固定。
 */
export function assistantKeysByTurn(rows: LoopRecord[]): Map<string, string> {
  const map = new Map<string, string>()
  for (const row of rows) {
    const isAssistant = row.role !== 'user' && !('status' in row && 'name' in row)
    if (!isAssistant) continue
    const turnKey = getTurnIdentifier(row)
    if (!map.has(turnKey)) map.set(turnKey, row.key)
  }
  return map
}

/** 判定该助手记录是否为本轮首条；轮次无助手记录时视为首条（正常展示）。 */
export function firstAssistantInTurn(row: LoopRecord, firstKeyByTurn: Map<string, string>): boolean {
  const firstKey = firstKeyByTurn.get(getTurnIdentifier(row))
  return !firstKey || firstKey === row.key
}

/**
 * 仅聚合已提交的上游 usage；缺字段代表上游未返回，不能当作零或自行估算。
 * 模型吞吐仅在输入、输出、耗时均有效时累计（避免半量数据拉低均值）；
 * 缓存命中率仅在出现任一缓存字段且输入有效时给出，否则为 null。
 */
export function conversationMetricsFrom(attempts: Record<string, Attempt> | undefined): ConversationMetrics {
  let inputTokens = 0
  let outputTokens = 0
  let modelLatencyMs = 0
  let cacheReadTokens = 0
  let hasCacheUsage = false
  for (const attempt of Object.values(attempts || {})) {
    const usage = attempt.usage
    if (!usage) continue
    const input = tokenValue(usage.prompt_tokens)
    const output = tokenValue(usage.completion_tokens)
    inputTokens += input
    outputTokens += output
    const latency = tokenValue(attempt.latency_ms) || tokenValue((usage as { latency_ms?: unknown })?.latency_ms)
    if (input > 0 && output > 0 && latency > 0) modelLatencyMs += latency
    const cached = tokenValue(usage.cache_read_input_tokens) || tokenValue(usage.cached_tokens)
    if (
      cached > 0
      || typeof usage.cache_read_input_tokens === 'number'
      || typeof usage.cached_tokens === 'number'
    ) {
      hasCacheUsage = true
      cacheReadTokens += cached
    }
  }
  return {
    inputTokens,
    outputTokens,
    outputTokensPerSecond: outputTokens > 0 && modelLatencyMs > 0 ? outputTokens / (modelLatencyMs / 1000) : null,
    cacheHitRate: hasCacheUsage && inputTokens > 0 ? (cacheReadTokens / inputTokens) * 100 : null,
  }
}

/** 草稿协议档可独立于平台默认项选择；后端在提交时再次校验。 */
export function pickProfile(ui: LoopUi | null | undefined, profileId: string): LoopProfile | null {
  return ui?.profiles.find(item => item.id === profileId) || ui?.profile || null
}

/** 草稿专家可独立选择；未知 ID 回落列表默认项（后端提交时复核）。 */
export function pickAgent(ui: LoopUi | null | undefined, agentId: string): LoopAgent | null {
  const list = ui?.agents || []
  return list.find(item => item.id === agentId) || list.find(item => item.default) || null
}
