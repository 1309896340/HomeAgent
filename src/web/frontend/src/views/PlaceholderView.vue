<script setup>
// 未实现模块的占位页（GitHub blankslate 风格）
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
})
</script>

<template>
  <div class="mx-auto mt-16 max-w-md rounded-lg border border-dashed border-line bg-canvas p-10 text-center">
    <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-canvas-subtle">
      <svg
        class="h-6 w-6 text-fg-subtle"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <path d="M9 9h6v6H9z" />
      </svg>
    </div>
    <h2 class="mt-4 text-lg font-semibold">{{ title }}</h2>
    <p class="mt-2 text-sm text-fg-muted">
      {{ description || '该模块正在规划中，敬请期待。' }}
    </p>
    <button
      class="mt-6 cursor-not-allowed rounded-md border border-line bg-canvas-subtle px-3 py-1.5 text-sm font-medium text-fg-subtle"
      disabled
    >
      开始配置（开发中）
    </button>
  </div>
</template>
