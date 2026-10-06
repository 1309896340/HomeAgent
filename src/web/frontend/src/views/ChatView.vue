<script setup>
// 对话模块主视图：左侧会话列表 + 右侧消息流 + 底部多模态输入
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { get, post, patch, del as apiDelete, postSSE } from '../api/client.js'
import ChatInput from '../components/chat/ChatInput.vue'
import MessageItem from '../components/chat/MessageItem.vue'

const sessions = ref([])
const activeId = ref(null)
const messages = ref([])
const loading = ref(false)
const toast = ref('')

const asrReady = ref(false)

// 流式状态（当前正在生成的助手消息）
const streaming = ref(false)
const st = ref({ thinking: '', content: '', elapsedMs: 0, meta: null })
let abortCtl = null
let timer = null

const scrollEl = ref(null)
let pinned = true

const activeSession = computed(() => sessions.value.find((s) => s.id === activeId.value))

// ---------- 会话管理 ----------
async function loadSessions() {
  sessions.value = await get('/chat/sessions')
}

async function newSession() {
  stopStream()
  const s = await post('/chat/sessions', {})
  sessions.value.unshift(s)
  activeId.value = s.id
  messages.value = []
}

async function selectSession(id) {
  if (id === activeId.value) return
  stopStream()
  activeId.value = id
  await loadMessages()
}

async function loadMessages() {
  if (!activeId.value) return
  loading.value = true
  try {
    messages.value = await get(`/chat/sessions/${activeId.value}/messages`)
    pinned = true
    await nextTick(scrollBottom)
  } finally {
    loading.value = false
  }
}

const renamingId = ref(null)
const renameText = ref('')

function startRename(s) {
  renamingId.value = s.id
  renameText.value = s.title
}
async function saveRename() {
  const id = renamingId.value
  renamingId.value = null
  if (!id) return
  const title = renameText.value.trim()
  if (!title) return
  await patch(`/chat/sessions/${id}`, { title })
  const s = sessions.value.find((x) => x.id === id)
  if (s) s.title = title
}

async function removeSession(s) {
  if (!confirm(`删除会话「${s.title}」？`)) return
  if (s.id === activeId.value) stopStream()
  await apiDelete(`/chat/sessions/${s.id}`)
  sessions.value = sessions.value.filter((x) => x.id !== s.id)
  if (activeId.value === s.id) {
    activeId.value = null
    messages.value = []
  }
}

// ---------- 流式对话 ----------
function startTimer() {
  st.value.elapsedMs = 0
  const t0 = performance.now()
  timer = setInterval(() => (st.value.elapsedMs = performance.now() - t0), 100)
}
function stopTimer() {
  clearInterval(timer)
  timer = null
}

function stopStream() {
  // 中断：fetch 读流抛 AbortError，由 send/regenerate 的 catch 收尾落库展示
  abortCtl?.abort()
  abortCtl = null
}

async function ensureSession() {
  if (activeId.value) return activeId.value
  const s = await post('/chat/sessions', {})
  sessions.value.unshift(s)
  activeId.value = s.id
  messages.value = []
  return s.id
}

async function send({ content, images }) {
  const sid = await ensureSession()
  messages.value.push({
    id: `local-${Date.now()}`,
    role: 'user',
    content,
    images,
    status: 'complete',
  })
  pinned = true
  await nextTick(scrollBottom)
  await runStream(`/chat/sessions/${sid}/messages`, { content, images })
}

async function regenerate() {
  if (!activeId.value || streaming.value) return
  await runStream(`/chat/sessions/${activeId.value}/regenerate`, {})
}

async function runStream(url, body) {
  streaming.value = true
  st.value = { thinking: '', content: '', elapsedMs: 0, meta: null }
  abortCtl = new AbortController()
  startTimer()
  await nextTick(scrollBottom)

  const finishWith = (status) => {
    const { thinking, content, meta } = st.value
    if (thinking || content || status !== 'interrupted') {
      messages.value.push({
        id: meta?.message_id || `local-a-${Date.now()}`,
        role: 'assistant',
        content,
        thinking: thinking || null,
        duration_ms: meta?.duration_ms ?? st.value.elapsedMs,
        prompt_tokens: meta?.prompt_tokens ?? null,
        completion_tokens: meta?.completion_tokens ?? null,
        total_tokens: meta?.total_tokens ?? null,
        status,
      })
    }
  }

  try {
    await postSSE(url, body, {
      signal: abortCtl.signal,
      onEvent: (ev) => {
        if (ev.type === 'thinking_delta') {
          st.value.thinking += ev.text
        } else if (ev.type === 'content_delta') {
          st.value.content += ev.text
        } else if (ev.type === 'meta') {
          st.value.meta = { ...st.value.meta, ...ev }
        } else if (ev.type === 'error') {
          toast.value = ev.message
        } else if (ev.type === 'done') {
          st.value.meta = { ...st.value.meta, message_id: ev.message_id }
        }
        if (['thinking_delta', 'content_delta'].includes(ev.type)) {
          if (pinned) nextTick(scrollBottom)
        }
      },
    })
    finishWith('complete')
  } catch (err) {
    if (err.name === 'AbortError') {
      finishWith('interrupted')
    } else {
      finishWith('error')
      toast.value = String(err.message || err)
    }
  } finally {
    streaming.value = false
    stopTimer()
    abortCtl = null
    loadSessions() // 标题可能已随首条消息更新
    if (pinned) nextTick(scrollBottom)
  }
}

