<script setup>
import { ref, computed } from 'vue'
import DashboardView from './views/DashboardView.vue'
import ChatView from './views/ChatView.vue'
import PlaceholderView from './views/PlaceholderView.vue'

// 顶层导航：每个 tab 对应一个相对独立的模块。
// tab 数量确定后可平滑迁移到 vue-router（component 换成路由视图即可）。
const tabs = [
  {
    key: 'dashboard',
    label: '仪表盘',
    icon: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    component: DashboardView,
  },
  {
    key: 'chat',
    label: '对话',
    icon: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    component: ChatView,
  },
  {
    key: 'devices',
    label: '设备',
    icon: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/>',
    component: PlaceholderView,
    props: { title: '设备', description: '家庭设备接入与控制面板，规划中。' },
  },
  {
    key: 'settings',
    label: '设置',
    icon: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    component: PlaceholderView,
    props: { title: '设置', description: '系统偏好、账号与集成配置，规划中。' },
  },
]

const active = ref('dashboard')
const activeTab = computed(() => tabs.find((t) => t.key === active.value))
</script>

<template>
  <div class="min-h-screen bg-canvas-subtle font-sans text-fg-default">
    <!-- 顶部导航（GitHub 仓库页风格：logo + 下划线 tab 同行） -->
    <header class="sticky top-0 z-10 border-b border-line bg-canvas">
      <div class="mx-auto flex h-16 max-w-7xl items-center gap-6 px-4 lg:px-6">
        <!-- 品牌 -->
        <a href="#" class="flex items-center gap-2">
          <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-fg-default">
            <svg
              class="h-4.5 w-4.5 text-white"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              <polyline points="9 22 9 12 15 12 15 22" />
            </svg>
          </span>
          <span class="text-lg font-bold tracking-tight">HomeAgent</span>
        </a>

        <!-- Tab 导航 -->
        <nav class="flex h-16 flex-1 items-stretch gap-1 overflow-x-auto">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="flex items-center gap-2 whitespace-nowrap border-b-2 px-3 text-sm transition"
            :class="
              active === tab.key
                ? 'border-nav-underline font-semibold text-fg-default'
                : 'border-transparent text-fg-muted hover:border-line hover:text-fg-default'
            "
            @click="active = tab.key"
          >
            <svg
              class="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              v-html="tab.icon"
            ></svg>
            {{ tab.label }}
          </button>
        </nav>

        <!-- 右侧：搜索 + 头像 -->
        <div class="hidden items-center gap-3 md:flex">
          <button
            class="flex w-56 items-center gap-2 rounded-md border border-line bg-canvas-subtle px-3 py-1.5 text-sm text-fg-muted transition hover:border-fg-subtle"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <circle cx="11" cy="11" r="8" />
              <path d="M21 21l-4.35-4.35" />
            </svg>
            搜索
            <span class="ml-auto rounded border border-line bg-canvas px-1.5 text-xs text-fg-subtle">/</span>
          </button>
          <span class="flex h-8 w-8 items-center justify-center rounded-full bg-accent-subtle text-sm font-semibold text-accent">
            W
          </span>
        </div>
      </div>
    </header>

    <!-- 内容区：tab 切换（对话模块全屏无内边距，其余 tab 居中带内边距） -->
    <main :class="active === 'chat' ? '' : 'mx-auto max-w-7xl px-4 py-6 lg:px-6'">
      <component :is="activeTab.component" v-bind="activeTab.props ?? {}" />
    </main>
  </div>
</template>
