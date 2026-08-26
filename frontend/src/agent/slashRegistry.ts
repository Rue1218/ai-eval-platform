/**
 * 最小会话控制命令。业务斜杠与资产查询斜杠已移除，避免抢占模型路由。
 * 命令清单与后端 /help 帮助文本（app/agent/routing.py HELP_TEXT）保持一致：
 * /help /stop /compact /cancel /stress 均已开放。
 */

export interface SlashCommandDef {
  name: string
  hint: string
  group: 'order' | 'control' | 'readonly' | 'system'
  enabled: boolean
  reason?: string
}

export const SYSTEM_SLASH_COMMANDS: SlashCommandDef[] = [
  { name: 'help', hint: '查看帮助', group: 'system', enabled: true },
  { name: 'stop', hint: '停止本轮生成', group: 'control', enabled: true },
  { name: 'compact', hint: '压缩本会话模型窗口', group: 'control', enabled: true },
  { name: 'cancel', hint: '取消本会话未完成任务', group: 'control', enabled: true },
  { name: 'stress', hint: '先评后压确认卡', group: 'order', enabled: true },
]
