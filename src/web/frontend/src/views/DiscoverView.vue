<script setup>
// 设备配对：类似蓝牙配对——自动嗅探新设备 → 人工勾选与命名 → 加入已注册列表
// 注册立即返回；端口扫描在后台线程进行，完成后仪表盘可见
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { get, post } from '../api/client.js'

const router = useRouter()

const scanning = ref(false)
const scanError = ref('')
const hosts = ref([]) // [{ ip, suggested_name }]
const checked = ref(new Set())
const names = ref({}) // { ip: 编辑中的名称 }
const registerError = ref('')
const registering = ref(false)
const registeredCount = ref(0)

let scanId = null
let pollTimer = null

const hasChecked = computed(() => checked.value.size > 0)

function pollScan() {
  pollTimer = setInterval(async () => {
    try {
      const task = await get(`/devices/scan/${scanId}`)
      if (task.status === 'done') {
        scanning.value = false
        hosts.value = task.hosts
        for (const h of task.hosts) {
          checked.value.add(h.ip)
          if (!(h.ip in names.value)) names.value[h.ip] = h.suggested_name
        }
        stopPolling()
      }
    } catch (e) {
      scanning.value = false
      scanError.value = e.message
      stopPolling()
    }
  }, 1000)
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

async function startScan() {
  scanError.value = ''
  registerError.value = ''
  scanning.value = true
  hosts.value = []
  checked.value = new Set()
  names.value = {}
  try {
    const { scan_id } = await post('/devices/scan')
    scanId = scan_id
    pollScan()
  } catch (e) {
    scanning.value = false
    scanError.value = e.message
  }
}

function toggleCheck(ip) {
  const s = checked.value
  s.has(ip) ? s.delete(ip) : s.add(ip)
}

function onNameInput(ip, e) {
  names.value[ip] = e.target.value
}

async function registerChecked() {
  registering.value = true
  registerError.value = ''
  let ok = 0
  const succeeded = new Set()
  for (const ip of checked.value) {
    try {
      await post('/devices', { ip, name: names.value[ip] || null })
      ok += 1
      succeeded.add(ip)
    } catch (e) {
      registerError.value = e.message
    }
  }
  registeredCount.value = ok
  checked.value = new Set([...checked.value].filter((ip) => !succeeded.has(ip)))
  hosts.value = hosts.value.filter((h) => !succeeded.has(h.ip))
  registering.value = false
  if (ok > 0 && !registerError.value) {
    // 全部注册成功：短暂展示成功态后回仪表盘
    setTimeout(() => router.push('/dashboard'), 1200)
  }
}

onMounted(startScan)
onUnmounted(stopPolling)
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6 px-4 py-6 lg:px-6">
    <!-- 页头 -->
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">设备配对</h1>
        <p class="mt-1 text-sm text-fg-muted">
          嗅探内网中的新设备，勾选后加入已注册列表（端口扫描将在注册后于后台进行）。
        </p>
      </div>
      <button
        class="rounded-md border border-line bg-canvas px-3 py-1.5 text-sm font-medium text-fg-default transition hover:bg-canvas-subtle"
        :disabled="scanning"
        @click="startScan"
      >
        重新扫描
      </button>
    </div>

    <p v-if="scanError" class="rounded-md border border-danger-emphasis bg-danger-subtle px-3 py-2 text-sm text-danger">
      {{ scanError }}
    </p>

    <!-- 扫描进度 -->
    <div v-if="scanning" class="rounded-lg border border-line bg-canvas p-8 text-center">
      <div class="mx-auto h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent"></div>
      <p class="mt-3 text-sm text-fg-muted">正在嗅探内网新设备（ping 扫描，约 10 秒）…</p>
    </div>

    <!-- 注册成功提示 -->
    <div v-else-if="registeredCount > 0 && !scanError && hosts.length === 0"
         class="rounded-lg border border-success-emphasis bg-success-subtle p-6 text-center">
      <p class="text-sm font-medium text-success">已加入 {{ registeredCount }} 台设备。</p>
      <p class="mt-1 text-xs text-fg-muted">端口扫描进行中，正在返回仪表盘…</p>
    </div>

    <!-- 扫描结果 -->
    <section v-else class="rounded-lg border border-line bg-canvas shadow-sm">
      <div class="flex items-center justify-between border-b border-line-muted px-5 py-3">
        <h2 class="font-semibold">发现的新设备（{{ hosts.length }}）</h2>
        <span class="text-xs text-fg-muted">仅列出未注册的存活主机</span>
      </div>

      <div v-if="!scanning && hosts.length === 0" class="px-5 py-8 text-center text-sm text-fg-muted">
        没有发现未注册的新设备。新设备接入后可点击「重新扫描」。
      </div>

      <ul v-else class="divide-y divide-line-muted">
        <li v-for="h in hosts" :key="h.ip" class="flex items-center gap-3 px-5 py-3">
          <input
            type="checkbox"
            class="h-4 w-4 accent-accent"
            :checked="checked.has(h.ip)"
            @change="toggleCheck(h.ip)"
          />
          <span class="font-mono text-sm text-fg-muted">{{ h.ip }}</span>
          <input
            class="w-48 rounded-md border border-line bg-canvas px-2 py-1 text-sm transition focus:border-accent"
            :value="names[h.ip] ?? h.suggested_name"
            placeholder="设备名称"
            @input="onNameInput(h.ip, $event)"
          />
        </li>
      </ul>

      <div v-if="hosts.length > 0" class="flex items-center justify-between border-t border-line-muted px-5 py-3">
        <p v-if="registerError" class="text-sm text-danger">{{ registerError }}</p>
        <p v-else-if="registeredCount > 0" class="text-sm text-success">
          已加入 {{ registeredCount }} 台（勾选新设备可继续注册）
        </p>
        <span v-else class="text-xs text-fg-muted">已勾选 {{ checked.size }} 台</span>
        <button
          class="rounded-md border border-accent-emphasis bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:bg-accent-emphasis/90 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!hasChecked || registering"
          @click="registerChecked"
        >
          {{ registering ? '注册中…' : '加入已注册列表' }}
        </button>
      </div>
    </section>

    <div class="text-center">
      <button class="text-sm text-accent hover:underline" @click="router.push('/dashboard')">
        返回仪表盘
      </button>
    </div>
  </div>
</template>
