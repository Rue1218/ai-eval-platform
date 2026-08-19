/**
 * 系统斜杠 15 条本地表（开发说明书 §9）。
 * 自定义命令只请求 GET /api/slash-commands，禁止 localStorage / admin settings 合并。
 */

export interface SlashCommandDef {
  name: string
  hint: string
  group: 'order' | 'control' | 'readonly' | 'system'
  enabled: boolean
  reason?: string
}

export const SYSTEM_SLASH_COMMANDS: SlashCommandDef[] = [
  { name: 'benchmark', hint: '基准评测', group: 'order', enabled: true },
  { name: 'rag', hint: 'RAG 评测', group: 'order', enabled: false, reason: '将在知识库阶段启用' },
  { name: 'testcase', hint: '生成用例', group: 'order', enabled: true },
  { name: 'stress', hint: '先评后压', group: 'order', enabled: true },
  { name: 'cancel', hint: '取消本会话非终态任务', group: 'control', enabled: true },
  { name: 'rerun', hint: '拷贝最近任务配置为新确认卡', group: 'control', enabled: true },
  { name: 'stop', hint: '停止本轮生成', group: 'control', enabled: true },
  { name: 'new', hint: '新建空会话', group: 'control', enabled: true },
  { name: 'compact', hint: '压缩本会话模型窗口', group: 'control', enabled: true },
  { name: 'status', hint: '当前占槽 / 活动任务', group: 'readonly', enabled: true },
  { name: 'profiles', hint: '列出协议档', group: 'readonly', enabled: true },
  { name: 'datasets', hint: '列出数据集', group: 'readonly', enabled: true },
  { name: 'kb', hint: '列出知识库', group: 'readonly', enabled: false, reason: '将在知识库阶段启用' },
  { name: 'report', hint: '读取已有报告', group: 'readonly', enabled: false, reason: '报告解读将在 M4 接入' },
  { name: 'help', hint: '列出当前已启用命令', group: 'system', enabled: true },
]
