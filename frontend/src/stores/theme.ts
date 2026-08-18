import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark'

export const useThemeStore = defineStore('theme', {
  state: () => ({
    mode: (localStorage.getItem('data-theme') as ThemeMode) || 'light',
    // 导航栏折叠态跨页持久化（键名对齐原型 ae_sidebar_fold）
    collapsed: localStorage.getItem('ae_sidebar_fold') === '1',
  }),
  actions: {
    apply() {
      document.documentElement.setAttribute('data-theme', this.mode)
      localStorage.setItem('data-theme', this.mode)
    },
    toggle() {
      this.mode = this.mode === 'light' ? 'dark' : 'light'
      this.apply()
    },
    toggleCollapsed() {
      this.collapsed = !this.collapsed
      localStorage.setItem('ae_sidebar_fold', this.collapsed ? '1' : '0')
    },
  },
})
