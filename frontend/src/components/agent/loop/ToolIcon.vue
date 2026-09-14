<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <g v-if="icon === 'file-read'"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M9 12h6M9 16h6"/></g>
    <g v-else-if="icon === 'image'"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></g>
    <g v-else-if="icon === 'file-write'"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M9 14h6M12 11v6"/></g>
    <g v-else-if="icon === 'file-edit'"><path d="M13 3H5v18h9M13 3v5h5V8l-5-5M11 19l1-4 7-7 3 3-7 7zM17 10l3 3"/></g>
    <g v-else-if="icon === 'terminal'"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/></g>
    <g v-else-if="icon === 'search-web'"><circle cx="10" cy="10" r="7"/><path d="M3 10h14M10 3c-4 4-4 10 0 14M10 3c4 4 4 10 0 14m5-2 6 6"/></g>
    <g v-else-if="icon === 'globe'"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c-5 5-5 13 0 18M12 3c5 5 5 13 0 18"/></g>
    <g v-else-if="icon === 'message-question'"><path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8l-5 3V6a2 2 0 0 1 2-2M10 9a2 2 0 1 1 3 1.7c-1 .6-1 1-1 1.3M12 15h.01"/></g>
    <g v-else-if="icon === 'task-add'"><path d="M8 5H5v16h10M16 5h3v6M9 10h4M9 14h2M18 14v7M14.5 17.5h7"/><rect x="8" y="3" width="8" height="4" rx="1"/></g>
    <g v-else-if="icon === 'list-check'"><path d="m3 6 2 2 3-4M11 6h10m-18 7 2 2 3-4M11 13h10M4 20h3M11 20h10"/></g>
    <g v-else-if="icon === 'circle-stop'"><circle cx="12" cy="12" r="9"/><rect x="8.5" y="8.5" width="7" height="7" rx="1"/></g>
    <g v-else-if="icon === 'folder-tree'"><path d="M3 4h6l2 3h10v7H3zM6 14v6h5M6 17h5M15 18h6v4h-6z"/></g>
    <g v-else-if="icon === 'files-search'"><path d="M8 3h10v6M5 6H3v15h10M6 6h9v4"/><circle cx="15" cy="15" r="4"/><path d="m18 18 3 3"/></g>
    <g v-else-if="icon === 'text-search'"><path d="M3 5h18M3 10h7M3 15h4M3 20h5"/><circle cx="15" cy="15" r="4"/><path d="m18 18 3 3"/></g>
    <g v-else-if="icon === 'code-edit'"><path d="m8 4-5 5 5 5m8-10 5 5-3 3M12 3l-2 12m2 6 1-4 6-6 3 3-6 6zM17 13l3 3"/></g>
    <g v-else-if="icon === 'cpu'"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2M9 2v2M15 20v2M9 20v2M2 15h2M2 9h2M20 15h2M20 9h2"/></g>
    <g v-else-if="icon === 'database'"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"/></g>
    <g v-else-if="icon === 'book-open'"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></g>
    <g v-else-if="icon === 'bar-chart'"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/><path d="M3 20h18"/></g>
    <g v-else-if="icon === 'sliders'"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></g>
    <g v-else-if="icon === 'check-circle'"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></g>
    <g v-else-if="icon === 'plug'"><path d="M8 3v5M16 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4"/></g>
    <g v-else-if="icon === 'wrench'"><path d="M21 7a6 6 0 0 1-8 7L6 21a2 2 0 0 1-3-3l7-7a6 6 0 0 1 7-8l-4 4 4 4z"/></g>
    <path v-else d="m14 4 6 6-4 4-2-2-8 8-2-2 8-8-2-2z"/>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { toolAliases } from '../../../agent/loop/toolPresentation'

/** 静态路径来自已评审本地 SVG 稿，禁止加载工具返回的 SVG。 */
interface Props {
  name: string
  size?: number | string
}

const props = withDefaults(defineProps<Props>(), {
  size: 20,
})

const icons: Record<string, string> = {
  read: 'file-read',
  read_image: 'image',
  write: 'file-write',
  edit: 'file-edit',
  bash: 'terminal',
  web_search: 'search-web',
  web_fetch: 'globe',
  ask_user_question: 'message-question',
  task: 'list-check',
  TaskCreate: 'task-add',
  TaskGet: 'list-check',
  TaskUpdate: 'file-edit',
  TaskList: 'list-check',
  'task.create': 'task-add',
  'task.status': 'list-check',
  'task.cancel': 'circle-stop',
  list_dir: 'folder-tree',
  glob: 'files-search',
  grep: 'text-search',
  str_replace_editor: 'code-edit',
}

const icon = computed(() => {
  // 媒体工具先按原始逻辑名判别，避免中文展示别名影响图标选择。
  if (props.name.startsWith('image.') || props.name.startsWith('video.')) return 'image'
  const resolved = toolAliases[props.name] || props.name
  if (icons[resolved]) return icons[resolved]
  if (resolved.startsWith('model.')) return 'cpu'
  if (resolved.startsWith('dataset.')) return 'database'
  if (resolved.startsWith('kb.')) return 'book-open'
  if (resolved.startsWith('report.')) return 'bar-chart'
  if (resolved.startsWith('dispatch.')) return 'sliders'
  if (resolved.startsWith('testcase.')) return 'check-circle'
  return 'wrench'
})
</script>
