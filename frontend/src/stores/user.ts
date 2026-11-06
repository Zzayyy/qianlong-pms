import { defineStore } from 'pinia'
import { login as apiLogin, profile, type Profile } from '@/api'

interface UserState {
  token: string
  profile: Profile | null
}

export const useUserStore = defineStore('user', {
  state: (): UserState => ({
    token: localStorage.getItem('pms_token') || '',
    profile: null
  }),
  getters: {
    isLogin: (state) => Boolean(state.token),
    permissions: (state) => state.profile?.permissions ?? [],
    roles: (state) => state.profile?.roles ?? []
  },
  actions: {
    async login(username: string, password: string) {
      const data = await apiLogin(username, password)
      this.token = data.token
      localStorage.setItem('pms_token', data.token)
      await this.loadProfile()
    },
    async loadProfile() {
      if (!this.token) {
        return
      }
      this.profile = await profile()
    },
    logout() {
      this.token = ''
      this.profile = null
      localStorage.removeItem('pms_token')
    },
    has(permission: string) {
      return this.permissions.includes(permission)
    }
  }
})
