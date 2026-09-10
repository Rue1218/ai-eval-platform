import type { GlobalThemeOverrides } from 'naive-ui'

// Naive UI 主题覆盖（设计规范 §8.4）：令牌优先，主色 = --accent-ai，精准对齐字阶与字体栈
export const themeOverrides: GlobalThemeOverrides = {
  common: {
    // 与 CSS 全局令牌保持同一字体回退顺序，确保 Naive UI 浮层和表单也一致清晰。
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif',
    fontFamilyMono: '"Cascadia Mono", "JetBrains Mono", "Sarasa Mono SC", "Microsoft YaHei UI", ui-monospace, monospace',
    fontSize: '14px',
    fontSizeSmall: '13px',
    fontSizeMedium: '14px',
    fontSizeLarge: '16px',
    primaryColor: '#1E293B',
    primaryColorHover: '#0F172A',
    primaryColorPressed: '#020617',
    primaryColorSuppl: '#334155',
    successColor: '#15803D',
    warningColor: '#B45309',
    errorColor: '#DC2626',
    infoColor: '#0F766E',
    borderRadius: '6px',
    borderRadiusSmall: '4px',
  },
}
