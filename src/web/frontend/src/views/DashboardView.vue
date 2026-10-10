<script setup>
// 仪表盘：已注册内网设备列表（在线状态 + 端口三级展开）
// 进入页面静默刷新一轮在线状态，停留期间按后端下发的间隔定时轮询
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { get, patch, del } from '../api/client.js'
import { useAuth } from '../stores/auth.js'

const router = useRouter()
const auth = useAuth()
const greetingName = () => auth.displayName.value || '朋友'

const devices = ref([])
const loading = ref(true)
const error = ref('')
const pingInterval = ref(5)
let timer = null

// 三级展开状态：展开的设备 id 集合 / 设备内展开的端口 key 集合
const expandedDevices = ref(new Set())
const expandedPorts = ref(new Set())
const renamingId = ref(null)
const renameValue = ref('')

const scanBadge = {
  pending: { text: '端口扫描排队中', cls: 'text-fg-muted' },
  running: { text: '端口扫描中…', cls: 'text-attention' },
  failed: { text: '端口扫描失败', cls: 'text-danger' },
  unavailable: { text: '端口扫描不可用（未安装 nmap）', cls: 'text-fg-muted' },
}

async function loadDevices() {
  error.value = ''
  try {
    devices.value = await get('/devices')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function refreshStatus() {
  try {
    const data = await get('/devices/status')
    pingInterval.value = data.ping_interval
    const byId = new Map(data.devices.map((d) => [d.id, d]))
    for (const d of devices.value) {
      const s = byId.get(d.id)
      if (s) d.status = s.status
    }
  } catch {
    // 状态轮询失败不打断页面，下一轮再试
  }
}

function startPolling() {
  stopPolling()
  timer = setInterval(refreshStatus, pingInterval.value * 1000)
}

function stopPolling() {
  if (timer) clearInterval(timer)
  timer = null
}

function toggleDevice(id) {
  const s = expandedDevices.value
  s.has(id) ? s.delete(id) : s.add(id)
}

function togglePort(key) {
  const s = expandedPorts.value
  s.has(key) ? s.delete(key) : s.add(key)
}

function portKey(deviceId, port, protocol) {
  return `${deviceId}:${protocol}:${port}`
}

function portSummary(d) {
  if (['pending', 'running'].includes(d.scan_status)) return null
  return d.ports.filter((p) => p.protocol === 'tcp').length
}

async function submitRename(d) {
  const name = renameValue.value.trim()
  if (!name || name === d.name) {
    renamingId.value = null
    return
  }
  try {
    const updated = await patch(`/devices/${d.id}`, { name })
    Object.assign(d, updated)
  } catch (e) {
    error.value = e.message
  }
  renamingId.value = null
}

function startRename(d) {
  renamingId.value = d.id
  renameValue.value = d.name
}

async function removeDevice(d) {
  if (!confirm(`确定移除设备「${d.name}」（${d.ip}）的注册？`)) return
  try {
    await del(`/devices/${d.id}`)
    devices.value = devices.value.filter((x) => x.id !== d.id)
  } catch (e) {
    error.value = e.message
  }
}

onMounted(async () => {
  await loadDevices()
  await refreshStatus()
  startPolling()
})
onUnmounted(stopPolling)
</script>

<script>
// 行内重命名输入框的自动聚焦指令
export default {
  directives: {
    focus: {
      mounted(el) {
        el.focus()
        el.select()
      },
    },
  },
}
</script>

<template>
  <div class="mx-auto max-w-7xl space-y-6 px-4 py-6 lg:px-6">
    <!-- 页头 -->
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">仪表盘</h1>
        <p class="mt-1 text-sm text-fg-muted">你好，{{ greetingName() }}。以下是已注册的内网设备。</p>
      </div>
      <div class="flex gap-2">
        <button
          class="rounded-md border border-line bg-canvas px-3 py-1.5 text-sm font-medium text-fg-default transition hover:bg-canvas-subtle"
          @click="loadDevices(); refreshStatus()"
        >
          刷新
        </button>
        <button
          class="rounded-md border border-accent-emphasis bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:bg-accent-emphasis/90"
          @click="router.push('/discover')"
        >
          添加设备
        </button>
      </div>
    </div>

    <p v-if="error" class="rounded-md border border-danger-emphasis bg-danger-subtle px-3 py-2 text-sm text-danger">
      {{ error }}
    </p>

    <!-- 空状态 -->
    <div
      v-if="!loading && devices.length === 0"
      class="rounded-lg border border-dashed border-line bg-canvas p-10 text-center"
    >
      <p class="text-sm text-fg-muted">还没有已注册的设备。</p>
      <button
        class="mt-4 rounded-md border border-accent-emphasis bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:bg-accent-emphasis/90"
        @click="router.push('/discover')"
      >
        添加设备
      </button>
    </div>

    <!-- 设备列表 -->
    <section v-else class="rounded-lg border border-line bg-canvas shadow-sm">
      <div class="flex items-center justify-between border-b border-line-muted px-5 py-3">
        <h2 class="font-semibold">已注册设备（{{ devices.length }}）</h2>
        <span class="text-xs text-fg-muted">每 {{ pingInterval }} 秒自动刷新在线状态</span>
      </div>

      <div v-if="loading" class="px-5 py-8 text-center text-sm text-fg-muted">加载中…</div>
      <ul v-else class="divide-y divide-line-muted">
        <li v-for="d in devices" :key="d.id">
          <!-- 一级：设备行 -->
          <div class="flex items-center gap-3 px-5 py-3">
            <button
              class="flex h-5 w-5 shrink-0 items-center justify-center rounded text-fg-muted transition hover:bg-canvas-subtle"
              :title="expandedDevices.has(d.id) ? '收起端口' : '展开端口'"
              @click="toggleDevice(d.id)"
            >
              <svg
                class="h-4 w-4 transition-transform"
                :class="{ 'rotate-90': expandedDevices.has(d.id) }"
                viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
              >
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </button>

            <span class="flex items-center gap-1.5 text-xs" :title="d.status === 'online' ? '在线' : '离线'">
              <span class="h-2 w-2 rounded-full" :class="d.status === 'online' ? 'bg-success' : 'bg-fg-subtle'"></span>
              <span :class="d.status === 'online' ? 'text-success' : 'text-fg-muted'">
                {{ d.status === 'online' ? '在线' : '离线' }}
              </span>
            </span>

            <template v-if="renamingId === d.id">
              <input
                v-model="renameValue"
                v-focus
                class="w-40 rounded-md border border-accent px-2 py-0.5 text-sm"
                @keyup.enter="submitRename(d)"
                @blur="submitRename(d)"
                @keyup.esc="renamingId = null"
              />
            </template>
            <template v-else>
              <span class="text-sm font-medium" @dblclick="startRename(d)">{{ d.name }}</span>
              <button
                class="text-fg-subtle transition hover:text-fg-default"
                title="重命名"
                @click="startRename(d)"
              >
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
                </svg>
              </button>
            </template>

            <span class="font-mono text-sm text-fg-muted">{{ d.ip }}</span>
            <span v-if="d.vendor" class="hidden text-xs text-fg-subtle sm:inline">{{ d.vendor }}</span>

            <span class="ml-auto flex items-center gap-3">
              <span v-if="scanBadge[d.scan_status]" class="text-xs" :class="scanBadge[d.scan_status].cls">
                {{ scanBadge[d.scan_status].text }}
              </span>
              <span v-else-if="portSummary(d) !== null" class="text-xs text-fg-muted">
                {{ portSummary(d) }} 个开放端口
              </span>
              <button
                class="text-fg-subtle transition hover:text-danger"
                title="移除注册"
                @click="removeDevice(d)"
              >
                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </span>
          </div>

          <!-- 二级：端口列表 -->
          <div v-if="expandedDevices.has(d.id)" class="border-t border-line-muted bg-canvas-subtle/60 px-5 py-3">
            <div v-if="['pending', 'running'].includes(d.scan_status)" class="py-2 text-sm text-attention">
              端口扫描中，完成后此处显示开放端口…
            </div>
            <div v-else-if="d.scan_status === 'unavailable'" class="py-2 text-sm text-fg-muted">
              端口扫描不可用：服务器未安装 nmap。安装后重新注册或等待后续扫描可获得端口信息。
            </div>
            <div v-else-if="d.scan_status === 'failed'" class="py-2 text-sm text-danger">
              端口扫描失败，可在「添加设备」页重新触发或检查 nmap 安装。
            </div>
            <div v-else-if="d.ports.length === 0" class="py-2 text-sm text-fg-muted">
              未发现开放端口（top 1000 常用端口）。
            </div>
            <ul v-else class="divide-y divide-line-muted rounded-md border border-line bg-canvas">
              <li v-for="p in d.ports" :key="portKey(d.id, p.port, p.protocol)">
                <!-- 端口行：端口号 + 服务名摘要 -->
                <button
                  v-if="p.version"
                  class="flex w-full items-center gap-3 px-4 py-2 text-left transition hover:bg-canvas-subtle"
                  @click="togglePort(portKey(d.id, p.port, p.protocol))"
                >
                  <svg
                    class="h-3.5 w-3.5 shrink-0 text-fg-subtle transition-transform"
                    :class="{ 'rotate-90': expandedPorts.has(portKey(d.id, p.port, p.protocol)) }"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                  >
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                  <span class="w-20 font-mono text-sm">{{ p.port }}/{{ p.protocol }}</span>
                  <span class="text-sm">{{ p.service || '未知服务' }}</span>
                </button>
                <div v-else class="flex items-center gap-3 px-4 py-2">
                  <span class="w-3.5 shrink-0"></span>
                  <span class="w-20 font-mono text-sm">{{ p.port }}/{{ p.protocol }}</span>
                  <span class="text-sm">{{ p.service || '未知服务' }}</span>
                </div>

                <!-- 三级：服务详情 -->
                <div v-if="p.version && expandedPorts.has(portKey(d.id, p.port, p.protocol))"
                     class="border-t border-line-muted bg-canvas-subtle px-4 py-2 pl-11 text-xs text-fg-muted">
                  {{ p.version }}
                </div>
              </li>
            </ul>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>
