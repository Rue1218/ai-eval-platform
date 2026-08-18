<template>
  <n-drawer :show="show" :width="560" @update:show="$emit('update:show', $event)">
    <n-drawer-content title="发起 RAG 知识库评测" closable>
      <div class="launch-form">
        <div class="field">
          <label class="field-label">目标知识库 <span class="req">*</span></label>
          <n-select
            v-model:value="spec.kb_id"
            :options="kbOptions"
            placeholder="选择知识库"
            @update:value="onKbChange"
          />
          <div v-if="errors.kb_id" class="field-error">{{ errors.kb_id }}</div>
        </div>

        <div class="field">
          <label class="field-label">黄金 QA 数据集 <span class="req">*</span></label>
          <n-select
            v-model:value="spec.gold_qa_id"
            :options="goldQaOptions"
            placeholder="选择黄金问答集"
          />
          <div v-if="errors.gold_qa_id" class="field-error">{{ errors.gold_qa_id }}</div>
        </div>

        <div class="field">
          <label class="field-label">检索模式</label>
          <n-checkbox-group v-model:value="spec.rag_mode">
            <n-space>
              <n-checkbox value="naive" label="Naive" />
              <n-checkbox value="local" label="Local" />
              <n-checkbox value="global" label="Global" />
              <n-checkbox value="hybrid" label="Hybrid (默认)" />
            </n-space>
          </n-checkbox-group>
        </div>

        <div class="panel" style="margin-top: 14px">
          <div class="panel-title">运行参数</div>
          <div class="form-row">
            <div class="field">
              <label class="field-label">Top-K 召回数</label>
              <n-input-number v-model:value="spec.run!.k" :min="1" :max="20" />
            </div>
            <div class="field">
              <label class="field-label">并发数</label>
              <n-input-number v-model:value="spec.run!.concurrency" :min="1" :max="16" />
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
import type { TaskSpec, KnowledgeBase, GoldQA } from '../../api/types'
import { validateTaskSpec, createDefaultTaskSpec } from '../../schemas/confirmCard'

const props = defineProps<{
  show: boolean
  defaultKbId?: string
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
  (e: 'success', taskId: string): void
}>()

const message = useMessage()
const submitting = ref(false)
const errors = ref<Record<string, string>>({})
const kbs = ref<KnowledgeBase[]>([])
const goldQAs = ref<GoldQA[]>([])

const spec = ref<TaskSpec>(createDefaultTaskSpec('rag'))

const kbOptions = computed(() =>
  kbs.value.map((k) => ({ label: `${k.name} (${k.kind === 'lightrag' ? 'LightRAG' : '外部Chat'})`, value: k.id })),
)

const goldQaOptions = computed(() =>
  goldQAs.value.map((g) => ({ label: `${g.name} (v${g.version} · ${g.row_count}条)`, value: g.id })),
)

async function loadKbs() {
  try {
    kbs.value = await api.kb.list()
    if (spec.value.kb_id) {
      goldQAs.value = await api.kb.getGoldQA(spec.value.kb_id)
    }
  } catch (err) {
    console.error('Failed to load kbs for launch drawer:', err)
  }
}

async function onKbChange(kbId: string) {
  spec.value.gold_qa_id = undefined
  if (kbId) {
    try {
      goldQAs.value = await api.kb.getGoldQA(kbId)
    } catch (err) {
      goldQAs.value = []
    }
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
    message.success('RAG 评测任务已入队')
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
      spec.value = createDefaultTaskSpec('rag')
      if (props.defaultKbId) spec.value.kb_id = props.defaultKbId
      loadKbs()
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
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
}
</style>
