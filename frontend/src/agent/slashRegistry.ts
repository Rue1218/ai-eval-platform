/**
 * 最小会话控制命令。业务斜杠与资产查询斜杠已移除，避免抢占模型路由。
 */

export interface SlashCommandDef {
  name: string
  hint: string
  group: 'order' | 'control' | 'readonly' | 'system'
  enabled: boolean
  reason?: string
}

export const SYSTEM_SLASH_COMMANDS: SlashCommandDef[] = [
  { name: 'stop', hint: '停止本轮生成', group: 'control', enabled: true },
  { name: 'compact', hint: '压缩本会话模型窗口', group: 'control', enabled: true },
]
