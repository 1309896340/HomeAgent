<script setup>
// 应用外壳：公开路由（登录页）全屏直出；其余路由套顶栏 + 内容区
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { mainTabs } from './router/index.js'
import { useAuth } from './stores/auth.js'

const route = useRoute()
const router = useRouter()
const auth = useAuth()

const menuOpen = ref(false)

function isActive(path) {
  return route.path === path || route.path.startsWith(`${path}/`)
}

function settingsTarget() {
  return auth.isAdmin.value ? '/settings/users' : '/settings/account'
}

async function logout() {
  menuOpen.value = false
  await auth.logout()
  router.push('/login')
}

function onDocClick(e) {
  if (!e.target.closest?.('.avatar-menu')) menuOpen.value = false
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))

const initials = () => auth.displayName.value.slice(0, 1).toUpperCase()
</script>

<template>
  <!-- 公开路由（登录页）：无外框 -->
  <div v-if="route.meta.public" class="min-h-screen bg-canvas-subtle font-sans text-fg-default">
    <RouterView />
  </div>

  <!-- 应用外壳 -->
  <div v-else class="min-h-screen bg-canvas-subtle font-sans text-fg-default">
    <header class="sticky top-0 z-10 border-b border-line bg-canvas">
      <div class="mx-auto flex h-16 max-w-7xl items-center gap-6 px-4 lg:px-6">
        <RouterLink to="/dashboard" class="flex items-center gap-2">
          <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-fg-default">
            <svg class="h-4.5 w-4.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              <polyline points="9 22 9 12 15 12 15 22" />
            </svg>
          </span>
          <span class="text-lg font-bold tracking-tight">HomeAgent</span>
        </RouterLink>

        <!-- Tab 导航（由路由表生成） -->
        <nav class="flex h-16 flex-1 items-stretch gap-1 overflow-x-auto">
          <RouterLink
            v-for="tab in mainTabs"
            :key="tab.path"
            :to="tab.path === '/settings' ? settingsTarget() : tab.path"
            class="flex items-center gap-2 whitespace-nowrap border-b-2 px-3 text-sm transition"
            :class="
              isActive(tab.path)
                ? 'border-nav-underline font-semibold text-fg-default'
                : 'border-transparent text-fg-muted hover:border-line hover:text-fg-default'
            "
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" v-html="tab.icon"></svg>
            {{ tab.title }}
          </RouterLink>
        </nav>

        <!-- 右侧：用户菜单 -->
        <div class="avatar-menu relative">
          <button
            class="flex h-8 w-8 items-center justify-center rounded-full bg-accent-subtle text-sm font-semibold text-accent transition hover:ring-2 hover:ring-accent/30"
            :title="auth.displayName.value"
            @click="menuOpen = !menuOpen"
          >
            {{ initials() }}
          </button>
          <div
            v-if="menuOpen"
            class="absolute right-0 top-10 w-44 overflow-hidden rounded-md border border-line bg-canvas py-1 shadow-md"
          >
            <div class="border-b border-line-muted px-3 py-2">
              <div class="truncate text-sm font-medium">{{ auth.displayName.value }}</div>
              <div class="text-xs text-fg-muted">
                {{ auth.me.value?.role === 'admin' ? '管理员' : auth.me.value?.role === 'member' ? '成员' : '客人' }}
              </div>
            </div>
            <RouterLink
              :to="settingsTarget()"
              class="block px-3 py-2 text-sm text-fg-default hover:bg-canvas-subtle"
              @click="menuOpen = false"
            >设置</RouterLink>
            <button
              class="block w-full px-3 py-2 text-left text-sm text-danger hover:bg-canvas-subtle"
              @click="logout"
            >退出登录</button>
          </div>
        </div>
      </div>
    </header>

    <main>
      <RouterView />
    </main>
  </div>
</template>
