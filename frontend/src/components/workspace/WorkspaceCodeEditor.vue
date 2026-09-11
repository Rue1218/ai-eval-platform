<template>
  <div class="workspace-code-editor">
    <div class="editor-main">
      <!-- 行号栏 -->
      <div ref="lineNumbersRef" class="line-numbers" aria-hidden="true">
        <div v-for="line in totalLines" :key="line" class="line-number">{{ line }}</div>
      </div>

      <!-- 编辑主体 Textarea -->
      <textarea
        ref="textareaRef"
        v-model="internalValue"
        class="editor-textarea"
        :placeholder="placeholder || '输入或编辑代码...'"
        :readonly="readonly"
        spellcheck="false"
        autocomplete="off"
        autocorrect="off"
        autocapitalize="off"
        @scroll="handleScroll"
        @keydown="handleKeyDown"
        @keyup="updateCursorPos"
        @click="updateCursorPos"
      />
    </div>

    <!-- 底部状态条 -->
    <div class="editor-statusbar">
      <div class="status-left">
        <span>行: {{ cursorLine }}, 列: {{ cursorCol }}</span>
        <span class="status-sep">|</span>
        <span>总行数: {{ totalLines }}</span>
        <span class="status-sep">|</span>
        <span>字符数: {{ internalValue.length }}</span>
      </div>
      <div class="status-right">
        <span class="status-tag">UTF-8</span>
        <span class="status-tag">LF</span>
        <span v-if="language" class="status-lang">{{ language }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = defineProps<{
  modelValue: string
  placeholder?: string
  readonly?: boolean
  language?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'save'): void
}>()

const internalValue = computed({
  get: () => props.modelValue,
  set: (val: string) => emit('update:modelValue', val),
})

const textareaRef = ref<HTMLTextAreaElement | null>(null)
const lineNumbersRef = ref<HTMLDivElement | null>(null)

const cursorLine = ref(1)
const cursorCol = ref(1)

const totalLines = computed(() => {
  const count = (internalValue.value || '').split('\n').length
  return Math.max(1, count)
})

function handleScroll(): void {
  if (textareaRef.value && lineNumbersRef.value) {
    lineNumbersRef.value.scrollTop = textareaRef.value.scrollTop
  }
}

function updateCursorPos(): void {
  const el = textareaRef.value
  if (!el) return
  const text = el.value.substring(0, el.selectionStart)
  const lines = text.split('\n')
  cursorLine.value = lines.length
  cursorCol.value = (lines[lines.length - 1]?.length ?? 0) + 1
}

function handleKeyDown(e: KeyboardEvent): void {
  // 拦截 Ctrl+S / Cmd+S 触发保存
  if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
    e.preventDefault()
    emit('save')
    return
  }

  // 拦截 Tab 键插入 4 个空格
  if (e.key === 'Tab' && !props.readonly) {
    e.preventDefault()
    const el = textareaRef.value
    if (!el) return
    const start = el.selectionStart
    const end = el.selectionEnd
    const val = internalValue.value
    const indent = '    '
    internalValue.value = val.substring(0, start) + indent + val.substring(end)
    setTimeout(() => {
      if (el) {
        el.selectionStart = el.selectionEnd = start + indent.length
        updateCursorPos()
      }
    }, 0)
  }
}

watch(
  () => props.modelValue,
  () => {
    updateCursorPos()
  },
)
</script>

<style scoped>
.workspace-code-editor {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background: var(--bg-main, #ffffff);
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border-subtle, #e5e7eb);
}

.editor-main {
  flex: 1;
  display: flex;
  position: relative;
  overflow: hidden;
  background: var(--bg-main, #ffffff);
}

.line-numbers {
  width: 48px;
  padding: 12px 6px 12px 0;
  text-align: right;
  font-family: var(--font-mono, 'Fira Code', Consolas, Monaco, monospace);
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-tertiary, #9ca3af);
  background: var(--bg-elevated, #f4f8f8);
  border-right: 1px solid var(--border-subtle, #e5e7eb);
  user-select: none;
  overflow-y: hidden;
  box-sizing: border-box;
}

.line-number {
  height: 20.8px;
  padding-right: 8px;
}

.editor-textarea {
  flex: 1;
  padding: 12px 14px;
  margin: 0;
  border: none;
  outline: none;
  resize: none;
  background: var(--bg-main, #ffffff);
  color: var(--text-primary, #111827);
  font-family: var(--font-mono, 'Fira Code', Consolas, Monaco, monospace);
  font-size: 13px;
  line-height: 1.6;
  tab-size: 4;
  white-space: pre;
  word-wrap: normal;
  overflow: auto;
  box-sizing: border-box;
}

.editor-textarea::placeholder {
  color: var(--text-tertiary, #9ca3af);
}

.editor-statusbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 14px;
  background: var(--bg-elevated, #f4f8f8);
  border-top: 1px solid var(--border-subtle, #e5e7eb);
  font-size: 12px;
  color: var(--text-secondary, #4b5563);
  font-family: var(--font-mono, monospace);
  user-select: none;
}

.status-left,
.status-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-sep {
  opacity: 0.35;
}

.status-tag {
  padding: 1px 6px;
  background: var(--bg-main, #ffffff);
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 4px;
  font-size: 11px;
  color: var(--text-secondary, #4b5563);
}

.status-lang {
  padding: 1px 8px;
  border-radius: 4px;
  background: #e6f1ec;
  color: #1f5947;
  font-weight: 500;
  font-size: 11px;
}

[data-theme='dark'] .status-lang {
  background: rgba(22, 151, 122, 0.18);
  color: #34d399;
}
</style>
