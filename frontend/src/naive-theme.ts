import type { GlobalThemeOverrides } from 'naive-ui'

// Naive UI 主题覆盖（设计规范 §8.4）：令牌优先，主色 = --accent-ai，精准对齐字阶与字体栈
export const themeOverrides: GlobalThemeOverrides = {
  common: {
    fontFamily: 'Inter, "Noto Sans SC", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontFamilyMono: '"JetBrains Mono", "Fira Code", "SF Mono", Menlo, monospace',
    fontSize: '13px',
    fontSizeSmall: '12px',
    fontSizeMedium: '13px',
    fontSizeLarge: '15px',
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
