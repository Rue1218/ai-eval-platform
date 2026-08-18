<template>
  <n-modal
    :show="show"
    preset="card"
    :title="`上传文档到知识库「${kb?.name}」`"
    style="width: 480px"
    @update:show="$emit('update:show', $event)"
  >
    <div class="upload-form">
      <div style="font-size: 12px; color: var(--text-tertiary); margin-bottom: 8px">
        支持 PDF, Markdown, TXT, HTML 等文档，上传后 LightRAG 将自动切块并提取实体与图谱关系进行索引。
      </div>

      <n-upload
        ref="uploadRef"
        :default-upload="false"
        :max="1"
        accept=".pdf,.md,.txt,.html,.json,.yaml,.yml"
        @change="handleFileChange"
      >
        <n-upload-dragger>
          <div style="margin-bottom: 8px; color: var(--c-kb)">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin: 0 auto">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="12" y1="18" x2="12" y2="12"></line>
              <line x1="9" y1="15" x2="15" y2="15"></line>
            </svg>
          </div>
          <div style="font-size: 13px; font-weight: 500">点击或将知识库文档拖拽至此处</div>
        </n-upload-dragger>
      </n-upload>
    </div>

    <template #footer>
      <div style="display: flex; gap: 8px; justify-content: flex-end">
        <n-button @click="$emit('update:show', false)">取消</n-button>
        <n-button type="primary" :loading="uploading" @click="handleUpload">开始上传并索引</n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useMessage, type UploadFileInfo } from 'naive-ui'
import { api } from '../../api/http'
import type { KnowledgeBase } from '../../api/types'

const props = defineProps<{
  show: boolean
  kb?: KnowledgeBase | null
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
  (e: 'success'): void
}>()

const message = useMessage()
const uploading = ref(false)
const selectedFile = ref<File | null>(null)

watch(
  () => props.show,
  (val) => {
    if (val) selectedFile.value = null
  },
)

function handleFileChange(options: { fileList: UploadFileInfo[] }) {
  if (options.fileList.length > 0 && options.fileList[0].file) {
    selectedFile.value = options.fileList[0].file
  } else {
    selectedFile.value = null
  }
}

async function handleUpload() {
  if (!props.kb?.id) return
  if (!selectedFile.value) {
    message.warning('请选择要上传的文档')
    return
  }

  uploading.value = true
  try {
    await api.kb.uploadDoc(props.kb.id, selectedFile.value)
    message.success('文档已上传并开始建索引')
    emit('update:show', false)
    emit('success')
  } catch (err: any) {
    message.error(err.message || '上传文档失败')
  } finally {
    uploading.value = false
  }
}
</script>
