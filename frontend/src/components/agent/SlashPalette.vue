<template>
  <!-- 斜杠命令悬浮面板（极简毛玻璃卡片、SVG 图标、键盘导航与微交互） -->
  <div v-if="show" class="slash-palette-wrap" @mousedown.prevent>
    <!-- 顶部导引栏 -->
    <div class="slash-palette-head">
      <div class="slash-palette-title-wrap">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="5" y1="19" x2="19" y2="5"></line>
        </svg>
        <span class="slash-palette-title">快捷斜杠命令</span>
      </div>
      <div class="slash-palette-kbd-group">
        <span class="kbd"><kbd>↑</kbd><kbd>↓</kbd> 导航</span>
        <span class="kbd"><kbd>↵</kbd> 填入</span>
        <span class="kbd"><kbd>Esc</kbd> 关闭</span>
      </div>
    </div>

    <!-- 命令列表滚动区 -->
    <div ref="bodyRef" class="slash-palette-body">
      <!-- 1. 系统 15 条必带命令分组 -->
      <div v-for="group in filteredGroups" :key="group.key" class="slash-group">
        <div class="slash-group-label">{{ group.label }}</div>
        <div
          v-for="cmd in group.items"
          :key="cmd.name"
          :data-cmd="cmd.name"
          class="slash-item"
          :class="{
            active: activeName === cmd.name,
            disabled: !cmd.enabled,
          }"
          @click="handleItemClick(cmd)"
          @mouseenter="setActive(cmd)"
        >
          <div class="slash-item-left">
            <div class="slash-item-icon" :class="[group.key, { disabled: !cmd.enabled }]">
              <svg v-if="cmd.name === 'benchmark'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M18 20V10M12 20V4M6 20v-6" />
              </svg>
              <svg v-else-if="cmd.name === 'rag'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
              </svg>
              <svg v-else-if="cmd.name === 'testcase'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <path d="m9 12 2 2 4-4" />
              </svg>
              <svg v-else-if="cmd.name === 'stress'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
              <svg v-else-if="cmd.name === 'cancel'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="9" />
                <line x1="9" y1="9" x2="15" y2="15" />
                <line x1="15" y1="9" x2="9" y2="15" />
              </svg>
              <svg v-else-if="cmd.name === 'rerun'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="23 4 23 10 17 10" />
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
              </svg>
              <svg v-else-if="cmd.name === 'stop'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              <svg v-else-if="cmd.name === 'new'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="9" />
                <line x1="12" y1="8" x2="12" y2="16" />
                <line x1="8" y1="12" x2="16" y2="12" />
              </svg>
              <svg v-else-if="cmd.name === 'compact'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="4 14 10 14 10 20" />
                <polyline points="20 10 14 10 14 4" />
                <line x1="14" y1="10" x2="21" y2="3" />
                <line x1="3" y1="21" x2="10" y2="14" />
              </svg>
              <svg v-else-if="cmd.name === 'status'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
              <svg v-else-if="cmd.name === 'profiles'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="4" y="4" width="16" height="16" rx="2" />
                <rect x="9" y="9" width="6" height="6" />
                <line x1="9" y1="1" x2="9" y2="4" />
                <line x1="15" y1="1" x2="15" y2="4" />
              </svg>
              <svg v-else-if="cmd.name === 'datasets'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <ellipse cx="12" cy="5" rx="9" ry="3" />
                <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
              </svg>
              <svg v-else-if="cmd.name === 'kb'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
              </svg>
              <svg v-else-if="cmd.name === 'report'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
              <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10" />
                <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            </div>
            <div class="slash-item-content">
              <span class="slash-item-name mono">/{{ cmd.name }}</span>
              <span class="slash-item-hint">{{ cmd.hint }}</span>
            </div>
          </div>
          <div class="slash-item-right">
            <span v-if="!cmd.enabled" class="slash-item-badge disabled">{{ cmd.reason || '未启用' }}</span>
            <span v-else-if="activeName === cmd.name" class="slash-item-arrow">↵</span>
          </div>
        </div>
      </div>

      <!-- 2. 我的命令（团队自定义命令） -->
      <div v-if="customCommands.length > 0" class="slash-group custom-group">
        <div class="slash-group-label">我的命令</div>
        <div
          v-for="cmd in customCommands"
          :key="cmd.id"
          :data-cmd="cmd.name"
          class="slash-item"
          :class="{ active: activeName === cmd.name }"
          @click="handleCustomClick(cmd)"
          @mouseenter="activeName = cmd.name"
        >
          <div class="slash-item-left">
            <div class="slash-item-icon custom">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
              </svg>
            </div>
            <div class="slash-item-content">
              <span class="slash-item-name mono">/{{ cmd.name }}</span>
              <span class="slash-item-hint">{{ cmd.hint }}</span>
            </div>
          </div>
          <div class="slash-item-right">
            <span v-if="activeName === cmd.name" class="slash-item-arrow">↵</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { SYSTEM_SLASH_COMMANDS, type SlashCommandDef } from '../../agent/slashRegistry'
