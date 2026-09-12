/**
 * 格式化与显示工具函数库（对齐产品契约与开发说明书）。
 */

/**
 * 统一耗时格式化函数（开发说明书 §16.7 冻结规则）
 * - < 1000ms 显示为整数毫秒，如 "45ms", "320ms"
 * - >= 1000ms 显示为秒（保留一位小数），如 "1.0s", "1.2s"
 * - 0ms 正常显示 "0ms"
 * - 无效或负数返回空字符串 ""
 *
 * @param ms 耗时毫秒数
 */
export function formatLatency(ms?: number | null): string {
  if (ms === undefined || ms === null || isNaN(ms) || ms < 0) {
    return ''
  }
  if (ms < 1000) {
    return `${Math.round(ms)}ms`
  }
  return `${(ms / 1000).toFixed(1)}s`
}

/**
 * 格式化文件大小
 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

/**
 * 完整日期时间（本地时区，zh-CN，24 小时制）。
 * 空值或无效日期返回 fallback（默认空字符串）。
 *
 * @param value ISO 时间字符串
 * @param fallback 空值/无效日期时的占位文案
 */
export function formatDateTime(value?: string | null, fallback = ''): string {
  if (!value) return fallback
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return fallback
  return date.toLocaleString('zh-CN', { hour12: false })
}

/**
 * 日期（本地时区，zh-CN，不含时分秒）。
 * 空值或无效日期返回 fallback（默认空字符串）。
 *
 * @param value ISO 时间字符串
 * @param fallback 空值/无效日期时的占位文案
 */
export function formatDate(value?: string | null, fallback = ''): string {
  if (!value) return fallback
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return fallback
  return date.toLocaleDateString('zh-CN')
}

/**
 * 紧凑文件大小（B/KB/MB/GB，≥10 取整，否则保留一位小数）。
 *
 * @param bytes 字节数
 */
export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
}
