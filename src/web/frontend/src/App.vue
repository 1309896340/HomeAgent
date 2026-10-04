<script setup>
import { ref } from 'vue'
import { get } from './api/client.js'

const count = ref(0)

// 演示 api 模块：请求后端 /api/health（相对路径，dev 下由 vite 代理转发）
const apiState = ref('idle') // idle | loading | ok | error
const apiResult = ref('')

async function callHealth() {
  apiState.value = 'loading'
  apiResult.value = ''
  try {
    const data = await get('/health')
    apiState.value = 'ok'
    apiResult.value = JSON.stringify(data, null, 2)
  } catch (err) {
    apiState.value = 'error'
    apiResult.value = String(err.message || err)
  }
}
</script>

<template>
  <div class="flex min-h-screen flex-col items-center justify-center gap-8 bg-gray-50 px-4 py-12 text-gray-800">
    <header class="text-center">
      <h1 class="text-4xl font-bold tracking-tight text-indigo-600">HomeAgent</h1>
      <p class="mt-2 text-gray-500">Vue 3 + Vite + Tailwind CSS 前端骨架</p>
    </header>

    <!-- Tailwind 样式演示 -->
    <section class="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
      <h2 class="mb-4 text-lg font-semibold">Tailwind 演示：计数器</h2>
      <div class="flex items-center gap-4">
        <button
          class="rounded-lg bg-indigo-600 px-4 py-2 font-medium text-white transition hover:bg-indigo-700 active:scale-95"
          @click="count++"
        >
          +1
        </button>
        <span class="rounded-lg bg-indigo-50 px-4 py-2 font-mono text-xl text-indigo-700">
          {{ count }}
        </span>
        <button
          class="rounded-lg border border-gray-300 px-4 py-2 font-medium text-gray-600 transition hover:bg-gray-100"
          @click="count = 0"
        >
          重置
        </button>
      </div>
    </section>

    <!-- API 模块演示 -->
    <section class="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
      <h2 class="mb-4 text-lg font-semibold">API 演示：GET /api/health</h2>
      <button
        class="rounded-lg bg-emerald-600 px-4 py-2 font-medium text-white transition hover:bg-emerald-700 disabled:opacity-50"
        :disabled="apiState === 'loading'"
        @click="callHealth"
      >
        {{ apiState === 'loading' ? '请求中…' : '发起请求' }}
      </button>
      <pre
        v-if="apiResult"
        class="mt-4 max-h-48 overflow-auto rounded-lg p-3 text-sm"
        :class="apiState === 'ok' ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'"
      >{{ apiResult }}</pre>
      <p v-else-if="apiState === 'idle'" class="mt-4 text-sm text-gray-400">
        点击按钮测试后端连通性（未启动后端时会显示错误，属正常现象）。
      </p>
    </section>
  </div>
</template>
