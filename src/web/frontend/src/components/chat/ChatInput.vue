<script setup>
// 多模态输入区：文字 + 图片（选文件/粘贴/拖拽）+ 语音（录音/上传音频）
import { ref, watch, nextTick, onUnmounted } from 'vue'
import { upload } from '../../api/client.js'

const props = defineProps({
  disabled: { type: Boolean, default: false }, // 无会话时整体禁用
  streaming: { type: Boolean, default: false }, // 生成中：发送变停止
  asrReady: { type: Boolean, default: false }, // ASR 未就绪时麦克风置灰
})
const emit = defineEmits(['send', 'stop'])

const text = ref('')
const images = ref([]) // [{ dataUrl, name, size }]
const fileInput = ref(null)
const audioInput = ref(null)
const ta = ref(null)
const notice = ref('')

const micTitle = () =>
  !props.asrReady ? '语音识别服务未就绪' : recording.value ? '停止录音' : '开始录音'

// ---------- 发送 ----------
function doSend() {
  if (props.disabled || props.streaming) return
  const content = text.value.trim()
  if (!content && images.value.length === 0) return
  emit('send', { content, images: images.value.map((i) => i.dataUrl) })
  text.value = ''
  images.value = []
  autoSize()
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    doSend()
  }
}

function autoSize() {
  const el = ta.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}
watch(text, () => nextTick(autoSize))

// ---------- 图片 ----------
const MAX_IMAGES = 4
const MAX_BYTES = 5 * 1024 * 1024

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result)
    r.onerror = reject
    r.readAsDataURL(file)
  })
}

async function addImages(files) {
  notice.value = ''
  for (const f of files) {
    if (!f.type.startsWith('image/')) continue
    if (images.value.length >= MAX_IMAGES) {
      notice.value = `每条消息最多 ${MAX_IMAGES} 张图片`
      break
    }
    if (f.size > MAX_BYTES) {
      notice.value = `「${f.name}」超过 5MB，已跳过`
      continue
    }
    images.value.push({ dataUrl: await fileToDataUrl(f), name: f.name, size: f.size })
  }
}

function pickImages() {
  fileInput.value?.click()
}
function onFilesPicked(e) {
  addImages([...e.target.files])
  e.target.value = ''
}
function removeImage(i) {
  images.value.splice(i, 1)
}

function onPaste(e) {
  const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/'))
  if (files.length) {
    e.preventDefault()
    addImages(files)
  }
}

// 拖拽：图片直接加，音频文件走转写
function onDrop(e) {
  const files = [...(e.dataTransfer?.files || [])]
  const imgs = files.filter((f) => f.type.startsWith('image/'))
  const audio = files.find((f) => f.type.startsWith('audio/'))
  if (imgs.length) addImages(imgs)
  if (audio) transcribeFile(audio)
}

// ---------- 语音输入 ----------
const recording = ref(false)
const recordSeconds = ref(0)
const transcribing = ref(false)
let mediaRecorder = null
let chunks = []
let recStream = null
let audioCtx = null
let analyser = null
let meterTimer = null
let maxAmplitude = 0
let tickTimer = null

