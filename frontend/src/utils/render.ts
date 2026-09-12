/**
 * 工作台展示辅助（Datasets 与 Cases 共用）。
 *
 * 收敛前 ``renderIcon`` / ``escapeHtml`` / ``escapeRegex`` 在两个工作台页面
 * 内逐字重复实现；此处为唯一事实源。
 */
import { h } from 'vue'

/**
 * 构造 14×14 的 stroke 风格内联 SVG 图标渲染函数。
 *
 * @param pathD 单条或多条 path 的 d 属性
 * @param strokeColor 描边颜色，缺省继承 currentColor
 */
export function renderIcon(pathD: string | string[], strokeColor?: string) {
  return () =>
    h(
      'svg',
      {
        width: 14,
        height: 14,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: strokeColor || 'currentColor',
        strokeWidth: 2,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        style: { display: 'inline-block', verticalAlign: '-2px', marginRight: '6px' },
      },
      Array.isArray(pathD) ? pathD.map(p => h('path', { d: p })) : [h('path', { d: pathD })],
    )
}

/** 转义 HTML 特殊字符，防止 v-html 注入。 */
export function escapeHtml(str: string): string {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** 转义正则元字符，用于把用户输入安全地拼进 RegExp。 */
export function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
