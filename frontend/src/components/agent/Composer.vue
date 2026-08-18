<template>
  <div class="composer-wrap">
    <!-- 快捷提示芯片 -->
    <div v-if="showChips && !text.trim()" class="quick-chips">
      <button
        v-for="chip in chips"
        :key="chip.label"
        class="chip"
        @click="selectChip(chip.prompt)"
      >
        {{ chip.label }}
      </button>
    </div>

    <!-- 附件预览芯片 -->
    <div v-if="attachment" class="attach-preview">
      <div class="attach-chip">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
        </svg>
        <span>{{ attachment.filename }}</span>
        <span class="mono">{{ formatSize(attachment.size) }}</span>
        <button class="remove-attach" @click="removeAttachment" title="移除附件">×</button>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="composer-inner">
      <!-- 附件上传隐藏 input -->
      <input
        ref="fileInputRef"
        type="file"
        style="display: none"
        accept=".txt,.md,.pdf,.json,.jsonl,.csv,.xlsx"
        @change="handleFileChange"
      />

      <!-- 附件按钮 -->
      <button
        class="composer-btn"
        :disabled="uploading"
        @click="triggerUpload"
        title="上传附件（≤20MB）"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
        </svg>
      </button>

      <!-- 文本输入框 -->
      <textarea
        v-model="text"
        placeholder="说明要评测什么（模型 / RAG / 生成用例），我会先澄清后给出确认卡..."
        :rows="1"
        @keydown.enter.prevent="handleEnter"
      ></textarea>

      <!-- 右侧只读模型名 -->
      <div class="composer-model mono">{{ agentModelName }}</div>

      <!-- 发送按钮 -->
      <button
        class="send-btn"
        :class="{ ready: canSend }"
        :disabled="!canSend"
        @click="handleSend"
        title="发送消息"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../../api/http'

const props = withDefaults(
  defineProps<{
    connected?: boolean
    agentModelName?: string
    showChips?: boolean
  }>(),
  {
    connected: true,
    agentModelName: 'Agent · 主模型',
    showChips: true,
  },
)

const emit = defineEmits<{
  (e: 'send', text: string, fileId?: string): void
}>()

const message = useMessage()
const text = ref('')
const fileInputRef = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const attachment = ref<{ id: string; filename: string; size: number } | null>(null)

const chips = [
  { label: '基准评测', prompt: '帮我针对最新的两个大模型进行一单 Benchmark 基准评测' },
  { label: 'RAG 评测', prompt: '帮我对知识库 default 进行一次 RAG 混合检索能力评测' },
  { label: '生成用例', prompt: '根据需求描述生成一批结构化测试用例并进行正反向自检' },
  { label: '先评后压', prompt: '帮我对比模型质量，并在评测成功后自动派生压测' },
]

const canSend = computed(() => {
  return props.connected && (text.value.trim().length > 0 || !!attachment.value)
})

function selectChip(prompt: string) {
  text.value = prompt
}

function triggerUpload() {
  fileInputRef.value?.click()
}

async function handleFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  if (file.size > 20 * 1024 * 1024) {
    message.error('单文件大小不能超过 20MB')
    target.value = ''
    return
  }

  uploading.value = true
  try {
    const res = await api.files.upload(file)
    attachment.value = res
    message.success(`附件 ${file.name} 已上传`)
  } catch (err: any) {
    message.error(err.message || '上传附件失败')
  } finally {
    uploading.value = false
    target.value = ''
  }
}

function removeAttachment() {
  attachment.value = null
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function handleEnter(e: KeyboardEvent) {
  if (!e.shiftKey) {
    handleSend()
  }
}

function handleSend() {
  if (!canSend.value) return
  const msg = text.value.trim()
  const fileId = attachment.value?.id
  emit('send', msg, fileId)
  text.value = ''
  attachment.value = null
}
</script>

<style scoped>
.composer-wrap {
  padding: 10px 24px 18px;
  background: var(--bg-main);
}

.quick-chips {
  max-width: 760px;
  margin: 0 auto 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.chip {
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  font-size: 12px;
  color: var(--text-secondary);
  transition: all 0.14s ease;
}
.chip:hover {
  border-color: var(--accent-ai);
  color: var(--accent-ai);
}

.attach-preview {
  max-width: 760px;
  margin: 0 auto 8px;
}
.attach-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--text-secondary);
}
.remove-attach {
  background: none;
  border: 0;
  color: var(--text-tertiary);
  font-size: 14px;
  cursor: pointer;
  padding: 0 2px;
}
.remove-attach:hover {
  color: var(--accent-error);
}

.composer-inner {
  max-width: 760px;
  margin: 0 auto;
  border: 1px solid var(--border-subtle);
  border-radius: 20px;
  background: var(--bg-main);
  padding: 8px 12px;
  display: flex;
  align-items: flex-end;
  gap: 10px;
  transition: all 0.15s ease;
}
.composer-inner:focus-within {
  border-color: var(--accent-ai);
  box-shadow: var(--focus-ring);
}

.composer-inner textarea {
  flex: 1;
  border: 0;
  outline: none;
  resize: none;
  font-family: var(--font-chat);
  font-size: 14px;
  line-height: 1.5;
  min-height: 36px;
  max-height: 140px;
  padding: 6px 4px;
  background: transparent;
  color: var(--text-primary);
}

.composer-btn {
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: 50%;
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
  color: var(--text-secondary);
  display: grid;
  place-items: center;
  transition: all 0.15s ease;
}
.composer-btn:hover:not(:disabled) {
  border-color: var(--text-tertiary);
  color: var(--text-primary);
}

.composer-model {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
  padding-bottom: 8px;
}

.send-btn {
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  border-radius: 50%;
  border: 0;
  display: grid;
  place-items: center;
  background: var(--bg-elevated);
  color: var(--text-tertiary);
  transition: all 0.15s ease;
}
.send-btn.ready {
  background: var(--text-primary);
  color: var(--bg-main);
}
.send-btn.ready:hover {
  opacity: 0.85;
}
</style>
