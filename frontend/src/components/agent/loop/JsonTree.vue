<template>
  <div class="json-tree" :role="root ? 'tree' : undefined" :aria-label="root ? label : undefined">
    <template v-if="isContainer">
      <div class="json-node" role="treeitem" :aria-expanded="root ? undefined : expanded">
        <div class="json-row">
          <button v-if="!root" class="json-toggle" type="button" :aria-label="`${expanded ? '收起' : '展开'} ${label}`" @click="expanded = !expanded">
            <span aria-hidden="true">{{ expanded ? '▼' : '▶' }}</span>
          </button>
          <span v-else class="json-root-indent" aria-hidden="true"/>
          <span v-if="label && !root" class="json-key">{{ JSON.stringify(label) }}</span><span v-if="label && !root" class="json-punctuation">: </span>
          <span class="json-punctuation">{{ openToken }}</span><span v-if="!expanded" class="json-collapsed">… {{ entries.length }} 项 {{ closeToken }}{{ trailing ? ',' : '' }}</span>
        </div>
        <div v-if="expanded" class="json-children" role="group">
          <JsonTree v-for="([key, item], index) in entries" :key="key" :value="item" :label="key" :depth="depth + 1" :trailing="index < entries.length - 1" :root="false"/>
        </div>
        <div v-if="expanded" class="json-closing"><span class="json-punctuation">{{ closeToken }}{{ trailing ? ',' : '' }}</span></div>
      </div>
    </template>
    <div v-else class="json-row json-leaf" role="treeitem">
      <span class="json-root-indent" aria-hidden="true"/>
      <span v-if="label && !root" class="json-key">{{ JSON.stringify(label) }}</span><span v-if="label && !root" class="json-punctuation">: </span>
      <span class="json-value" :class="valueKind">{{ displayValue }}</span><span class="json-punctuation">{{ trailing ? ',' : '' }}</span>
    </div>
    <button v-if="root" class="json-copy" type="button" @click="copy">{{ copyLabel }}</button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { copyText } from '../../../utils/clipboard'

/** 将已授权的 JSON 按原始层级展示；折叠只影响前端视图，不修改网络快照。 */
const props = withDefaults(defineProps<{
  value: unknown
  label?: string
  depth?: number
  trailing?: boolean
  root?: boolean
}>(), { label: 'JSON', depth: 0, trailing: false, root: true })

const expanded = ref(props.depth < 2)
const copyLabel = ref('复制 JSON')
const isContainer = computed(() => props.value !== null && typeof props.value === 'object')
const isArray = computed(() => Array.isArray(props.value))
const openToken = computed(() => isArray.value ? '[' : '{')
const closeToken = computed(() => isArray.value ? ']' : '}')
/** 数组保留数值索引，对象保持后端字段原名，不重排也不补默认值。 */
const entries = computed<[string, unknown][]>(() => {
  if (!isContainer.value) return []
  return Array.isArray(props.value)
    ? props.value.map((item, index) => [String(index), item])
    : Object.entries(props.value as Record<string, unknown>)
})
const displayValue = computed(() => JSON.stringify(props.value) ?? 'null')
const valueKind = computed(() => {
  if (props.value === null) return 'is-null'
  if (typeof props.value === 'string') return 'is-string'
  if (typeof props.value === 'number') return 'is-number'
  if (typeof props.value === 'boolean') return 'is-boolean'
  return 'is-unknown'
})

/** 复制格式化后的同一份 JSON，避免用户从折叠态获得不完整文本。 */
async function copy() {
  const text = JSON.stringify(props.value, null, 2)
  copyLabel.value = await copyText(text) ? '已复制' : '复制失败'
  window.setTimeout(() => { copyLabel.value = '复制 JSON' }, 1600)
}
</script>

<style scoped>
.json-tree { position: relative; color: #42536a; font: 14px/1.72 var(--font-mono); }
.json-row { display: flex; min-width: max-content; align-items: baseline; padding: 1px 0; white-space: pre; }
.json-root-indent { display: inline-block; width: 18px; flex: 0 0 18px; }
.json-toggle { display: inline-flex; width: 20px; height: 22px; flex: 0 0 20px; align-items: center; justify-content: center; border: 0; border-radius: 4px; background: transparent; padding: 0; color: #6d7b90; font-size: 11px; cursor: pointer; }
.json-toggle:hover, .json-toggle:focus-visible { background: #e8edfb; color: #4e58b8; outline: 0; }
.json-children { margin-left: 9px; border-left: 1px solid #dce4ee; padding-left: 6px; }
.json-closing { min-width: max-content; padding-left: 20px; }
.json-key { color: #7756ad; } .json-punctuation { color: #65758b; } .json-value.is-string { color: #a24d4a; } .json-value.is-number { color: #1d7c61; } .json-value.is-boolean { color: #2d69a5; } .json-value.is-null { color: #8a629b; }
.json-collapsed { color: #7d8999; }
.json-copy { position: absolute; top: 0; right: 0; border: 0; border-radius: 5px; background: #f4f6fb; padding: 3px 7px; color: #5564a6; font: 12px/1.45 inherit; cursor: pointer; }
.json-copy:hover { background: #e9edff; }
</style>
