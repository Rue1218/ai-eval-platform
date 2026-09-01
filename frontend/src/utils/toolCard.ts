/** 成功后保持展开的工具：音频播放/转写、文件读取、沙箱命令与任务清单。 */
const KEEP_OPEN_TOOLS = new Set([
  'audio.speech_recognition',
  'audio.speech_synthesis',
  'audio.voiceclone',
  'read',
  'bash',
  'task',
  'TaskCreate',
  'TaskGet',
  'TaskUpdate',
  'TaskList',
  'ask_user_question',
  'task.create',
  'task.status',
  'task.cancel',
])

/** 判断 ToolCard 在 ok 后是否默认保持展开。 */
export function shouldKeepToolCardOpen(name: string): boolean {
  return KEEP_OPEN_TOOLS.has(name)
}

/** 尚未终态的工具卡：执行中或危险命令等待确认，确认后的 progress/result 必须仍能回填。 */
const OPEN_TOOL_STATUSES = new Set(['pending', 'awaiting_approval'])

/** 可按 call_id 关联的工具块；直播与历史回放共用同一套匹配规则。 */
export interface ToolMatchable {
  type?: string
  callId?: string
  tool?: string
  status?: string
}

/** 判断工具卡是否仍等待 progress / tool_result 回填。 */
export function isOpenToolStatus(status: string | undefined): boolean {
  return OPEN_TOOL_STATUSES.has(status || '')
}

/** 按 call_id 查找待完成工具；历史事件缺失该字段时才兼容旧的同名回退。 */
export function findPendingToolItem<T extends ToolMatchable>(
  items: T[],
  name: unknown,
  callId?: unknown,
): T | undefined {
  const reversed = [...items].reverse()
  if (typeof callId === 'string' && callId) {
    return reversed.find(
      (item) => item.type === 'tool' && item.callId === callId && isOpenToolStatus(item.status),
    )
  }
  return reversed.find(
    (item) => item.type === 'tool' && item.tool === name && isOpenToolStatus(item.status),
  )
}
