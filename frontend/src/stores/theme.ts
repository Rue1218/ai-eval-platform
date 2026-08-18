import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark'

export const useThemeStore = defineStore('theme', {
  state: () => ({
    mode: (localStorage.getItem('data-theme') as ThemeMode) || 'light',
    collapsed: false,
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
    },
  },
})
