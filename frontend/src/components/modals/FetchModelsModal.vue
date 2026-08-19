<template>
  <n-modal
    :show="show"
    preset="card"
    title="从端点获取的模型列表 (/models)"
    style="width: 640px; max-width: 95vw"
    @update:show="$emit('update:show', $event)"
  >
    <div class="fetch-models-content">
      <!-- 顶部搜索与统计 -->
      <div class="search-bar">
        <n-input
          v-model:value="searchKeyword"
          placeholder="搜索模型名称或标识 (如 mimo / gpt / claude)..."
          clearable
          size="small"
        >
          <template #prefix>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
          </template>
        </n-input>
      </div>

      <!-- 模型列表区 -->
      <div class="models-list-wrap">
        <div v-if="filteredModels.length === 0" class="empty-tip">
          没有找到匹配的模型标识
        </div>
        <div
          v-for="m in filteredModels"
          :key="m.id"
          class="model-item-row"
          :class="{ selected: selectedModelIds.includes(m.id) }"
          @click="toggleSelect(m.id)"
        >
          <div class="model-meta">
            <div class="model-id-text mono">{{ m.id }}</div>
            <div class="model-sub-text">
              <span v-if="m.owned_by" class="tag-owned">{{ m.owned_by }}</span>
            </div>
          </div>
          <div class="model-actions" @click.stop>
            <button
              class="btn btn-secondary btn-xs"
              @click="handleSinglePick(m.id)"
            >
              选用此模型
            </button>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="modal-footer-row">
        <span class="small tertiary">
          共发现 {{ models.length }} 个模型，当前筛选 {{ filteredModels.length }} 个
        </span>
        <div style="display: flex; gap: 8px">
          <n-button size="small" @click="$emit('update:show', false)">关闭</n-button>
          <n-button
            v-if="selectedModelIds.length > 1"
            type="primary"
            size="small"
            @click="handleBatchAdd"
          >
            批量创建选中的 {{ selectedModelIds.length }} 个协议档
          </n-button>
        </div>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  show: boolean
  models: Array<{ id: string; name: string; owned_by?: string }>
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
  (e: 'select', modelId: string): void
  (e: 'batch-create', modelIds: string[]): void
}>()

const searchKeyword = ref('')
const selectedModelIds = ref<string[]>([])

const filteredModels = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return props.models
  return props.models.filter(
    (m) =>
      m.id.toLowerCase().includes(kw) ||
      (m.owned_by && m.owned_by.toLowerCase().includes(kw))
  )
})

function toggleSelect(id: string) {
  const idx = selectedModelIds.value.indexOf(id)
  if (idx >= 0) {
    selectedModelIds.value.splice(idx, 1)
  } else {
    selectedModelIds.value.push(id)
  }
}

function handleSinglePick(modelId: string) {
  emit('select', modelId)
  emit('update:show', false)
}

function handleBatchAdd() {
  if (selectedModelIds.value.length === 0) return
  emit('batch-create', [...selectedModelIds.value])
  emit('update:show', false)
}
</script>

<style scoped>
.fetch-models-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.search-bar {
  margin-bottom: 4px;
}
.models-list-wrap {
  max-height: 380px;
  overflow-y: auto;
  border: 1px solid var(--border-subtle, rgba(229, 231, 235, 1));
  border-radius: 8px;
  background: var(--bg-surface, #fafafa);
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.model-item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--bg-card, #ffffff);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s ease;
}
.model-item-row:hover {
  background: rgba(14, 165, 233, 0.05);
  border-color: rgba(14, 165, 233, 0.3);
}
.model-item-row.selected {
  background: rgba(14, 165, 233, 0.1);
  border-color: var(--accent-info, #0284c7);
}
.model-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.model-id-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #111827);
}
.model-sub-text {
  display: flex;
  gap: 6px;
  font-size: 11px;
}
.tag-owned {
  background: rgba(100, 116, 139, 0.12);
  color: var(--text-secondary, #475569);
  padding: 1px 6px;
  border-radius: 4px;
}
.empty-tip {
  padding: 32px;
  text-align: center;
  color: var(--text-tertiary, #94a3b8);
  font-size: 13px;
}
.modal-footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.btn-xs {
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 4px;
}
</style>
