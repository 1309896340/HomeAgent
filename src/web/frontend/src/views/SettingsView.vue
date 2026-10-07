<script setup>
// 设置模块布局：按角色重定向默认子页，子导航区分权限
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../stores/auth.js'

const route = useRoute()
const router = useRouter()
const auth = useAuth()

// /settings 落地时按角色送进对应子页
watch(
  () => route.name,
  (name) => {
    if (name === undefined || name === 'settings') {
      router.replace(auth.isAdmin.value ? { name: 'settings-users' } : { name: 'settings-account' })
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-6 lg:px-6">
    <h1 class="text-2xl font-semibold tracking-tight">设置</h1>

    <div class="mt-4 flex gap-1 border-b border-line">
      <RouterLink
        v-if="auth.isAdmin.value"
        :to="{ name: 'settings-users' }"
        class="-mb-px border-b-2 px-3 py-2 text-sm transition"
        :class="
          route.name === 'settings-users'
            ? 'border-nav-underline font-semibold text-fg-default'
            : 'border-transparent text-fg-muted hover:text-fg-default'
        "
      >用户管理</RouterLink>
      <RouterLink
        :to="{ name: 'settings-account' }"
        class="-mb-px border-b-2 px-3 py-2 text-sm transition"
        :class="
          route.name === 'settings-account'
            ? 'border-nav-underline font-semibold text-fg-default'
            : 'border-transparent text-fg-muted hover:text-fg-default'
        "
      >账号安全</RouterLink>
    </div>

    <RouterView />
  </div>
</template>
