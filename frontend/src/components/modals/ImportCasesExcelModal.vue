<template>
  <n-modal
    :show="show"
    preset="card"
    title="导入 Excel 用例"
    style="width: 560px; max-width: calc(100vw - 24px)"
    @update:show="$emit('update:show', $event)"
  >
    <div class="import-form">
      <div class="field">
        <label class="field-label">导入目标</label>
        <n-radio-group v-model:value="target" name="import-target">
          <n-space>
            <n-radio value="new">创建为新用例集</n-radio>
            <n-radio value="current" :disabled="!canImportCurrent">导入到当前用例集</n-radio>
          </n-space>
        </n-radio-group>
        <div class="field-hint">
          {{ targetHint }}
        </div>
      </div>

      <div v-if="target === 'new'" class="field">
        <label class="field-label">用例集名称</label>
        <n-input v-model:value="setName" placeholder="默认使用文件名" />
      </div>

      <div v-if="target === 'current'" class="field">
        <label class="field-label">写入方式</label>
        <n-radio-group v-model:value="mode" name="import-mode">
          <n-space>
            <n-radio value="append">追加（同编号则更新）</n-radio>
            <n-radio value="replace">覆盖当前全部用例</n-radio>
          </n-space>
        </n-radio-group>
      </div>

      <div class="field">
        <label class="field-label">Excel 文件 (.xlsx) <span class="req">*</span></label>
        <div class="field-hint">
          支持平台导出列、testcase-tools 标准列（用例编号/所属模块/用例标题/…），以及简化列「模块 / 名称 / 步骤 / 预期」。表头可出现在前 20 行。
        </div>
        <n-upload
          ref="uploadRef"
          :default-upload="false"
          :max="1"
          accept=".xlsx,.xlsm"
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
            <div style="font-size: 13px; font-weight: 500">点击或将 .xlsx 拖拽至此处</div>
          </n-upload-dragger>
        </n-upload>
      </div>

      <div class="row" style="gap: 8px">
        <button class="link-btn" type="button" @click="downloadTemplate">下载 Excel 模板</button>
      </div>
    </div>

    <template #footer>
      <div style="display: flex; gap: 8px; justify-content: flex-end">
        <n-button @click="$emit('update:show', false)">取消</n-button>
        <n-button type="primary" :loading="importing" @click="handleImport">开始导入</n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMessage, type UploadFileInfo, type UploadInst } from 'naive-ui'
import { api } from '../../api/http'
import type { CaseSet } from '../../api/types'

const props = defineProps<{
  show: boolean
  currentSet?: CaseSet | null
  folderId?: string
}>()

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
  (e: 'imported', setId: string): void
}>()

const message = useMessage()
const uploadRef = ref<UploadInst | null>(null)
const file = ref<File | null>(null)
const importing = ref(false)
const target = ref<'new' | 'current'>('new')
const mode = ref<'append' | 'replace'>('append')
const setName = ref('')

const canImportCurrent = computed(() => props.currentSet?.status === 'generated')

const targetHint = computed(() => {
  if (target.value === 'new') return '将按文件内容新建用例集；文件名可作为默认名称。'
  return '追加不会删除已有行；覆盖会先清空当前用例再写入。'
})

watch(
  () => props.show,
  (show) => {
    if (!show) return
    file.value = null
    setName.value = ''
    mode.value = 'append'
    target.value = canImportCurrent.value ? 'current' : 'new'
    uploadRef.value?.clear()
  },
)

function handleFileChange(options: { fileList: UploadFileInfo[] }) {
  const next = options.fileList[0]?.file || null
  file.value = next
  if (next && !setName.value.trim()) {
    setName.value = next.name.replace(/\.(xlsx|xlsm)$/i, '')
  }
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

async function downloadTemplate() {
  try {
    const blob = await api.cases.downloadImportTemplate()
    triggerDownload(blob, '用例导入模板.xlsx')
    message.success('已下载 Excel 模板')
  } catch (err: any) {
    message.error(err.message || '下载模板失败')
  }
}

async function handleImport() {
  if (!file.value) {
    message.warning('请先选择 Excel 文件')
    return
  }
  importing.value = true
  try {
    let setId = props.currentSet?.id
    if (target.value === 'new' || !setId) {
      const name = setName.value.trim() || file.value.name.replace(/\.(xlsx|xlsm)$/i, '')
      const created = await api.cases.createSet({
        name,
        folder_id: props.folderId || undefined,
      })
      setId = created.id
      const result = await api.cases.importExcel(setId, file.value, 'replace')
      message.success(`已导入 ${result.imported_count} 条用例${result.skipped_count ? `，跳过 ${result.skipped_count} 行` : ''}`)
      emit('imported', setId)
      emit('update:show', false)
      return
    }
    const result = await api.cases.importExcel(setId, file.value, mode.value)
    message.success(`已导入 ${result.imported_count} 条用例${result.skipped_count ? `，跳过 ${result.skipped_count} 行` : ''}`)
    emit('imported', setId)
    emit('update:show', false)
  } catch (err: any) {
    message.error(err.message || '导入 Excel 失败')
  } finally {
    importing.value = false
  }
}
</script>

<style scoped>
.import-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.field-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 6px;
  line-height: 1.6;
}
.req {
  color: var(--accent-error);
}
</style>
