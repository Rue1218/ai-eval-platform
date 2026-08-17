import { defineStore } from 'pinia'
import http from '../api'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    loaded: false,
  }),
  actions: {
    async fetchMe() {
      try {
        const { data } = await http.get('/api/auth/me')
        this.user = data
      } catch (e) {
        this.user = null
      } finally {
        this.loaded = true
      }
    },
    async login(username, password) {
      const { data } = await http.post('/api/auth/login', { username, password })
      this.user = data
      return data
    },
    async logout() {
      await http.post('/api/auth/logout')
      this.user = null
    },
  },
})
