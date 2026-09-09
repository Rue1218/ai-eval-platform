/** 浏览器随机源；请求标识用于幂等关联，不作为鉴权凭据。 */
type RequestIdRandom = { randomUUID?: () => string; getRandomValues?: (values: Uint8Array) => Uint8Array }

/** 普通 HTTP 页面没有 randomUUID，使用仍可用的安全随机字节生成 UUID v4。 */
export function createRequestId(random: RequestIdRandom | undefined = globalThis.crypto): string {
  if (typeof random?.randomUUID === 'function') {
    try { return random.randomUUID() } catch { /* 浏览器拒绝调用时继续使用安全随机字节。 */ }
  }
  if (typeof random?.getRandomValues !== 'function') throw new Error('浏览器不支持安全随机请求标识')
  const bytes = random.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
