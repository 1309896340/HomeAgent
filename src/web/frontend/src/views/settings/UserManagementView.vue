<script setup>
// 用户管理（仅 admin）：列表 / 新增 / 改角色 / 重置密码 / 禁用启用 / 移除
import { ref, onMounted, nextTick } from 'vue'
import { get, post, patch, del as apiDelete } from '../../api/client.js'
import { useAuth } from '../../stores/auth.js'

const auth = useAuth()
const users = ref([])
const loading = ref(true)
const notice = ref('')
const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ username: '', display_name: '', password: '', role: 'member' })

// 重置密码 modal
const resetTarget = ref(null) // 待重置的用户对象
const resetPw = ref('')
const resetPwConfirm = ref('')
const resetError = ref('')
const resetBusy = ref(false)
const resetPwInput = ref(null)

const ROLE_LABELS = { admin: '管理员', member: '成员', guest: '客人' }

async function loadUsers() {
  loading.value = true
  try {
    users.value = await get('/admin/users')
  } catch (err) {
    notice.value = String(err.message || err)
  } finally {
    loading.value = false
  }
}

async function run(action, okMsg) {
  notice.value = ''
  try {
    await action()
    if (okMsg) notice.value = okMsg
    await loadUsers()
  } catch (err) {
    notice.value = String(err.message || err).replace(/^API 请求失败: \d+ ?/, '')
  }
}

function createUser() {
  creating.value = true
  run(async () => {
    await post('/admin/users', createForm.value)
    showCreate.value = false
    createForm.value = { username: '', display_name: '', password: '', role: 'member' }
  }).finally(() => (creating.value = false))
}

function changeRole(u, event) {
  const role = event.target.value
  if (!confirm(`将「${u.display_name || u.username}」的角色改为 ${ROLE_LABELS[role]}？`)) {
    event.target.value = u.role
    return
  }
  run(() => patch(`/admin/users/${u.id}`, { role }))
}

// ---------- 重置密码 modal ----------
function openReset(u) {
  resetTarget.value = u
  resetPw.value = ''
  resetPwConfirm.value = ''
  resetError.value = ''
  nextTick(() => resetPwInput.value?.focus())
}
function closeReset() {
  resetTarget.value = null
}
async function confirmReset() {
  resetError.value = ''
  if (resetPw.value.length < 6) {
    resetError.value = '密码至少 6 位'
    return
  }
  if (resetPw.value !== resetPwConfirm.value) {
    resetError.value = '两次输入的密码不一致'
    return
  }
  resetBusy.value = true
  try {
    await run(
      () => patch(`/admin/users/${resetTarget.value.id}`, { password: resetPw.value }),
      `已重置「${resetTarget.value.display_name || resetTarget.value.username}」的密码，其登录会话已失效`,
    )
    closeReset()
  } finally {
    resetBusy.value = false
  }
}

function toggleDisabled(u) {
  const next = !u.disabled
  if (next && !confirm(`禁用「${u.display_name || u.username}」？其登录会话将立即失效。`)) return
  run(() => patch(`/admin/users/${u.id}`, { disabled: next }))
}

function removeUser(u) {
  if (!confirm(`移除「${u.display_name || u.username}」？\n其全部对话数据将被删除，不可恢复！`)) return
  run(() => apiDelete(`/admin/users/${u.id}`))
}

onMounted(loadUsers)
</script>

