<template>
  <!-- 斜杠命令悬浮面板（开发说明书 §9 / §16.4 / §16.5 冻结，宽 360px） -->
  <div v-if="show" class="slash-palette-wrap" @mousedown.prevent>
    <div class="slash-palette-head">
      <span class="slash-palette-title">快捷斜杠命令</span>
      <span class="slash-palette-kbd mono">↑ / ↓ 导航 · Enter 确认 · Esc 关闭</span>
    </div>

    <div class="slash-palette-body">
      <!-- 1. 上区：系统 15 条必带命令（只读不可删） -->
      <div v-for="group in filteredGroups" :key="group.key" class="slash-group">
        <div class="slash-group-label">{{ group.label }}</div>
        <div
          v-for="cmd in group.items"
          :key="cmd.name"
          class="slash-item"
          :class="{
            active: activeName === cmd.name,
            disabled: !cmd.enabled,
          }"
          @click="handleItemClick(cmd)"
          @mouseenter="setActive(cmd)"
        >
          <div class="slash-item-left">
            <span class="slash-item-name mono">/{{ cmd.name }}</span>
            <span class="slash-item-hint">{{ cmd.hint }}</span>
          </div>
          <div class="slash-item-right">
            <span v-if="!cmd.enabled" class="slash-item-badge disabled">{{ cmd.reason || '未启用' }}</span>
          </div>
        </div>
      </div>

      <!-- 2. 下区：我的命令（团队自定义命令） -->
      <div class="slash-group custom-group">
        <div class="slash-group-label">我的命令</div>
        <div v-if="customCommands.length === 0" class="slash-empty-note">
          <span>自定义命令未启用</span>
        </div>
        <div
          v-for="cmd in customCommands"
          :key="cmd.id"
          class="slash-item"
          :class="{ active: activeName === cmd.name }"
          @click="handleCustomClick(cmd)"
          @mouseenter="activeName = cmd.name"
        >
          <div class="slash-item-left">
            <span class="slash-item-name mono">/{{ cmd.name }}</span>
            <span class="slash-item-hint">{{ cmd.hint }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
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

const activeName = ref<string>('benchmark')
const customCommands = ref<any[]>([])

const GROUP_LABELS: Record<string, string> = {
  order: '评测下单',
  control: '会话控制',
  readonly: '资产与只读查询',
  system: '系统帮助',
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

watch(
  () => props.show,
  (isOpen) => {
    if (isOpen) {
      const first = flatEnabledItems.value[0]
      if (first) activeName.value = first.name
      fetchCustomCommands()
    }
  },
)

async function fetchCustomCommands() {
  try {
    const res = await api.slashCommands.list().catch(() => null)
    if (res && Array.isArray(res.items)) {
      customCommands.value = res.items
    } else {
      customCommands.value = []
    }
  } catch {
    customCommands.value = []
  }
}

function setActive(cmd: SlashCommandDef) {
  if (cmd.enabled) {
    activeName.value = cmd.name
  }
}

function handleItemClick(cmd: SlashCommandDef) {
  if (!cmd.enabled) return
  emit('select', `/${cmd.name} `)
}

function handleCustomClick(cmd: any) {
  emit('select', cmd.template || `/${cmd.name} `)
}

/**
 * 键盘导航拦截（由父组件 Composer 在 keydown 时委托调用）
 */
function handleKeyDown(e: KeyboardEvent): boolean {
  if (!props.show) return false

  if (e.key === 'Escape') {
    emit('close')
    return true
  }

  const items = flatEnabledItems.value
  if (!items.length) return false

  const curIdx = items.findIndex((x) => x.name === activeName.value)

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    const nextIdx = (curIdx + 1) % items.length
    activeName.value = items[nextIdx].name
    return true
  }

  if (e.key === 'ArrowUp') {
    e.preventDefault()
    const prevIdx = (curIdx - 1 + items.length) % items.length
    activeName.value = items[prevIdx].name
    return true
  }

  if (e.key === 'Enter' || e.key === 'Tab') {
    e.preventDefault()
    const hit = items.find((x) => x.name === activeName.value)
    if (hit) {
      if ('template' in hit && hit.template) {
        emit('select', hit.template)
      } else {
        emit('select', `/${hit.name} `)
      }
      return true
    }
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
  bottom: calc(100% + 8px);
  left: 0;
  width: 360px;
  max-height: 380px;
  background: var(--bg-surface, #1e293b);
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.12));
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(12px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 100;
  animation: palette-in 0.16s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes palette-in {
  from {
    opacity: 0;
    transform: translateY(6px);
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
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-bottom: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
}
.slash-palette-title {
  font-size: 11.5px;
  font-weight: 700;
  color: var(--text-secondary, #94a3b8);
  letter-spacing: 0.02em;
}
.slash-palette-kbd {
  font-size: 10.5px;
  color: var(--text-tertiary, #64748b);
}

.slash-palette-body {
  flex: 1;
  overflow-y: auto;
  padding: 6px 0;
  max-height: 330px;
}

.slash-group {
  margin-bottom: 6px;
}
.slash-group:last-child {
  margin-bottom: 0;
}
.slash-group-label {
  font-size: 10.5px;
  font-weight: 600;
  color: var(--text-tertiary, #64748b);
  padding: 4px 12px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.slash-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  cursor: pointer;
  transition: all 0.12s ease;
  user-select: none;
}
.slash-item:hover:not(.disabled) {
  background: rgba(255, 255, 255, 0.06);
}
.slash-item.active:not(.disabled) {
  background: var(--t-agent, rgba(16, 185, 129, 0.14));
}
.slash-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.slash-item-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.slash-item-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--accent-ai, #10b981);
}
.slash-item.disabled .slash-item-name {
  color: var(--text-tertiary, #64748b);
}
.slash-item-hint {
  font-size: 12px;
  color: var(--text-secondary, #cbd5e1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.slash-item-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-tertiary, #64748b);
  white-space: nowrap;
}

.slash-empty-note {
  padding: 6px 12px;
  font-size: 11.5px;
  color: var(--text-tertiary, #64748b);
  font-style: italic;
}
</style>
