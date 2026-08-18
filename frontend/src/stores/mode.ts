import { defineStore } from 'pinia'

export type TestObjectMode = 'llm' | 'rag'

export const useModeStore = defineStore('mode', {
  state: () => ({
    mode: (localStorage.getItem('ae_mode') === 'rag' ? 'rag' : 'llm') as TestObjectMode,
  }),
  actions: {
    setMode(mode: TestObjectMode) {
      this.mode = mode
      localStorage.setItem('ae_mode', mode)
    },
    toggle() {
      this.setMode(this.mode === 'llm' ? 'rag' : 'llm')
    },
  },
})
