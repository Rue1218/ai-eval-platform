import type { GlobalThemeOverrides } from 'naive-ui'

// Naive UI 主题覆盖（设计规范 §8.4）：令牌优先，主色 = --accent-ai
export const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#6366F1',
    primaryColorHover: '#818CF8',
    primaryColorPressed: '#4F46E5',
    successColor: '#10B981',
    warningColor: '#F59E0B',
    errorColor: '#EF4444',
    infoColor: '#3B82F6',
    borderRadius: '10px',
  },
}