<template>
  <div class="mt-6">
    <div class="flex items-center justify-between">
      <p class="text-sm text-fg-muted">共 {{ users.length }} 个账号</p>
      <button
        class="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:bg-accent-emphasis"
        @click="showCreate = !showCreate"
      >
        ＋ 新增用户
      </button>
    </div>

    <p v-if="notice" class="mt-3 rounded-md border border-attention-subtle bg-attention-subtle px-3 py-2 text-xs text-attention">
      {{ notice }}
    </p>

    <!-- 新增用户 -->
    <form
      v-if="showCreate"
      class="mt-4 grid grid-cols-1 gap-3 rounded-lg border border-line bg-canvas p-4 shadow-sm sm:grid-cols-2"
      @submit.prevent="createUser"
    >
      <label class="block text-sm">
        <span class="mb-1 block font-medium">用户名 <span class="text-danger">*</span></span>
        <input v-model="createForm.username" required class="w-full rounded-md border border-line px-3 py-1.5 text-sm outline-none focus:border-accent" placeholder="3~32 位字母数字_-"/>
      </label>
      <label class="block text-sm">
        <span class="mb-1 block font-medium">昵称</span>
        <input v-model="createForm.display_name" class="w-full rounded-md border border-line px-3 py-1.5 text-sm outline-none focus:border-accent" placeholder="选填"/>
      </label>
      <label class="block text-sm">
        <span class="mb-1 block font-medium">初始密码 <span class="text-danger">*</span></span>
        <input v-model="createForm.password" required type="password" class="w-full rounded-md border border-line px-3 py-1.5 text-sm outline-none focus:border-accent" placeholder="至少 6 位"/>
      </label>
      <label class="block text-sm">
        <span class="mb-1 block font-medium">角色</span>
        <select v-model="createForm.role" class="w-full rounded-md border border-line bg-canvas px-3 py-1.5 text-sm outline-none focus:border-accent">
          <option value="member">成员</option>
          <option value="admin">管理员</option>
          <option value="guest">客人</option>
        </select>
      </label>
      <div class="flex gap-2 sm:col-span-2">
        <button type="submit" :disabled="creating" class="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:bg-accent-emphasis disabled:opacity-50">创建</button>
        <button type="button" class="rounded-md border border-line px-3 py-1.5 text-sm transition hover:bg-canvas-subtle" @click="showCreate = false">取消</button>
      </div>
    </form>

    <!-- 用户列表 -->
    <div class="mt-4 overflow-x-auto rounded-lg border border-line bg-canvas shadow-sm">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-line bg-canvas-subtle text-left text-xs text-fg-muted">
            <th class="px-4 py-2.5 font-medium">用户</th>
            <th class="px-4 py-2.5 font-medium">角色</th>
            <th class="px-4 py-2.5 font-medium">状态</th>
            <th class="px-4 py-2.5 font-medium">最近登录</th>
            <th class="px-4 py-2.5 text-right font-medium">操作</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line-muted">
          <tr v-if="loading">
            <td colspan="5" class="px-4 py-8 text-center text-fg-subtle">加载中…</td>
          </tr>
          <tr v-for="u in users" v-else :key="u.id" :class="{ 'opacity-60': u.disabled }">
            <td class="px-4 py-3">
              <div class="flex items-center gap-2">
                <span class="flex h-7 w-7 items-center justify-center rounded-full bg-accent-subtle text-xs font-semibold text-accent">
                  {{ (u.display_name || u.username)[0].toUpperCase() }}
                </span>
                <div>
                  <div class="font-medium">{{ u.display_name || u.username }}</div>
                  <div class="text-xs text-fg-muted">{{ u.username }}</div>
                </div>
                <span v-if="u.id === auth.me.value?.id" class="rounded bg-canvas-inset px-1.5 py-0.5 text-[10px] text-fg-muted">我</span>
              </div>
            </td>
            <td class="px-4 py-3">
              <select
                :value="u.role"
                :disabled="u.id === auth.me.value?.id"
                class="rounded-md border border-line bg-canvas px-2 py-1 text-xs outline-none focus:border-accent disabled:opacity-50"
                @change="changeRole(u, $event)"
              >
                <option value="admin">管理员</option>
                <option value="member">成员</option>
                <option value="guest">客人</option>
              </select>
            </td>
            <td class="px-4 py-3">
              <span
                class="rounded-full px-2 py-0.5 text-xs font-medium"
                :class="u.disabled ? 'bg-danger-subtle text-danger' : 'bg-success-subtle text-success'"
              >{{ u.disabled ? '已禁用' : '正常' }}</span>
            </td>
            <td class="px-4 py-3 text-xs text-fg-muted">{{ u.last_login_at || '从未' }}</td>
            <td class="px-4 py-3 text-right text-xs">
              <button class="text-accent hover:underline" @click="openReset(u)">重置密码</button>
              <button class="ml-3 text-attention hover:underline" @click="toggleDisabled(u)">
                {{ u.disabled ? '启用' : '禁用' }}
              </button>
              <button class="ml-3 text-danger hover:underline" @click="removeUser(u)">移除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 重置密码 modal -->
    <div
      v-if="resetTarget"
      class="fixed inset-0 z-50 flex items-center justify-center bg-fg-default/50 px-4"
      @click.self="closeReset"
      @keydown.esc="closeReset"
    >
      <div class="w-full max-w-sm rounded-lg border border-line bg-canvas p-5 shadow-lg" role="dialog" aria-modal="true">
        <h3 class="font-semibold">重置密码</h3>
        <p class="mt-1 text-xs text-fg-muted">
          为「{{ resetTarget.display_name || resetTarget.username }}」设置新密码；提交后该用户的全部登录会话将失效。
        </p>
        <form class="mt-4 space-y-3 text-sm" @submit.prevent="confirmReset">
          <label class="block">
            <span class="mb-1 block text-fg-muted">新密码（至少 6 位）</span>
            <input
              ref="resetPwInput"
              v-model="resetPw"
              required
              type="password"
              autocomplete="new-password"
              class="w-full rounded-md border border-line px-3 py-1.5 outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
            />
          </label>
          <label class="block">
            <span class="mb-1 block text-fg-muted">确认新密码</span>
            <input
              v-model="resetPwConfirm"
              required
              type="password"
              autocomplete="new-password"
              class="w-full rounded-md border border-line px-3 py-1.5 outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
            />
          </label>
          <p v-if="resetError" class="rounded-md border border-danger-subtle bg-danger-subtle px-3 py-2 text-xs text-danger">
            {{ resetError }}
          </p>
          <div class="flex justify-end gap-2 pt-1">
            <button
              type="button"
              class="rounded-md border border-line px-3 py-1.5 transition hover:bg-canvas-subtle"
              @click="closeReset"
            >取消</button>
            <button
              type="submit"
              :disabled="resetBusy"
              class="rounded-md bg-accent px-3 py-1.5 font-medium text-white transition hover:bg-accent-emphasis disabled:opacity-50"
            >{{ resetBusy ? '提交中…' : '确认重置' }}</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
