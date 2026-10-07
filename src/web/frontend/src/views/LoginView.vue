<script setup>
// 登录 / 注册页（公开路由，全屏无外框）
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../stores/auth.js'

const mode = ref('login') // login | register
const username = ref('')
const password = ref('')
const displayName = ref('')
const remember = ref(false)
const error = ref('')
const busy = ref(false)

const router = useRouter()
const route = useRoute()
const auth = useAuth()

async function submit() {
  if (busy.value) return
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  busy.value = true
  try {
    if (mode.value === 'login') {
      await auth.login(username.value.trim(), password.value, remember.value)
    } else {
      if (password.value.length < 6) {
        error.value = '密码至少 6 位'
        return
      }
      await auth.register(username.value.trim(), password.value, displayName.value.trim())
    }
    router.push(typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard')
  } catch (err) {
    error.value = String(err.message || err).replace(/^API 请求失败: \d+ ?/, '')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-canvas-subtle px-4">
    <div class="w-full max-w-sm">
      <!-- 品牌 -->
      <div class="mb-6 flex flex-col items-center gap-2">
        <span class="flex h-12 w-12 items-center justify-center rounded-xl bg-fg-default">
          <svg class="h-6 w-6 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
            <polyline points="9 22 9 12 15 12 15 22" />
          </svg>
        </span>
        <h1 class="text-xl font-bold tracking-tight">HomeAgent</h1>
        <p class="text-sm text-fg-muted">运行在家中的智能助手</p>
      </div>

      <div class="rounded-lg border border-line bg-canvas p-6 shadow-sm">
        <!-- 模式切换 -->
        <div class="mb-5 grid grid-cols-2 rounded-md border border-line bg-canvas-subtle p-0.5 text-sm font-medium">
          <button
            class="rounded-[5px] py-1.5 transition"
            :class="mode === 'login' ? 'bg-canvas shadow-sm' : 'text-fg-muted hover:text-fg-default'"
            @click="mode = 'login'; error = ''"
          >登录</button>
          <button
            class="rounded-[5px] py-1.5 transition"
            :class="mode === 'register' ? 'bg-canvas shadow-sm' : 'text-fg-muted hover:text-fg-default'"
            @click="mode = 'register'; error = ''"
          >注册</button>
        </div>

        <form class="space-y-4" @submit.prevent="submit">
          <label class="block">
            <span class="mb-1 block text-sm font-medium">用户名</span>
            <input
              v-model="username"
              type="text"
              autocomplete="username"
              class="w-full rounded-md border border-line px-3 py-1.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
              placeholder="3~32 位字母、数字、_ 或 -"
            />
          </label>

          <label v-if="mode === 'register'" class="block">
            <span class="mb-1 block text-sm font-medium">昵称 <span class="font-normal text-fg-muted">(选填)</span></span>
            <input
              v-model="displayName"
              type="text"
              class="w-full rounded-md border border-line px-3 py-1.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
              placeholder="顶栏与欢迎语中显示"
            />
          </label>

          <label class="block">
            <span class="mb-1 block text-sm font-medium">密码</span>
            <input
              v-model="password"
              type="password"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
              class="w-full rounded-md border border-line px-3 py-1.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
              :placeholder="mode === 'register' ? '至少 6 位' : ''"
            />
          </label>

          <label v-if="mode === 'login'" class="flex items-center gap-2 text-sm text-fg-muted">
            <input v-model="remember" type="checkbox" class="h-4 w-4 rounded border-line accent-[#0969da]" />
            记住我（30 天）
          </label>

          <p v-if="error" class="rounded-md border border-danger-subtle bg-danger-subtle px-3 py-2 text-xs text-danger">
            {{ error }}
          </p>

          <button
            type="submit"
            class="w-full rounded-md bg-accent py-1.5 text-sm font-medium text-white transition hover:bg-accent-emphasis disabled:opacity-50"
            :disabled="busy"
          >
            {{ busy ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录' }}
          </button>
        </form>
      </div>

      <p class="mt-4 text-center text-xs text-fg-subtle">第一个注册的用户将成为管理员</p>
    </div>
  </div>
</template>
