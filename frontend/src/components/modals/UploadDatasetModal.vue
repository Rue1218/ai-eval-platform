<template>
  <n-modal
    :show="show"
    preset="card"
    :title="isOverride ? `覆盖上传「${dataset?.name}」` : '上传新评测数据集'"
    style="width: 520px"
    @update:show="$emit('update:show', $event)"
  >
    <div class="upload-form">
      <div v-if="!isOverride" class="field">
        <label class="field-label">数据集名称 <span class="req">*</span></label>
        <n-input v-model:value="name" placeholder="例如：smoke-20 或 支付问答集" />
      </div>

      <div v-if="!isOverride" class="field">
        <label class="field-label">主评分指标</label>
        <n-select
          v-model:value="metric"
          :options="[
            { label: 'Contain (文本包含，默认)', value: 'contain' },
            { label: 'Exact Match (严格全等)', value: 'exact' },
            { label: 'Regex (正则表达式)', value: 'regex' },
            { label: 'ROUGE-L (最长公共子序列)', value: 'rouge_l' },
            { label: 'BLEU (自然语言相似度)', value: 'bleu' },
          ]"
        />
      </div>

      <div class="field">
        <label class="field-label">数据文件 (JSONL / CSV) <span class="req">*</span></label>
        <div style="font-size: 12px; color: var(--text-tertiary); margin-bottom: 6px">
          支持 JSONL 与 CSV 格式，单文件 ≤50MB，≤20,000 行。列格式需包含 <code>question, reference, context?</code>
        </div>
        <n-upload
          ref="uploadRef"
          :default-upload="false"
          :max="1"
          accept=".jsonl,.csv,.json"
          @change="handleFileChange"
        >
          <n-upload-dragger>
            <div style="margin-bottom: 8px; color: var(--accent-ai)">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin: 0 auto">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
            </div>
            <div style="font-size: 13px; font-weight: 500">点击或将数据集文件拖拽至此处</div>
          </n-upload-dragger>
        </n-upload>
      </div>

      <div v-if="isOverride" class="warn-strip" style="margin-top: 6px">
        覆盖上传后，数据集版本号将自动 +1 (当前版本 v{{ dataset?.version }})，历史评测快照不受影响。
      </div>
    </div>

    <template #footer>
      <div style="display: flex; gap: 8px; justify-content: flex-end">
        <n-button @click="$emit('update:show', false)">取消</n-button>
        <n-button type="primary" :loading="uploading" @click="handleUpload">
          {{ isOverride ? '确认覆盖上传' : '上传并创建' }}
        </n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useMessage, type UploadFileInfo } from 'naive-ui'
import { api } from '../../api/http'
import type { Dataset, DatasetMetric } from '../../api/types'

const props = defineProps<{
  show: boolean
  dataset?: Dataset | null
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
  (e: 'success'): void
}>()

const message = useMessage()
const uploading = ref(false)
const name = ref('')
const metric = ref<DatasetMetric>('contain')
const selectedFile = ref<File | null>(null)

const isOverride = computed(() => !!props.dataset?.id)

watch(
  () => props.show,
  (val) => {
    if (val) {
      name.value = props.dataset ? props.dataset.name : ''
      metric.value = props.dataset ? props.dataset.metric : 'contain'
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
  if (!isOverride.value && !name.value.trim()) {
    message.warning('请输入数据集名称')
    return
  }
  if (!selectedFile.value) {
    message.warning('请选择要上传的数据集文件')
    return
  }

  if (selectedFile.value.size > 50 * 1024 * 1024) {
    message.error('文件大小超出 50MB 限制')
    return
  }

  uploading.value = true
  try {
    if (isOverride.value && props.dataset) {
      await api.datasets.upload(props.dataset.id, selectedFile.value)
      message.success('数据集已覆盖更新，版本已自增')
    } else {
      const created = await api.datasets.create({ name: name.value, metric: metric.value })
      await api.datasets.upload(created.id, selectedFile.value)
      message.success('数据集创建并上传成功')
    }
    emit('update:show', false)
    emit('success')
  } catch (err: any) {
    message.error(err.message || '上传数据集失败')
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