import { api } from '../../api/http'

const props = withDefaults(
  defineProps<{
    show: boolean
    filterQuery?: string
  }>(),
  {
    show: false,
    filterQuery: '',
  },
)

const emit = defineEmits<{
  (e: 'select', text: string): void
  (e: 'close'): void
}>()

const bodyRef = ref<HTMLDivElement | null>(null)
const activeName = ref<string>('benchmark')
const customCommands = ref<any[]>([])

const GROUP_LABELS: Record<string, string> = {
  order: '评测与执行',
  control: '会话与控制',
  readonly: '资产与查询',
  system: '帮助与支持',
}

const filteredGroups = computed(() => {
  const q = (props.filterQuery || '').trim().toLowerCase().replace(/^\//, '')
  const groups: { key: string; label: string; items: SlashCommandDef[] }[] = [
    { key: 'order', label: GROUP_LABELS.order, items: [] },
    { key: 'control', label: GROUP_LABELS.control, items: [] },
    { key: 'readonly', label: GROUP_LABELS.readonly, items: [] },
    { key: 'system', label: GROUP_LABELS.system, items: [] },
  ]

  for (const cmd of SYSTEM_SLASH_COMMANDS) {
    if (!q || cmd.name.toLowerCase().includes(q) || cmd.hint.toLowerCase().includes(q)) {
      const g = groups.find((grp) => grp.key === cmd.group)
      if (g) g.items.push(cmd)
    }
  }

  return groups.filter((g) => g.items.length > 0)
})

const flatEnabledItems = computed(() => {
  const list: (SlashCommandDef | { name: string; template: string; enabled: boolean })[] = []
  for (const g of filteredGroups.value) {
    for (const item of g.items) {
      if (item.enabled) list.push(item)
    }
  }
  for (const c of customCommands.value) {
    list.push({ name: c.name, template: c.template, enabled: true })
  }
  return list
})

function setActive(cmd: SlashCommandDef) {
  if (cmd.enabled) {
    activeName.value = cmd.name
  }
}

function handleItemClick(cmd: SlashCommandDef) {
  if (!cmd.enabled) return
  emit('select', `/${cmd.name}`)
}

function handleCustomClick(cmd: any) {
  emit('select', cmd.template || `/${cmd.name}`)
}

function scrollToActive() {
  nextTick(() => {
    if (!bodyRef.value) return
    const activeEl = bodyRef.value.querySelector(`.slash-item[data-cmd="${activeName.value}"]`) as HTMLElement | null
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  })
}

// 监听过滤条件变化，重置高亮首项
watch(
  () => props.filterQuery,
  () => {
    const first = flatEnabledItems.value[0]
    if (first) {
      activeName.value = first.name
      scrollToActive()
    }
  },
)

watch(
  () => props.show,
  (val) => {
    if (val) {
      const first = flatEnabledItems.value[0]
      if (first) activeName.value = first.name
      scrollToActive()
    }
  },
)

async function loadCustomCommands() {
  // 说明：依 API.md §3.4 与说明书 AGT-SLH-03，后端 /api/slash-commands 在 M1 为桩（严格返回 VALIDATION 400「自定义命令未启用」）。
  // 完整自定义斜杠 CRUD 将在 M2（AGT-M2-04）开放。M1 阶段默认置空，避免在控制台产生无意义的网络 400 日志。
  customCommands.value = []
}

onMounted(() => {
  loadCustomCommands()
})

/**
 * 键盘导航拦截（由父级 Composer 调用）
 */
function handleKeyDown(e: KeyboardEvent): boolean {
  if (!props.show) return false

  const items = flatEnabledItems.value
  if (!items.length) return false

  const currentIndex = items.findIndex((i) => i.name === activeName.value)

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    const nextIdx = (currentIndex + 1) % items.length
    activeName.value = items[nextIdx].name
    scrollToActive()
    return true
  }

  if (e.key === 'ArrowUp') {
    e.preventDefault()
    const prevIdx = (currentIndex - 1 + items.length) % items.length
    activeName.value = items[prevIdx].name
    scrollToActive()
    return true
  }

  if (e.key === 'Enter' || e.key === 'Tab') {
    const activeItem = items.find((i) => i.name === activeName.value)
    if (activeItem) {
      e.preventDefault()
      emit('select', ('template' in activeItem && activeItem.template) ? activeItem.template : `/${activeItem.name}`)
      return true
    }
  }

  if (e.key === 'Escape') {
    e.preventDefault()
    emit('close')
    return true
  }

  return false
}

