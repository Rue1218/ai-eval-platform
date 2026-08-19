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
