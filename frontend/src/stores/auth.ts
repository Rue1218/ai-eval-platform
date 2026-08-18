import { defineStore } from 'pinia'
import { api } from '../api/http'
import type { AuthUser, Role } from '../api/types'

export type { Role }

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as AuthUser | null,
    loaded: false,
  }),
  getters: {
    isLoggedIn: (state) => !!state.user,
    mustChangePassword: (state) => !!state.user?.must_change_password,
  },
  actions: {
    async fetchMe() {
      try {
        const user = await api.auth.getMe()
        this.user = user
      } catch (e) {
        this.user = null
      } finally {
        this.loaded = true
      }
    },
    async login(username: string, password: string) {
      const user = await api.auth.login({ username, password })
      this.user = user
      return user
    },
    async logout() {
      try {
        await api.auth.logout()
      } finally {
        this.user = null
      }
    },
    async changePassword(newPassword: string, oldPassword?: string) {
      await api.auth.changePassword({ old_password: oldPassword, new_password: newPassword })
      if (this.user) {
        this.user.must_change_password = false
      }
    },
  },
})