async function toggleRecord() {
  if (recording.value) {
    stopRecording()
    return
  }
  notice.value = ''
  try {
    recStream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch {
    notice.value = '无法访问麦克风，请检查浏览器权限'
    return
  }
  chunks = []
  maxAmplitude = 0
  // 挂 AnalyserNode 做音量监测：无语音输入 ASR 会产生幻觉文本，静音录音直接丢弃
  audioCtx = new AudioContext()
  const source = audioCtx.createMediaStreamSource(recStream)
  analyser = audioCtx.createAnalyser()
  analyser.fftSize = 1024
  source.connect(analyser)
  const buf = new Float32Array(analyser.fftSize)
  meterTimer = setInterval(() => {
    analyser.getFloatTimeDomainData(buf)
    for (const v of buf) maxAmplitude = Math.max(maxAmplitude, Math.abs(v))
  }, 200)

  mediaRecorder = new MediaRecorder(recStream)
  mediaRecorder.ondataavailable = (e) => chunks.push(e.data)
  mediaRecorder.onstop = onRecordStop
  mediaRecorder.start()
  recording.value = true
  recordSeconds.value = 0
  tickTimer = setInterval(() => (recordSeconds.value += 1), 1000)
}

function stopRecording() {
  mediaRecorder?.stop()
  recording.value = false
  clearInterval(tickTimer)
  clearInterval(meterTimer)
}

async function onRecordStop() {
  recStream?.getTracks().forEach((t) => t.stop())
  await audioCtx?.close()
  const blob = new Blob(chunks, { type: mediaRecorder.mimeType || 'audio/webm' })
  mediaRecorder = null
  if (recordSeconds.value < 1) {
    notice.value = '录音太短'
    return
  }
  if (maxAmplitude < 0.01) {
    notice.value = '未检测到声音，录音已丢弃'
    return
  }
  await sendAudio(blob, `rec_${Date.now()}.webm`)
}

async function transcribeFile(file) {
  await sendAudio(file, file.name || 'audio.webm')
}

async function sendAudio(blob, filename) {
  notice.value = ''
  transcribing.value = true
  try {
    const data = await upload('/chat/transcribe', new File([blob], filename, { type: blob.type }))
    if (data.text) {
      text.value = text.value ? `${text.value} ${data.text}` : data.text
      nextTick(() => ta.value?.focus())
    } else {
      notice.value = '没有识别到内容'
    }
  } catch (err) {
    notice.value = String(err.message || err)
  } finally {
    transcribing.value = false
  }
}

onUnmounted(() => {
  if (recording.value) stopRecording()
  recStream?.getTracks().forEach((t) => t.stop())
  audioCtx?.close()
})
</script>

<template>
  <div
    class="border-t border-line bg-canvas px-4 py-3"
    @paste="onPaste"
    @dragover.prevent
    @drop.prevent="onDrop"
  >
    <div v-if="notice" class="mx-auto mb-2 max-w-3xl rounded-md border border-attention-subtle bg-attention-subtle px-3 py-1.5 text-xs text-attention">
      {{ notice }}
    </div>

    <!-- 图片预览 -->
    <div v-if="images.length" class="mx-auto mb-2 flex max-w-3xl flex-wrap gap-2">
      <div v-for="(img, i) in images" :key="i" class="group relative">
        <img :src="img.dataUrl" class="h-16 rounded-md border border-line object-cover" :alt="img.name" />
        <button
          class="absolute -right-1.5 -top-1.5 hidden h-5 w-5 items-center justify-center rounded-full border border-line bg-canvas text-xs text-fg-muted shadow-sm group-hover:flex hover:text-danger"
          @click="removeImage(i)"
        >×</button>
      </div>
    </div>

    <div class="mx-auto flex max-w-3xl items-end gap-2 rounded-lg border border-line bg-canvas p-2 shadow-sm focus-within:border-fg-subtle">
      <!-- 工具列 -->
      <div class="flex items-center gap-1">
        <button
          class="flex h-8 w-8 items-center justify-center rounded-md text-fg-muted transition hover:bg-canvas-subtle hover:text-fg-default disabled:opacity-40"
          title="添加图片（也可粘贴 / 拖拽）"
          :disabled="disabled || streaming"
          @click="pickImages"
        >
          <svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <path d="M21 15l-5-5L5 21" />
          </svg>
        </button>
        <button
          class="flex h-8 w-8 items-center justify-center rounded-md text-fg-muted transition hover:bg-canvas-subtle hover:text-fg-default disabled:opacity-40"
          title="上传音频文件转写"
          :disabled="disabled || streaming || transcribing"
          @click="audioInput?.click()"
        >
          <svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 18V5l12-2v13" />
            <circle cx="6" cy="18" r="3" />
            <circle cx="18" cy="16" r="3" />
          </svg>
        </button>
        <button
          class="flex h-8 items-center justify-center gap-1 rounded-md px-2 text-fg-muted transition hover:bg-canvas-subtle disabled:opacity-40"
          :class="recording ? 'text-danger' : ''"
          :title="micTitle()"
          :disabled="disabled || streaming || transcribing || (!asrReady && !recording)"
          @click="toggleRecord"
        >
          <span v-if="recording" class="h-2 w-2 animate-pulse rounded-full bg-danger"></span>
          <svg v-if="!recording" class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <path d="M12 19v3" />
          </svg>
          <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
          <span v-if="recording" class="text-xs tabular-nums">{{ recordSeconds }}s</span>
          <span v-if="transcribing" class="text-xs">转写中…</span>
        </button>
      </div>

      <textarea
        ref="ta"
        v-model="text"
        rows="1"
        class="max-h-52 min-h-8 flex-1 resize-none bg-transparent px-1 py-1.5 text-sm outline-none placeholder:text-fg-subtle"
        :placeholder="disabled ? '先新建或选择一个会话' : '输入消息，Enter 发送，Shift+Enter 换行'"
        :disabled="disabled"
        @keydown="onKeydown"
      ></textarea>

      <!-- 发送 / 停止 -->
      <button
        v-if="!streaming"
        class="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-white transition hover:bg-accent-emphasis disabled:opacity-40"
        title="发送"
        :disabled="disabled || (!text.trim() && images.length === 0)"
        @click="doSend"
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M22 2L11 13" />
          <path d="M22 2l-7 20-4-9-9-4 20-7z" />
        </svg>
      </button>
      <button
        v-else
        class="flex h-8 w-8 items-center justify-center rounded-md border border-danger bg-canvas text-danger transition hover:bg-danger-subtle"
        title="停止生成"
        @click="emit('stop')"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
          <rect x="6" y="6" width="12" height="12" rx="2" />
        </svg>
      </button>
    </div>

    <p class="mx-auto mt-1.5 max-w-3xl text-center text-[11px] text-fg-subtle">
      内容由 AI 生成，请注意甄别
    </p>

    <input ref="fileInput" type="file" accept="image/*" multiple class="hidden" @change="onFilesPicked" />
    <input
      ref="audioInput"
      type="file"
      accept="audio/*"
      class="hidden"
      @change="(e) => { const f = e.target.files[0]; if (f) transcribeFile(f); e.target.value = '' }"
    />
  </div>
</template>
