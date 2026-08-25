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
