// 认证状态：模块级单例（轻量替代 pinia），供路由守卫与组件共用
import { ref, computed } from 'vue'
import { get, post } from '../api/client.js'

const me = ref(null) // { id, username, display_name, role } | null
const loaded = ref(false)

export function useAuth() {
  const isAdmin = computed(() => me.value?.role === 'admin')
  const displayName = computed(
    () => me.value?.display_name || me.value?.username || '',
  )

  async function loadMe() {
    try {
      me.value = await get('/auth/me')
    } catch {
      me.value = null
    } finally {
      loaded.value = true
    }
  }

  async function login(username, password, remember) {
    const user = await post('/auth/login', { username, password, remember })
    me.value = user
    return user
  }

  async function register(username, password, displayName) {
    const user = await post('/auth/register', {
      username,
      password,
      display_name: displayName,
    })
    me.value = user
    return user
  }

  async function logout() {
    try {
      await post('/auth/logout', {})
    } finally {
      me.value = null
    }
  }

  return { me, loaded, isAdmin, displayName, loadMe, login, register, logout }
}