// ---------- 滚动跟随 ----------
function onScroll() {
  const el = scrollEl.value
  if (!el) return
  pinned = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}
function scrollBottom() {
  const el = scrollEl.value
  if (el && pinned) el.scrollTop = el.scrollHeight
}

watch(toast, (v) => {
  if (v) setTimeout(() => (toast.value = ''), 5000)
})

// 切走 tab 视为中断（App.vue 的 component :is 会卸载本组件）
onUnmounted(() => abortCtl?.abort())

onMounted(async () => {
  await loadSessions()
  if (sessions.value.length) {
    activeId.value = sessions.value[0].id
    await loadMessages()
  }
  get('/chat/asr/status').then((d) => (asrReady.value = !!d.ready)).catch(() => {})
})

const lastAssistantIdx = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'assistant') return i
  }
  return -1
})

// 重命名输入框自动聚焦（script setup 局部指令，模板里用 v-focus）
const vFocus = { mounted: (el) => el.focus() }
</script>

<template>
  <div class="flex h-[calc(100vh-4rem)]">
    <!-- 会话列表 -->
    <aside class="hidden w-64 shrink-0 flex-col border-r border-line bg-canvas-subtle md:flex">
      <div class="p-3">
        <button
          class="w-full rounded-md border border-accent-emphasis bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:bg-accent-emphasis/90"
          @click="newSession"
        >
          ＋ 新对话
        </button>
      </div>
      <ul class="flex-1 space-y-1 overflow-y-auto px-2 pb-3">
        <li v-for="s in sessions" :key="s.id">
          <div
            class="group flex cursor-pointer items-center gap-1 rounded-md border px-2.5 py-2 text-sm"
            :class="
              s.id === activeId
                ? 'border-line bg-canvas font-medium shadow-sm'
                : 'border-transparent hover:bg-canvas-inset'
            "
            @click="selectSession(s.id)"
          >
            <input
              v-if="renamingId === s.id"
              v-model="renameText"
              v-focus
              class="min-w-0 flex-1 rounded border border-accent bg-canvas px-1 py-0.5 text-sm outline-none"
              @keydown.enter="saveRename"
              @keydown.esc="renamingId = null"
              @blur="saveRename"
              @click.stop
            />
            <template v-else>
              <span class="min-w-0 flex-1 truncate" :title="s.title" @dblclick="startRename(s)">
                {{ s.title }}
              </span>
              <button
                class="hidden h-5 w-5 shrink-0 items-center justify-center rounded text-fg-subtle hover:text-danger group-hover:flex"
                title="删除会话"
                @click.stop="removeSession(s)"
              >
                ×
              </button>
            </template>
          </div>
        </li>
      </ul>
    </aside>

    <!-- 消息区 -->
    <section class="flex min-w-0 flex-1 flex-col">
      <div ref="scrollEl" class="flex-1 overflow-y-auto" @scroll="onScroll">
        <div class="mx-auto max-w-3xl space-y-6 px-4 py-6">
          <!-- 空状态 -->
          <div v-if="!activeId && !loading" class="mx-auto mt-16 max-w-md rounded-lg border border-dashed border-line bg-canvas p-10 text-center">
            <h2 class="text-lg font-semibold">开始新对话</h2>
            <p class="mt-2 text-sm text-fg-muted">点击左上角「新对话」，支持文字、图片、语音输入。</p>
          </div>

          <MessageItem
            v-for="(m, i) in messages"
            :key="m.id"
            :msg="m"
            :is-last-assistant="i === lastAssistantIdx && !streaming"
            :busy="streaming"
            @regenerate="regenerate"
          />

          <!-- 流式中的助手消息 -->
          <MessageItem
            v-if="streaming"
            :msg="{ role: 'assistant', content: st.content, thinking: st.thinking || null, status: 'complete' }"
            :streaming="true"
            :live-elapsed-ms="st.elapsedMs"
          />

          <div v-if="loading" class="py-10 text-center text-sm text-fg-subtle">加载中…</div>
        </div>
      </div>

      <!-- 错误提示 -->
      <div v-if="toast" class="border-t border-danger-subtle bg-danger-subtle px-4 py-2 text-center text-xs text-danger">
        {{ toast }}
      </div>

      <ChatInput
        :disabled="false"
        :streaming="streaming"
        :asr-ready="asrReady"
        @send="send"
        @stop="stopStream"
      />
    </section>
  </div>
</template>
