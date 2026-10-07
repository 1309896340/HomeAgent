<script setup>
// 账号安全（全员）：账号信息展示 + 修改密码
import { ref } from 'vue'
import { post } from '../../api/client.js'
import { useAuth } from '../../stores/auth.js'

const auth = useAuth()
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const notice = ref('')
const ok = ref(false)
const busy = ref(false)

async function submit() {
  notice.value = ''
  ok.value = false
  if (newPassword.value.length < 6) {
    notice.value = '新密码至少 6 位'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    notice.value = '两次输入的新密码不一致'
    return
  }
  busy.value = true
  try {
    await post('/auth/change-password', {
      old_password: oldPassword.value,
      new_password: newPassword.value,
    })
    ok.value = true
    oldPassword.value = newPassword.value = confirmPassword.value = ''
  } catch (err) {
    notice.value = String(err.message || err).replace(/^API 请求失败: \d+ ?/, '')
  } finally {
    busy.value = false
  }
}

const ROLE_LABELS = { admin: '管理员', member: '成员', guest: '客人' }
</script>

<template>
  <div class="mt-6 grid gap-4 lg:grid-cols-2">
    <!-- 账号信息 -->
    <section class="rounded-lg border border-line bg-canvas p-5 shadow-sm">
      <h2 class="font-semibold">账号信息</h2>
      <dl class="mt-4 space-y-3 text-sm">
        <div class="flex justify-between">
          <dt class="text-fg-muted">用户名</dt>
          <dd class="font-medium">{{ auth.me.value?.username }}</dd>
        </div>
        <div class="flex justify-between">
          <dt class="text-fg-muted">昵称</dt>
          <dd class="font-medium">{{ auth.displayName.value }}</dd>
        </div>
        <div class="flex justify-between">
          <dt class="text-fg-muted">角色</dt>
          <dd>
            <span class="rounded-full bg-accent-subtle px-2 py-0.5 text-xs font-medium text-accent">
              {{ ROLE_LABELS[auth.me.value?.role] || auth.me.value?.role }}
            </span>
          </dd>
        </div>
      </dl>
      <p class="mt-4 text-xs text-fg-subtle">忘记密码请联系管理员重置。</p>
    </section>

    <!-- 修改密码 -->
    <section class="rounded-lg border border-line bg-canvas p-5 shadow-sm">
      <h2 class="font-semibold">修改密码</h2>
      <form class="mt-4 space-y-3 text-sm" @submit.prevent="submit">
        <label class="block">
          <span class="mb-1 block text-fg-muted">旧密码</span>
          <input v-model="oldPassword" required type="password" autocomplete="current-password"
                 class="w-full rounded-md border border-line px-3 py-1.5 outline-none focus:border-accent" />
        </label>
        <label class="block">
          <span class="mb-1 block text-fg-muted">新密码（至少 6 位）</span>
          <input v-model="newPassword" required type="password" autocomplete="new-password"
                 class="w-full rounded-md border border-line px-3 py-1.5 outline-none focus:border-accent" />
        </label>
        <label class="block">
          <span class="mb-1 block text-fg-muted">确认新密码</span>
          <input v-model="confirmPassword" required type="password" autocomplete="new-password"
                 class="w-full rounded-md border border-line px-3 py-1.5 outline-none focus:border-accent" />
        </label>
        <p v-if="notice" class="rounded-md border border-danger-subtle bg-danger-subtle px-3 py-2 text-xs text-danger">{{ notice }}</p>
        <p v-if="ok" class="rounded-md border border-success-subtle bg-success-subtle px-3 py-2 text-xs text-success">密码已更新。</p>
        <button type="submit" :disabled="busy"
                class="rounded-md bg-accent px-3 py-1.5 font-medium text-white transition hover:bg-accent-emphasis disabled:opacity-50">
          {{ busy ? '提交中…' : '更新密码' }}
        </button>
      </form>
    </section>
  </div>
</template>
