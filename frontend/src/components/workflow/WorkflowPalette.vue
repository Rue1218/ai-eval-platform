<template>
  <div class="wf-palette" :class="{ collapsed: isCollapsed }">
    <!-- 物料库顶栏 -->
    <div class="palette-header">
      <div v-if="!isCollapsed" class="palette-title">
        <span class="title-icon">🧩</span>
        <span class="title-text">节点物料库</span>
      </div>
      <button
        class="collapse-btn"
        :title="isCollapsed ? '展开节点库' : '收起节点库'"
        @click="isCollapsed = !isCollapsed"
      >
        <svg v-if="!isCollapsed" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M15 18l-6-6 6-6" />
        </svg>
        <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 18l6-6-6-6" />
        </svg>
      </button>
    </div>

    <!-- 展开内容区 -->
    <div v-show="!isCollapsed" class="palette-body">
      <!-- 搜索框 -->
      <div class="search-box">
        <input
          v-model="searchQuery"
          type="text"
          class="search-input"
          placeholder="搜索组件节点..."
        />
        <span v-if="searchQuery" class="clear-search" @click="searchQuery = ''">×</span>
      </div>

      <!-- 分组节点列表 -->
      <div class="category-list">
        <div
          v-for="group in filteredGroups"
          :key="group.category"
          class="category-group"
        >
          <div class="category-header" @click="toggleGroup(group.category)">
            <span class="cat-icon">{{ group.icon }}</span>
            <span class="cat-name">{{ group.title }}</span>
            <span class="cat-count">({{ group.nodes.length }})</span>
            <span class="cat-arrow" :class="{ open: !groupCollapsed[group.category] }">▾</span>
          </div>

          <div v-show="!groupCollapsed[group.category]" class="node-items">
            <div
              v-for="nodeMeta in group.nodes"
              :key="nodeMeta.type"
              class="palette-node-item"
              draggable="true"
              :style="{ '--node-color': nodeMeta.color }"
              @dragstart="onDragStart($event, nodeMeta.type)"
              @click="$emit('add-node', nodeMeta.type)"
            >
              <div class="item-icon-wrap">
                <span class="item-icon">{{ nodeMeta.icon }}</span>
              </div>
              <div class="item-info">
                <div class="item-name">{{ nodeMeta.name }}</div>
                <div class="item-desc">{{ nodeMeta.description }}</div>
              </div>
              <button class="item-add-btn" title="点击添加至画布">+</button>
            </div>
          </div>
        </div>

        <div v-if="!filteredGroups.length" class="empty-hint">
          未找到匹配组件
        </div>
      </div>
    </div>

    <!-- 折叠状态下的图标快捷条 -->
    <div v-if="isCollapsed" class="collapsed-shortcuts">
      <button
        v-for="type in shortcutTypes"
        :key="type"
        class="shortcut-btn"
        :title="NODE_METAS[type].name"
        @click="$emit('add-node', type)"
      >
        <span>{{ NODE_METAS[type].icon }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NODE_METAS } from './workflowTemplates'
import type { WorkflowNodeType, WorkflowNodeCategory } from './workflowTypes'

defineEmits<{
  (e: 'add-node', type: WorkflowNodeType): void
}>()

const isCollapsed = ref(false)
const searchQuery = ref('')
const groupCollapsed = ref<Record<string, boolean>>({
  trigger: false,
  eval: false,
  data: false,
  gate_stress: false,
  output: false,
})

const groups: Array<{ category: WorkflowNodeCategory; title: string; icon: string; types: WorkflowNodeType[] }> = [
  {
    category: 'trigger',
    title: '触发与调度',
    icon: '🚀',
    types: ['agent_kernel', 'worker_target'],
  },
  {
    category: 'eval',
    title: '评测与质检',
    icon: '📊',
    types: ['benchmark_eval', 'rag_eval', 'llm_judge'],
  },
  {
    category: 'data',
    title: '数据与用例',
    icon: '📚',
    types: ['dataset_source', 'case_gen'],
  },
  {
    category: 'gate_stress',
    title: '门禁与压测',
    icon: '⚡',
    types: ['quality_gate', 'stress_test'],
  },
  {
    category: 'output',
    title: '汇总与输出',
    icon: '📑',
    types: ['eval_report'],
  },
]

const shortcutTypes: WorkflowNodeType[] = [
  'agent_kernel',
  'dataset_source',
  'benchmark_eval',
  'rag_eval',
  'quality_gate',
  'stress_test',
  'eval_report',
]

const filteredGroups = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return groups
    .map((g) => {
      const nodes = g.types
        .map((t) => NODE_METAS[t])
        .filter((meta) => {
          if (!query) return true
          return (
            meta.name.toLowerCase().includes(query) ||
            meta.description.toLowerCase().includes(query) ||
            meta.type.toLowerCase().includes(query)
          )
        })
      return {
        ...g,
        nodes,
      }
    })
    .filter((g) => g.nodes.length > 0)
})

function toggleGroup(category: string) {
  groupCollapsed.value[category] = !groupCollapsed.value[category]
}

function onDragStart(event: DragEvent, type: WorkflowNodeType) {
  if (event.dataTransfer) {
    event.dataTransfer.setData('application/workflow-node-type', type)
    event.dataTransfer.effectAllowed = 'copy'
  }
}
</script>

<style scoped>
.wf-palette {
  width: 250px;
  background: var(--bg-main);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  transition: width 0.22s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 10;
  overflow: hidden;
  user-select: none;
}

.wf-palette.collapsed {
  width: 52px;
}

.palette-header {
  height: 48px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-subtle);
}

.palette-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
}

.collapse-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--text-tertiary);
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s, background 0.15s;
}

.collapse-btn:hover {
  color: var(--text-primary);
  background: var(--row-hover);
}

.palette-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.search-box {
  position: relative;
  width: 100%;
}

.search-input {
  width: 100%;
  padding: 6px 24px 6px 10px;
  font-size: 12px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.15s;
}

.search-input:focus {
  border-color: var(--accent-ai);
}

.clear-search {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 14px;
}

.category-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 4px;
}

.category-header:hover {
  background: var(--row-hover);
}

.cat-icon {
  font-size: 13px;
}

.cat-count {
  font-size: 11px;
  color: var(--text-tertiary);
}

.cat-arrow {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-tertiary);
  transition: transform 0.15s;
}

.cat-arrow.open {
  transform: rotate(0deg);
}

.node-items {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-left: 2px;
}

.palette-node-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  cursor: grab;
  position: relative;
  transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}

.palette-node-item:hover {
  border-color: var(--node-color);
  background: var(--bg-main);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

.palette-node-item:active {
  cursor: grabbing;
}

.item-icon-wrap {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 14px;
}

.item-info {
  flex: 1;
  min-width: 0;
}

.item-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 1px;
}

.item-add-btn {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.15s, background 0.15s, color 0.15s;
}

.palette-node-item:hover .item-add-btn {
  opacity: 1;
}

.item-add-btn:hover {
  background: var(--accent-ai);
  color: #fff;
  border-color: var(--accent-ai);
}

.empty-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  text-align: center;
  padding: 20px 0;
}

.collapsed-shortcuts {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 10px 4px;
}

.shortcut-btn {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.15s;
}

.shortcut-btn:hover {
  background: var(--bg-main);
  border-color: var(--accent-ai);
  transform: scale(1.08);
}
</style>
