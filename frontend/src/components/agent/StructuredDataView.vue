<template>
  <div class="structured-data" :class="{ 'is-nested': depth > 0, compact }">
    <div v-if="showToolbar && depth === 0" class="structured-head">
      <span class="structured-title">{{ label || '结构化输出' }}</span>
      <button type="button" class="structured-copy" @click="copyValue">
        {{ copied ? '已复制' : '复制 JSON' }}
      </button>
    </div>

    <p v-if="isEmptyContainer" class="structured-empty">{{ emptyContainerLabel }}</p>

    <div v-else-if="tableModel" class="structured-table-wrap">
      <table class="structured-table">
        <thead>
          <tr>
            <th v-for="key in tableModel.keys" :key="key">{{ key }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, rowIndex) in tableModel.rows" :key="rowIndex">
            <td v-for="key in tableModel.keys" :key="key">
              <template v-if="isScalar(row[key])">{{ formatScalar(row[key]) }}</template>
              <StructuredDataView
                v-else
                :value="row[key]"
                :depth="depth + 1"
                :max-depth="maxDepth"
                compact
              />
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="hiddenItemCount" class="structured-omitted">其余 {{ hiddenItemCount }} 项未展开</p>
    </div>

    <dl v-else-if="recordValue" class="structured-fields">
      <div v-for="([key, child], index) in visibleEntries" :key="`${key}-${index}`" class="structured-field">
        <dt>{{ key }}</dt>
        <dd>
          <template v-if="isScalar(child)">{{ formatScalar(child) }}</template>
          <span v-else-if="depth >= maxDepth" class="structured-depth">已折叠的对象</span>
          <StructuredDataView
            v-else
            :value="child"
            :depth="depth + 1"
            :max-depth="maxDepth"
            compact
          />
        </dd>
      </div>
      <p v-if="hiddenItemCount" class="structured-omitted">其余 {{ hiddenItemCount }} 项未展开</p>
    </dl>

    <ol v-else-if="arrayValue" class="structured-list">
      <li v-for="(child, index) in visibleItems" :key="index">
        <template v-if="isScalar(child)">{{ formatScalar(child) }}</template>
        <span v-else-if="depth >= maxDepth" class="structured-depth">已折叠的对象</span>
        <StructuredDataView
          v-else
          :value="child"
          :depth="depth + 1"
          :max-depth="maxDepth"
          compact
        />
      </li>
      <li v-if="hiddenItemCount" class="structured-omitted">其余 {{ hiddenItemCount }} 项未展开</li>
    </ol>

    <span v-else class="structured-scalar">{{ formatScalar(value) }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

defineOptions({ name: 'StructuredDataView' })

const props = withDefaults(
  defineProps<{
    /** 后端安全投影或模型最终 JSON；组件不解释业务字段，只保留对象结构。 */
    value: unknown
    label?: string
    depth?: number
    maxDepth?: number
    compact?: boolean
    showToolbar?: boolean
  }>(),
  {
    label: '',
    depth: 0,
    maxDepth: 4,
    compact: false,
    showToolbar: false,
  },
)

const MAX_VISIBLE_ITEMS = 50
const copied = ref(false)

/** 仅把普通对象识别为字段集合，避免 Date 等特殊对象被错误展开。 */
function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function isScalar(value: unknown): boolean {
  return value === null || ['string', 'number', 'boolean', 'undefined'].includes(typeof value)
}

function formatScalar(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}

const recordValue = computed(() => asRecord(props.value))
const arrayValue = computed(() => Array.isArray(props.value) ? props.value : null)
const visibleEntries = computed(() => Object.entries(recordValue.value || {}).slice(0, MAX_VISIBLE_ITEMS))
const visibleItems = computed(() => (arrayValue.value || []).slice(0, MAX_VISIBLE_ITEMS))
const itemCount = computed(() => recordValue.value ? Object.keys(recordValue.value).length : (arrayValue.value?.length || 0))
const hiddenItemCount = computed(() => Math.max(0, itemCount.value - MAX_VISIBLE_ITEMS))

/** 空对象或空数组也要明确呈现，避免工具成功卡片看起来像渲染失败。 */
const isEmptyContainer = computed(() => (
  (recordValue.value !== null && Object.keys(recordValue.value).length === 0)
  || (arrayValue.value !== null && arrayValue.value.length === 0)
))
const emptyContainerLabel = computed(() => arrayValue.value !== null ? '空数组' : '空对象')

/** 把形状一致的对象数组展示为表格，其余数据继续以字段树呈现。 */
const tableModel = computed(() => {
  const rows = arrayValue.value
  if (!rows?.length || rows.length > MAX_VISIBLE_ITEMS || !rows.every((row) => asRecord(row))) return null
  const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(asRecord(row) || {}))))
  if (!keys.length || keys.length > 8) return null
  return {
    keys,
    rows: rows.map((row) => asRecord(row) || {}),
  }
})

/** 复制的是安全投影的 JSON，而非任何模型 Observation 或浏览器私有状态。 */
async function copyValue(): Promise<void> {
  const text = typeof props.value === 'string'
    ? props.value
    : JSON.stringify(props.value, null, 2)
  if (!text || !navigator.clipboard) return
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 1600)
  } catch {
    copied.value = false
  }
}
</script>

<style scoped>
.structured-data {
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.52);
  color: var(--text-primary, #e2e8f0);
  font-size: 13px;
  line-height: 1.55;
}

.structured-data.is-nested {
  margin: 6px 0;
  border-radius: 7px;
  background: rgba(15, 23, 42, 0.34);
}

.structured-data.compact {
  font-size: 12px;
}

.structured-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.5);
}

.structured-title {
  color: var(--text-secondary, #94a3b8);
  font-size: 12px;
  font-weight: 650;
}

.structured-copy {
  border: 0;
  padding: 2px 0;
  background: transparent;
  color: var(--accent-ai, #34d399);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.structured-fields {
  display: grid;
  margin: 0;
}

.structured-empty {
  margin: 0;
  padding: 10px;
  color: var(--text-tertiary, #64748b);
  font-size: 12px;
}

.structured-field {
  display: grid;
  grid-template-columns: minmax(108px, 28%) minmax(0, 1fr);
  gap: 12px;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
}

.structured-field:last-of-type { border-bottom: 0; }
.structured-field dt { color: var(--text-secondary, #94a3b8); overflow-wrap: anywhere; }
.structured-field dd { min-width: 0; margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.structured-data.compact .structured-field { padding: 6px 8px; }

.structured-list {
  display: grid;
  gap: 7px;
  margin: 0;
  padding: 10px 10px 10px 30px;
}

.structured-list > li { padding-left: 2px; }

.structured-table-wrap { overflow-x: auto; }
.structured-table { width: 100%; border-collapse: collapse; text-align: left; }
.structured-table th,
.structured-table td { padding: 8px 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.1); vertical-align: top; overflow-wrap: anywhere; }
.structured-table th { position: sticky; top: 0; background: rgba(15, 23, 42, 0.76); color: var(--text-secondary, #94a3b8); font-size: 12px; font-weight: 650; white-space: nowrap; }
.structured-table tr:last-child td { border-bottom: 0; }

.structured-depth,
.structured-omitted { color: var(--text-tertiary, #64748b); font-size: 12px; }
.structured-omitted { margin: 0; padding: 8px 10px; }
.structured-scalar { display: block; padding: 8px 10px; overflow-wrap: anywhere; white-space: pre-wrap; }

@media (max-width: 640px) {
  .structured-field { grid-template-columns: 1fr; gap: 3px; }
}
</style>
