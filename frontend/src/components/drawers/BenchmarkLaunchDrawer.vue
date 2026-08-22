<template>
  <n-drawer :show="show" :width="drawerWidth" @update:show="$emit('update:show', $event)">
    <n-drawer-content title="发起基准评测 (Benchmark)" closable>
      <div class="launch-form">
        <div class="field">
          <label class="field-label">被测协议档 <span class="req">*</span> (1–5 个)</label>
          <n-select
            v-model:value="spec.profile_ids"
            multiple
            :options="profileOptions"
            placeholder="请选择 1–5 个被测模型协议档"
            :max-tag-count="3"
          />
          <div v-if="errors.profile_ids" class="field-error">{{ errors.profile_ids }}</div>
        </div>

        <div class="field">
          <label class="field-label">评测数据集 <span class="req">*</span></label>
          <n-select
            v-model:value="spec.dataset_id"
            :options="datasetOptions"
            placeholder="选择评测数据集"
          />
          <div v-if="errors.dataset_id" class="field-error">{{ errors.dataset_id }}</div>
        </div>

        <div class="panel" style="margin-top: 14px">
          <div class="panel-title">高级运行参数</div>
          <div class="form-row-3">
            <div class="field">
              <label class="field-label">采样数</label>
              <n-input-number v-model:value="spec.run!.sample_size" :min="1" :max="10000" />
            </div>
            <div class="field">
              <label class="field-label">并发数</label>
              <n-input-number v-model:value="spec.run!.concurrency" :min="1" :max="16" />
            </div>
            <div class="field">
              <label class="field-label">超时 (秒)</label>
              <n-input-number v-model:value="spec.run!.timeout_s" :min="5" :max="300" />
            </div>
          </div>
          <div class="form-row">
            <div class="field">
              <label class="field-label">Temperature</label>
              <n-input-number v-model:value="spec.run!.temperature" :min="0" :max="2" :step="0.1" />
            </div>
            <div class="field">
              <label class="field-label">Max Tokens</label>
              <n-input-number v-model:value="spec.run!.max_tokens" :min="256" :max="8192" />
            </div>
          </div>
        </div>

        <div class="switch-row" style="margin-top: 14px">
          <div>
            <div style="font-weight: 500; font-size: 13px">质量成功后自动压测 (先评后压)</div>
            <div style="font-size: 12px; color: var(--text-tertiary)">评测 succeeded 后派生共享发压任务</div>
          </div>
          <n-switch v-model:value="spec.with_stress" />
        </div>

        <div v-if="spec.with_stress" class="panel" style="margin-top: 12px; background: var(--bg-elevated)">
          <div class="panel-title" style="color: var(--c-stress)">压测参数</div>
          <div class="form-row">
            <div class="field">
              <label class="field-label">环境</label>
              <n-select
                v-model:value="spec.stress!.env"
                :options="[
                  { label: '测试环境 (test)', value: 'test' },
                  { label: '预发环境 (staging)', value: 'staging' },
                  { label: '生产环境 (prod，需会签)', value: 'prod' },
                ]"
              />
            </div>
            <div class="field">
              <label class="field-label">目标 QPS</label>
              <n-input-number v-model:value="spec.stress!.qps" :min="1" :max="1000" />
            </div>
          </div>
          <div class="form-row">
            <div class="field">
              <label class="field-label">时长 (秒)</label>
              <n-input-number v-model:value="spec.stress!.duration_s" :min="10" :max="3600" />
            </div>
            <div class="field">
              <label class="field-label">SLA P99 阈值 (ms)</label>
              <n-input-number v-model:value="spec.stress!.sla_p99_ms" :min="10" :max="60000" placeholder="例如 1500" />
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <div style="display: flex; gap: 8px; justify-content: flex-end">
          <n-button @click="$emit('update:show', false)">取消</n-button>
          <n-button type="primary" :loading="submitting" @click="handleSubmit">
            提交并开始评测
          </n-button>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../../api/http'
import type { TaskSpec, Profile, Dataset } from '../../api/types'
import { validateTaskSpec, createDefaultTaskSpec } from '../../schemas/confirmCard'

const props = defineProps<{
  show: boolean
  defaultDatasetId?: string
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
  (e: 'success', taskId: string): void
}>()

/** 移动端自适应抽屉宽度 */
const drawerWidth = computed(() => {
  if (typeof window !== 'undefined' && window.innerWidth <= 640) {
    return '100%'
  }
  return 560
})

const message = useMessage()
const submitting = ref(false)
const errors = ref<Record<string, string>>({})
const profiles = ref<Profile[]>([])
const datasets = ref<Dataset[]>([])

const spec = ref<TaskSpec>(createDefaultTaskSpec('benchmark'))

const profileOptions = computed(() =>
  profiles.value.map((p) => ({ label: `${p.name} (${p.model})`, value: p.id })),
)

const datasetOptions = computed(() =>
  datasets.value.map((d) => ({ label: `${d.name} (v${d.version} · ${d.row_count}行)`, value: d.id })),
)

async function loadOptions() {
  try {
    const [pList, dList] = await Promise.all([api.profiles.list(), api.datasets.list()])
    profiles.value = pList
    datasets.value = dList
  } catch (err) {
    console.error('Failed to load options for launch drawer:', err)
  }
}

async function handleSubmit() {
  const check = validateTaskSpec(spec.value)
  if (!check.valid) {
    errors.value = check.errors
    message.warning('请检查必填表单项')
    return
  }
  errors.value = {}

  submitting.value = true
  try {
    const res = await api.tasks.create(spec.value)
    message.success('评测任务已入队')
    emit('update:show', false)
    emit('success', res.id)
  } catch (err: any) {
    message.error(err.message || '任务创建失败')
  } finally {
    submitting.value = false
  }
}

watch(
  () => props.show,
  (val) => {
    if (val) {
      spec.value = createDefaultTaskSpec('benchmark')
      if (props.defaultDatasetId) spec.value.dataset_id = props.defaultDatasetId
      loadOptions()
    }
  },
)
</script>

<style scoped>
.launch-form {
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
.field-error {
  font-size: 12px;
  color: var(--accent-error);
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.form-row-3 {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
}
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
}
</style>
