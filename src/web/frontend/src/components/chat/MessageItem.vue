<script setup>
// 单条消息渲染：思考框（可折叠）+ Markdown 正文 + 图片 + 元信息行
import { computed, ref, watch, nextTick } from 'vue'
import { renderMarkdown, highlightCode } from '../../utils/markdown.js'

const props = defineProps({
  msg: { type: Object, required: true },
  // 流式进行中的伪消息：思考框自动展开、显示光标
  streaming: { type: Boolean, default: false },
  liveElapsedMs: { type: Number, default: null },
  isLastAssistant: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['regenerate'])

const contentEl = ref(null)
const html = computed(() => (props.msg.role === 'assistant' ? renderMarkdown(props.msg.content) : ''))
const copied = ref(false)

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.msg.content)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    /* 剪贴板不可用时静默 */
  }
}

watch(
  () => props.msg.content,
  async () => {
    if (props.msg.role !== 'assistant') return
    await nextTick()
    highlightCode(contentEl.value)
  },
  { immediate: true },
)

const fmtTok = (n) => (n === null || n === undefined ? '—' : n)
const fmtDur = (ms) => (ms === null || ms === undefined ? '—' : `${(ms / 1000).toFixed(1)}s`)

// 工具徽标文案：read_skill 显示技能名，其余工具显示紧凑参数
function toolLabel(t) {
  if (t.name === 'read_skill') return `技能 ${t.args?.name ?? ''}`
  const s = JSON.stringify(t.args ?? {})
  return `${t.name} ${s.length > 46 ? `${s.slice(0, 46)}…` : s}`
}
</script>

<template>
  <article class="flex gap-3">
    <!-- 头像 -->
    <div
      class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
      :class="msg.role === 'user' ? 'bg-accent-subtle text-accent' : 'bg-fg-default text-white'"
    >
      <svg v-if="msg.role === 'user'" class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21c0-4 4-6 8-6s8 2 8 6" />
      </svg>
      <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      </svg>
    </div>

    <div class="min-w-0 flex-1">
      <!-- 用户消息：图片缩略图 + 文本 -->
      <template v-if="msg.role === 'user'">
        <div v-if="msg.images?.length" class="mb-2 flex flex-wrap gap-2">
          <img
            v-for="(src, i) in msg.images"
            :key="i"
            :src="src"
            class="h-28 rounded-md border border-line object-cover"
            alt="用户图片"
          />
        </div>
        <div v-if="msg.content" class="inline-block max-w-full whitespace-pre-wrap rounded-lg rounded-tl-sm border border-line bg-accent-subtle/60 px-3.5 py-2 text-sm">
          {{ msg.content }}
        </div>
      </template>

      <!-- 助手消息 -->
      <template v-else>
        <!-- 工具调用徽标 -->
        <div v-if="msg.toolUses?.length" class="mb-2 flex flex-wrap gap-1.5">
          <span
            v-for="(t, i) in msg.toolUses"
            :key="i"
            class="inline-flex items-center gap-1 rounded-full border border-line bg-canvas-subtle px-2 py-0.5 text-xs text-fg-muted"
          >
            <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
            {{ toolLabel(t) }}
          </span>
        </div>

        <!-- 思考过程包围框：流式时自动展开，完成后折叠可回看 -->
        <details v-if="msg.thinking" class="mb-2 rounded-md border border-line bg-canvas-subtle" :open="streaming">
          <summary class="cursor-pointer select-none px-3 py-1.5 text-xs font-medium text-fg-muted">
            已思考 <span v-if="!streaming && msg.duration_ms !== null">· 全程 {{ fmtDur(msg.duration_ms) }}</span>
            <span v-if="streaming" class="ml-1 text-attention">思考中…</span>
          </summary>
          <div class="max-h-72 overflow-y-auto whitespace-pre-wrap border-t border-line-muted px-3 py-2 text-xs leading-relaxed text-fg-muted">
            {{ msg.thinking }}
          </div>
        </details>

        <div v-if="msg.content" ref="contentEl" class="markdown-body" v-html="html"></div>
        <div v-else-if="streaming && !msg.thinking" class="text-sm text-fg-subtle">
          正在思考<span class="animate-pulse">…</span>
        </div>
        <span v-if="streaming && msg.content" class="inline-block h-4 w-2 animate-pulse bg-accent align-text-bottom"></span>

        <!-- 错误提示条 -->
        <div v-if="msg.status === 'error'" class="mt-2 rounded-md border border-danger-subtle bg-danger-subtle px-3 py-2 text-xs text-danger">
          生成失败，请检查网络或模型配置后重试。
        </div>
      </template>

      <!-- 元信息 / 操作行 -->
      <div
        v-if="msg.role === 'assistant' && !streaming && (msg.status !== 'complete' || msg.content)"
        class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-subtle"
      >
        <span v-if="msg.status === 'interrupted'" class="rounded bg-attention-subtle px-1.5 py-0.5 font-medium text-attention">已中断</span>
        <span v-if="msg.status === 'error'" class="rounded bg-danger-subtle px-1.5 py-0.5 font-medium text-danger">失败</span>
        <span>耗时 {{ fmtDur(msg.duration_ms) }}</span>
        <span v-if="msg.total_tokens !== null && msg.total_tokens !== undefined">
          tokens ↑{{ fmtTok(msg.prompt_tokens) }} ↓{{ fmtTok(msg.completion_tokens) }} 计{{ fmtTok(msg.total_tokens) }}
        </span>
        <button
          v-if="msg.content"
          class="transition hover:text-accent"
          @click="copyContent"
        >
          {{ copied ? '已复制' : '复制' }}
        </button>
        <button
          v-if="isLastAssistant && !busy"
          class="transition hover:text-accent"
          @click="emit('regenerate')"
        >
          重新生成
        </button>
      </div>
      <div v-else-if="streaming" class="mt-1.5 text-xs text-fg-subtle tabular-nums">
        已进行 {{ ((liveElapsedMs ?? 0) / 1000).toFixed(1) }}s
      </div>
    </div>
  </article>
</template>
