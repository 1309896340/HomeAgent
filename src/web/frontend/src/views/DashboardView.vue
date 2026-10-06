<script setup>
// 仪表盘（demo 静态数据，后续接后端 API）

const stats = [
  {
    label: '设备在线',
    value: '12 / 14',
    trend: '2 台离线',
    trendType: 'attention',
    icon: 'M13 2 3 14h7l-1 8 10-12h-7l1-8z', // zap
  },
  {
    label: '自动化任务',
    value: '8',
    trend: '本周新增 1 个',
    trendType: 'success',
    icon: 'M4 7h11M4 12h11M4 17h11M18 5v4M18 15v4M16 7h4M16 17h4', // sliders
  },
  {
    label: '今日语音指令',
    value: '23',
    trend: '较昨日 +15%',
    trendType: 'success',
    icon: 'M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2M12 19v3', // mic
  },
  {
    label: '未读消息',
    value: '5',
    trend: '3 条来自门锁',
    trendType: 'default',
    icon: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z', // message
  },
]

const weekCommands = [
  { day: '周一', count: 12 },
  { day: '周二', count: 18 },
  { day: '周三', count: 9 },
  { day: '周四', count: 24 },
  { day: '周五', count: 31 },
  { day: '周六', count: 15 },
  { day: '周日', count: 22 },
]
const maxCount = Math.max(...weekCommands.map((d) => d.count))

const services = [
  { name: '后端 API', detail: 'http://localhost:8000', status: 'running' },
  { name: 'ASR 语音识别', detail: 'faster-whisper', status: 'running' },
  { name: 'MQTT Broker', detail: 'mqtt://home.local:1883', status: 'running' },
  { name: '消息队列', detail: '重连中 · 第 3 次尝试', status: 'degraded' },
]

const activities = [
  { time: '10:24', text: '语音指令「打开客厅灯」执行成功', scene: '客厅', type: 'success' },
  { time: '09:57', text: '自动化「离家模式」触发，关闭全部灯光', scene: '全屋', type: 'default' },
  { time: '09:30', text: '大门传感器离线超过 10 分钟', scene: '门厅', type: 'attention' },
  { time: '08:12', text: '扫地机器人完成任务，返回充电座', scene: '全屋', type: 'default' },
  { time: '07:45', text: '自动化「早安模式」触发，播放天气预报', scene: '卧室', type: 'default' },
]

const trendClass = {
  success: 'text-success',
  attention: 'text-attention',
  default: 'text-fg-muted',
}

const serviceDot = {
  running: 'bg-success',
  degraded: 'bg-attention',
  down: 'bg-danger',
}

const activityDot = {
  success: 'bg-success',
  attention: 'bg-attention',
  default: 'bg-fg-subtle',
}
</script>

<template>
  <div class="space-y-6">
    <!-- 页头 -->
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">仪表盘</h1>
        <p class="mt-1 text-sm text-fg-muted">早上好，wind。以下是你的家庭概况。</p>
      </div>
      <div class="flex gap-2">
        <button
          class="rounded-md border border-line bg-canvas px-3 py-1.5 text-sm font-medium text-fg-default transition hover:bg-canvas-subtle"
        >
          刷新
        </button>
        <button
          class="rounded-md border border-accent-emphasis bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:bg-accent-emphasis/90"
        >
          新建自动化
        </button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div
        v-for="stat in stats"
        :key="stat.label"
        class="rounded-lg border border-line bg-canvas p-4 shadow-sm"
      >
        <div class="flex items-center justify-between">
          <span class="text-sm text-fg-muted">{{ stat.label }}</span>
          <span class="flex h-8 w-8 items-center justify-center rounded-md bg-accent-subtle">
            <svg
              class="h-4 w-4 text-accent"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path :d="stat.icon" />
            </svg>
          </span>
        </div>
        <div class="mt-2 text-3xl font-semibold tabular-nums">{{ stat.value }}</div>
        <div class="mt-1 text-xs" :class="trendClass[stat.trendType]">{{ stat.trend }}</div>
      </div>
    </div>

    <!-- 图表 + 服务状态 -->
    <div class="grid gap-4 lg:grid-cols-3">
      <section class="rounded-lg border border-line bg-canvas p-5 shadow-sm lg:col-span-2">
        <div class="flex items-center justify-between">
          <h2 class="font-semibold">近 7 日语音指令</h2>
          <span class="text-xs text-fg-muted">共 131 次</span>
        </div>
        <div class="mt-6 flex h-44 items-end gap-3">
          <div v-for="d in weekCommands" :key="d.day" class="flex h-full flex-1 flex-col items-center justify-end gap-2">
            <span class="text-xs text-fg-muted tabular-nums">{{ d.count }}</span>
            <div
              class="w-full rounded-t-md transition-all"
              :class="d.count === maxCount ? 'bg-accent' : 'bg-accent/40'"
              :style="{ height: `${(d.count / maxCount) * 100}%` }"
              :title="`${d.day}：${d.count} 次`"
            ></div>
            <span class="text-xs text-fg-muted">{{ d.day }}</span>
          </div>
        </div>
      </section>

      <section class="rounded-lg border border-line bg-canvas p-5 shadow-sm">
        <h2 class="font-semibold">服务状态</h2>
        <ul class="mt-4 space-y-3">
          <li v-for="s in services" :key="s.name" class="flex items-start gap-3">
            <span class="mt-1.5 h-2 w-2 shrink-0 rounded-full" :class="serviceDot[s.status]"></span>
            <div class="min-w-0">
              <div class="text-sm font-medium">{{ s.name }}</div>
              <div class="truncate text-xs text-fg-muted">{{ s.detail }}</div>
            </div>
          </li>
        </ul>
        <div class="mt-5 rounded-md border border-attention-subtle bg-attention-subtle px-3 py-2 text-xs text-attention">
          消息队列正在重连，暂不影响本地控制。
        </div>
      </section>
    </div>

    <!-- 最近活动 -->
    <section class="rounded-lg border border-line bg-canvas shadow-sm">
      <div class="flex items-center justify-between border-b border-line-muted px-5 py-3">
        <h2 class="font-semibold">最近活动</h2>
        <a href="#" class="text-sm text-accent hover:underline">查看全部</a>
      </div>
      <ul class="divide-y divide-line-muted">
        <li v-for="a in activities" :key="a.time + a.text" class="flex items-center gap-3 px-5 py-3 text-sm">
          <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="activityDot[a.type]"></span>
          <span class="flex-1">{{ a.text }}</span>
          <span class="hidden text-xs text-fg-muted sm:inline">{{ a.scene }}</span>
          <span class="w-12 text-right text-xs text-fg-subtle tabular-nums">{{ a.time }}</span>
        </li>
      </ul>
    </section>
  </div>
</template>
