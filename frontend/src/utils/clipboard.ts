/**
 * 复制文本并兼容非安全上下文、嵌入式 WebView 等没有 Clipboard API 的环境。
 *
 * 首选异步 API；失败时只在用户点击的同步调用链中回退至 selection + execCommand，
 * 不会把文本写入页面状态或日志。
 */
export async function copyText(text: string): Promise<boolean> {
  if (!text) return false
  try {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 权限被拒绝时继续使用兼容回退，避免“复制”按钮形同虚设。
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;pointer-events:none;'
  document.body.appendChild(textarea)
  textarea.select()
  textarea.setSelectionRange(0, textarea.value.length)
  try {
    return document.execCommand('copy')
  } finally {
    textarea.remove()
  }
}
