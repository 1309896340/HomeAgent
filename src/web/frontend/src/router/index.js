// 路由表：tab 由主要路由生成，设置模块使用嵌套子路由
import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../stores/auth.js'
import DashboardView from '../views/DashboardView.vue'
import ChatView from '../views/ChatView.vue'
import PlaceholderView from '../views/PlaceholderView.vue'
import LoginView from '../views/LoginView.vue'
import SettingsView from '../views/SettingsView.vue'
import UserManagementView from '../views/settings/UserManagementView.vue'
import AccountView from '../views/settings/AccountView.vue'

// tab 定义（App.vue 顶栏按此渲染，图标为 24x24 stroke path）
export const mainTabs = [
  {
    path: '/dashboard',
    title: '仪表盘',
    icon: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
  },
  {
    path: '/chat',
    title: '对话',
    icon: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  },
  {
    path: '/devices',
    title: '设备',
    icon: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/>',
  },
  {
    path: '/settings',
    title: '设置',
    icon: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/', redirect: '/dashboard' },
    {
      path: '/dashboard',
      component: DashboardView,
      meta: { title: '仪表盘' },
    },
    { path: '/chat', component: ChatView, meta: { title: '对话' } },
    {
      path: '/devices',
      component: PlaceholderView,
      props: { title: '设备', description: '家庭设备接入与控制面板，规划中。' },
      meta: { title: '设备' },
    },
    {
      path: '/settings',
      component: SettingsView,
      children: [
        // 默认子页按角色在 SettingsView 内重定向：admin→用户管理，其余→账号安全
        { path: '', redirect: { name: 'settings-account' } },
        {
          path: 'users',
          name: 'settings-users',
          component: UserManagementView,
          meta: { roles: ['admin'], title: '用户管理' },
        },
        {
          path: 'account',
          name: 'settings-account',
          component: AccountView,
          meta: { title: '账号安全' },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

// 全局守卫：未登录 → /login；已登录访问 /login → 首页；子页按角色校验
router.beforeEach(async (to) => {
  const auth = useAuth()
  if (!auth.loaded.value) {
    await auth.loadMe()
  }
  if (to.meta.public) {
    return auth.me.value ? '/dashboard' : true
  }
  if (!auth.me.value) {
    return { path: '/login', query: to.fullPath !== '/dashboard' ? { redirect: to.fullPath } : {} }
  }
  if (to.meta.roles && !to.meta.roles.includes(auth.me.value.role)) {
    return '/dashboard'
  }
  return true
})

export default router
