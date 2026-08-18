<template>
  <n-modal
    :show="show"
    preset="card"
    :title="`上传黄金 QA 问答集至「${kb?.name}」`"
    style="width: 500px"
    @update:show="$emit('update:show', $event)"
  >
    <div class="upload-form">
      <div class="field">
        <label class="field-label">问答集名称 <span class="req">*</span></label>
        <n-input v-model:value="name" placeholder="例如：qa-v1 或 客服标准问答" />
      </div>

      <div class="field">
        <label class="field-label">QA 数据文件 (JSONL / CSV) <span class="req">*</span></label>
        <div style="font-size: 12px; color: var(--text-tertiary); margin-bottom: 6px">
          必须包含 <code>question, reference</code> 列，可选包含 <code>expected_doc_ids</code>（期望召回的文档 ID 列表）。≤10,000 条。
        </div>
        <n-upload
          ref="uploadRef"
          :default-upload="false"
          :max="1"
          accept=".jsonl,.csv,.json"
          @change="handleFileChange"
        >
          <n-upload-dragger>
            <div style="margin-bottom: 8px; color: var(--c-kb)">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin: 0 auto">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
            </div>
            <div style="font-size: 13px; font-weight: 500">点击或将黄金 QA 文件拖拽至此处</div>
          </n-upload-dragger>
        </n-upload>
      </div>

      <div class="info-strip" style="font-size: 12px">
        提示：样本中未填写 expected_doc_ids 的行将不参与 Hit Rate@K 命中率分母计算，仅参与答案质量评测。
      </div>
    </div>

    <template #footer>
      <div style="display: flex; gap: 8px; justify-content: flex-end">
        <n-button @click="$emit('update:show', false)">取消</n-button>
        <n-button type="primary" :loading="uploading" @click="handleUpload">确认上传</n-button>
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
const name = ref('')
const selectedFile = ref<File | null>(null)

watch(
  () => props.show,
  (val) => {
    if (val) {
      name.value = ''
      selectedFile.value = null
    }
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
  if (!name.value.trim()) {
    message.warning('请输入黄金 QA 数据集名称')
    return
  }
  if (!selectedFile.value) {
    message.warning('请选择要上传的数据文件')
    return
  }

  uploading.value = true
  try {
    await api.kb.uploadGoldQA(props.kb.id, selectedFile.value, name.value)
    message.success('黄金问答集上传成功')
    emit('update:show', false)
    emit('success')
  } catch (err: any) {
    message.error(err.message || '上传失败')
  } finally {
    uploading.value = false
  }
}
</script>

<style scoped>
.upload-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}
.field-label .req {
  color: var(--accent-error);
}
</style>
