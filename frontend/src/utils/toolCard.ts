/** 成功后保持展开的工具：音频播放/转写、文件读取与沙箱命令。 */
const KEEP_OPEN_TOOLS = new Set([
  'audio.speech_recognition',
  'audio.speech_synthesis',
  'audio.voiceclone',
  'read',
  'bash',
])

/** 判断 ToolCard 在 ok 后是否默认保持展开。 */
export function shouldKeepToolCardOpen(name: string): boolean {
  return KEEP_OPEN_TOOLS.has(name)
}

/** 可按 call_id 关联的工具块；直播与历史回放共用同一套匹配规则。 */
export interface ToolMatchable {
  type?: string
  callId?: string
  tool?: string
  status?: string
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
      (item) => item.type === 'tool' && item.callId === callId && item.status === 'pending',
    )
  }
  return reversed.find(
    (item) => item.type === 'tool' && item.tool === name && item.status === 'pending',
  )
}
