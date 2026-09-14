import type { LoopUi } from '../../api/agentLoopTypes.ts'

/** 合并当前身份/会话的能力请求；不缓存权限响应，也不推迟首次加载。 */
export function createAgentUiRefresh(
  load: (sessionId: string, signal: AbortSignal) => Promise<LoopUi>,
  apply: (data: LoopUi) => void,
  fail: () => void,
) {
  let current: { key: string; controller: AbortController; done: Promise<void> } | undefined
  let lastSuccess: { key: string; at: number } | undefined
  /** 取消旧作用域；即使服务端继续响应，也不能把旧权限写回当前页面。 */
  function cancel() { current?.controller.abort(); current = undefined }
  function refresh(userId: string, sessionId: string, focus = false): Promise<void> {
    const key = JSON.stringify([userId, sessionId])
    if (current?.key === key) return current.done
    cancel()
    // 仅抑制刚完成请求后的重复聚焦；定时刷新和会话切换仍立即读取。
    if (focus && lastSuccess?.key === key && Date.now() - lastSuccess.at < 1000) return Promise.resolve()
    const controller = new AbortController()
    const request = { key, controller, done: Promise.resolve() }
    current = request
    request.done = load(sessionId, controller.signal).then(data => {
      if (current !== request) return
      apply(data)
      lastSuccess = { key, at: Date.now() }
    }).catch(() => {
      if (current === request && !controller.signal.aborted) fail()
    }).finally(() => { if (current === request) current = undefined })
    return request.done
  }
  return { refresh, cancel }
}