defineExpose({
  handleKeyDown,
})
</script>

<style scoped>
.slash-palette-wrap {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 0;
  width: 380px;
  max-height: 400px;
  background: var(--bg-surface, rgba(15, 23, 42, 0.94));
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.12));
  border-radius: 14px;
  box-shadow: 0 16px 40px -6px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 100;
  animation: palette-in 0.16s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes palette-in {
  from {
    opacity: 0;
    transform: translateY(6px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.slash-palette-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 14px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
}

.slash-palette-title-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--accent-ai, #10b981);
}

.slash-palette-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary, #cbd5e1);
  letter-spacing: 0.2px;
}

.slash-palette-kbd-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.slash-palette-kbd-group .kbd {
  font-size: 11px;
  color: var(--text-tertiary, #64748b);
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.slash-palette-kbd-group kbd {
  display: inline-block;
  padding: 1px 4px;
  font-family: inherit;
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  color: var(--text-secondary, #94a3b8);
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 4px;
}

.slash-palette-body {
  flex: 1;
  overflow-y: auto;
  padding: 6px 6px 8px;
  max-height: 340px;
  scrollbar-width: thin;
}

.slash-group {
  margin-bottom: 6px;
}

.slash-group-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary, #64748b);
  padding: 6px 10px 3px;
  letter-spacing: 0.4px;
}

.slash-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  margin: 1px 0;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.12s ease;
  user-select: none;
}

.slash-item:hover:not(.disabled) {
  background: rgba(255, 255, 255, 0.05);
}

.slash-item.active:not(.disabled) {
  background: color-mix(in srgb, var(--accent-ai, #10b981) 14%, transparent);
}

.slash-item.disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.slash-item-left {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  flex: 1;
}

.slash-item-icon {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.04);
  color: var(--accent-ai, #10b981);
  flex-shrink: 0;
  border: 1px solid rgba(255, 255, 255, 0.05);
  transition: all 0.15s ease;
}

.slash-item.active .slash-item-icon {
  background: color-mix(in srgb, var(--accent-ai, #10b981) 22%, transparent);
  border-color: color-mix(in srgb, var(--accent-ai, #10b981) 35%, transparent);
}

.slash-item-icon.control {
  color: #38bdf8;
}
.slash-item-icon.readonly {
  color: #a78bfa;
}
.slash-item-icon.system {
  color: #f59e0b;
}
.slash-item-icon.custom {
  color: #ec4899;
}
.slash-item-icon.disabled {
  color: var(--text-tertiary, #64748b);
}

.slash-item-content {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.slash-item-name {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text-primary, #ffffff);
}

.slash-item.active .slash-item-name {
  color: var(--accent-ai, #10b981);
}

.slash-item.disabled .slash-item-name {
  color: var(--text-tertiary, #64748b);
}

.slash-item-hint {
  font-size: 12.5px;
  color: var(--text-secondary, #94a3b8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.slash-item.active .slash-item-hint {
  color: var(--text-primary, #f1f5f9);
}

.slash-item-right {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 8px;
  flex-shrink: 0;
}

.slash-item-badge {
  font-size: 10.5px;
  padding: 1.5px 7px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-tertiary, #64748b);
  white-space: nowrap;
}

.slash-item-badge.disabled {
  background: rgba(148, 163, 184, 0.08);
  color: var(--text-tertiary, #64748b);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.slash-item-arrow {
  font-size: 12px;
  font-weight: bold;
  color: var(--accent-ai, #10b981);
  padding: 0 2px;
}
</style>
