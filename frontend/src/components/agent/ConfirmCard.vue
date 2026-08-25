<template>
  <div class="confirm-card" :class="{ acked: isAcked, open: isOpen }">
    <!-- 卡头 -->
    <div class="confirm-head" @click="toggleFold">
      <span class="kind-tag" :class="`kind-${form.kind}`">{{ kindTitle }}</span>
      <div class="confirm-title">{{ cardTitle }}</div>
      <div v-if="isAcked" class="confirm-summary">{{ summaryText }}</div>
      <div v-if="isAcked" class="chev">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </div>
    </div>

    <!-- 卡身（未 ack 展开编辑，ack 后折叠可查看只读） -->
    <div class="confirm-body">
      <!-- 1. 基准评测字段 -->
      <div v-if="form.kind === 'benchmark'" class="form-fields">
        <div class="field">
          <label class="field-label">被测协议档 <span class="req">*</span> (1–5 个)</label>
          <n-select
            v-model:value="form.profile_ids"
            multiple
            :options="profileOptions"
            :disabled="isAcked"
            placeholder="选择 1–5 个大模型协议档"
            :max-tag-count="3"
          />
          <div v-if="validationErrors.profile_ids" class="field-error">{{ validationErrors.profile_ids }}</div>
        </div>

        <div class="field">
          <label class="field-label">评测数据集 <span class="req">*</span></label>
          <n-select
            v-model:value="form.dataset_id"
            :options="datasetOptions"
            :disabled="isAcked"
            placeholder="选择数据集"
          />
          <div v-if="validationErrors.dataset_id" class="field-error">{{ validationErrors.dataset_id }}</div>
        </div>
      </div>

      <!-- 2. RAG 评测字段 -->
      <div v-else-if="form.kind === 'rag'" class="form-fields">
        <div class="field">
          <label class="field-label">目标知识库 <span class="req">*</span></label>
          <n-select
            v-model:value="form.kb_id"
            :options="kbOptions"
            :disabled="isAcked"
            placeholder="选择知识库"
          />
          <div v-if="validationErrors.kb_id" class="field-error">{{ validationErrors.kb_id }}</div>
        </div>

        <div class="field">
          <label class="field-label">黄金 QA 数据集 <span class="req">*</span></label>
          <n-select
            v-model:value="form.gold_qa_id"
            :options="goldQaOptions"
            :disabled="isAcked"
            placeholder="选择黄金问答集"
          />
          <div v-if="validationErrors.gold_qa_id" class="field-error">{{ validationErrors.gold_qa_id }}</div>
        </div>

        <div class="field">
          <label class="field-label">检索模式 (1–4 种)</label>
          <n-checkbox-group v-model:value="form.rag_mode" :disabled="isAcked">
            <n-space>
              <n-checkbox value="naive" label="Naive" />
              <n-checkbox value="local" label="Local" />
              <n-checkbox value="global" label="Global" />
              <n-checkbox value="hybrid" label="Hybrid (推荐)" />
            </n-space>
          </n-checkbox-group>
        </div>
      </div>

      <!-- 3. 用例生成字段 -->
      <div v-else-if="form.kind === 'testcase'" class="form-fields">
        <div class="field">
          <label class="field-label">需求输入 / PRD 描述</label>
          <n-input
            v-model:value="form.case_source!.text"
            type="textarea"
            :rows="3"
            :disabled="isAcked"
            placeholder="输入或粘贴需求描述、接口规范或产品规格"
          />
          <div v-if="validationErrors.case_source" class="field-error">{{ validationErrors.case_source }}</div>
        </div>
      </div>

      <!-- 运行参数折叠 -->
      <div class="run-fold" :class="{ open: showRunConfig }">
        <div class="run-fold-head" @click="showRunConfig = !showRunConfig">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
          <span>高级运行参数 (采样 / 并发 / 超时)</span>
          <span class="chev">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </span>
        </div>
        <div v-if="showRunConfig" class="run-fold-body">
          <div class="form-row-3">
            <div class="field">
              <label class="field-label">采样样本数</label>
              <n-input-number v-model:value="form.run!.sample_size" :min="1" :max="1000" :disabled="isAcked" />
            </div>
            <div class="field">
              <label class="field-label">并发数</label>
              <n-input-number v-model:value="form.run!.concurrency" :min="1" :max="16" :disabled="isAcked" />
            </div>
            <div class="field">
              <label class="field-label">超时 (秒)</label>
              <n-input-number v-model:value="form.run!.timeout_s" :min="5" :max="300" :disabled="isAcked" />
            </div>
          </div>
          <div class="form-row">
            <div class="field">
              <label class="field-label">Temperature</label>
              <n-input-number v-model:value="form.run!.temperature" :min="0" :max="2" :step="0.1" :disabled="isAcked" />
            </div>
            <div class="field">
              <label class="field-label">Max Tokens</label>
              <n-input-number v-model:value="form.run!.max_tokens" :min="256" :max="8192" :disabled="isAcked" />
            </div>
          </div>
        </div>
      </div>

      <!-- 先评后压配置 -->
      <div v-if="form.kind !== 'stress'" class="switch-row" style="border-top: 1px solid var(--border-subtle); padding-top: 12px">
        <div>
          <div style="font-weight: 500; font-size: 13px">质量成功后自动压测 (先评后压)</div>
          <div style="font-size: 12px; color: var(--text-tertiary)">评测 succeeded 后派生共享发压任务</div>
        </div>
        <n-switch v-model:value="form.with_stress" :disabled="isAcked" />
      </div>

      <!-- 压测参数设置 -->
      <div v-if="form.with_stress || form.kind === 'stress'" class="stress-section" style="margin-top: 10px; padding: 12px; background: var(--bg-elevated); border-radius: 10px">
        <div style="font-size: 12px; font-weight: 600; margin-bottom: 8px; color: var(--c-stress)">压测配置参数</div>
        <div class="form-row">
          <div class="field">
            <label class="field-label">环境</label>
            <n-select
              v-model:value="form.stress!.env"
              :options="[
                { label: '测试环境 (test)', value: 'test' },
                { label: '预发环境 (staging)', value: 'staging' },
                { label: '生产环境 (prod，需会签)', value: 'prod' },
              ]"
              :disabled="isAcked"
            />
          </div>
          <div class="field">
            <label class="field-label">目标 QPS</label>
            <n-input-number v-model:value="form.stress!.qps" :min="1" :max="1000" :disabled="isAcked" />
          </div>
        </div>
        <div class="form-row">
          <div class="field">
            <label class="field-label">时长 (秒)</label>
            <n-input-number v-model:value="form.stress!.duration_s" :min="10" :max="3600" :disabled="isAcked" />
          </div>
          <div class="field">
            <label class="field-label">SLA P99 阈值 (ms)</label>
            <n-input-number v-model:value="form.stress!.sla_p99_ms" :min="10" :max="60000" :disabled="isAcked" placeholder="例如 1500" />
          </div>
        </div>
      </div>
    </div>

    <!-- 卡底操作条 -->
    <div class="confirm-foot">
      <div v-if="isAcked" class="ack-stamp" :class="ackResult ? 'ok' : 'no'">
        {{ ackResult ? '✓ 任务已确认入队' : '✕ 已取消此单' }}
      </div>
      <div class="spacer"></div>
      <template v-if="!isAcked">
        <button class="btn btn-secondary btn-sm" @click="handleCancel">取消</button>
        <button class="btn btn-sign btn-sm" :disabled="loading || submitting" @click="handleConfirm">
          {{ loading || submitting ? '入队中...' : '确认并开始' }}
        </button>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { TaskSpec, Profile, Dataset, KnowledgeBase, GoldQA } from '../../api/types'
import { api } from '../../api/http'
import { validateTaskSpec, createDefaultTaskSpec } from '../../schemas/confirmCard'

const props = defineProps<{
  card: TaskSpec
  isAcked?: boolean
  ackResult?: boolean
  submitting?: boolean
}>()

const emit = defineEmits<{
  (e: 'confirm', patch: TaskSpec): void
  (e: 'cancel'): void
}>()

const defaultSpec = createDefaultTaskSpec(props.card?.kind || 'benchmark')
const form = ref<TaskSpec>({
  ...defaultSpec,
  ...props.card,
  run: { ...defaultSpec.run, ...(props.card?.run || {}) } as any,
  stress: { ...defaultSpec.stress, ...(props.card?.stress || {}) } as any,
})

const showRunConfig = ref(false)
const isOpen = ref(!props.isAcked)
const loading = ref(false)
const validationErrors = ref<Record<string, string>>({})

const profiles = ref<Profile[]>([])
const datasets = ref<Dataset[]>([])
const kbs = ref<KnowledgeBase[]>([])
const goldQAs = ref<GoldQA[]>([])

const profileOptions = computed(() =>
  profiles.value.map((p) => ({ label: `${p.name} (${p.model})`, value: p.id })),
)

const datasetOptions = computed(() =>
  datasets.value.map((d) => ({ label: `${d.name} (v${d.version} · ${d.row_count}行)`, value: d.id })),
)

const kbOptions = computed(() =>
  kbs.value.map((k) => ({ label: `${k.name} (${k.kind === 'lightrag' ? 'LightRAG' : '外部Chat'})`, value: k.id })),
)

const goldQaOptions = computed(() =>
  goldQAs.value.map((g) => ({ label: `${g.name} (v${g.version} · ${g.row_count}条)`, value: g.id })),
)

const kindTitle = computed(() => {
  const map: Record<string, string> = {
    benchmark: '基准评测',
    rag: 'RAG 评测',
    testcase: '用例生成',
    stress: '压测',
  }
  return map[form.value.kind] || form.value.kind
})

const cardTitle = computed(() => {
  if (form.value.kind === 'benchmark') return '确认基准评测'
  if (form.value.kind === 'rag') return '确认 RAG 评测'
  if (form.value.kind === 'testcase') return '确认用例生成'
  return '确认压测'
})

const summaryText = computed(() => {
  if (form.value.kind === 'benchmark') {
    return `${form.value.profile_ids?.length || 0} 个协议档 · 数据集`
  }
  if (form.value.kind === 'rag') {
    return `知识库评测 · 模式: ${form.value.rag_mode?.join(',') || 'hybrid'}`
  }
  return '已确认'
})

function toggleFold() {
  if (props.isAcked) {
    isOpen.value = !isOpen.value
  }
}

async function loadOptions() {
  try {
    const [pList, dList, kList] = await Promise.all([
      api.profiles.list(),
      api.datasets.list(),
      api.kb.list(),
    ])
    profiles.value = pList
    datasets.value = dList
    kbs.value = kList

    if (form.value.kb_id) {
      goldQAs.value = await api.kb.getGoldQA(form.value.kb_id)
    }
  } catch (err) {
    console.error('Failed to load select options:', err)
  }
}

function handleConfirm() {
  const res = validateTaskSpec(form.value)
  if (!res.valid) {
    validationErrors.value = res.errors
    return
  }
  validationErrors.value = {}
  emit('confirm', form.value)
}

function handleCancel() {
  emit('cancel')
}

onMounted(loadOptions)
</script>

<style scoped>
.confirm-card {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--bg-main);
  box-shadow: 0 14px 40px rgba(17, 24, 39, 0.1);
  overflow: hidden;
  max-width: 640px;
  transition: all 0.25s ease;
  animation: card-up 0.3s cubic-bezier(0.2, 0.9, 0.3, 1.05);
}
@keyframes card-up {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.confirm-card.acked {
  background: var(--bg-elevated);
  box-shadow: none;
}
.confirm-card.acked:not(.open) .confirm-body {
  display: none;
}
.confirm-card.acked.open .confirm-body {
  opacity: 0.75;
  pointer-events: none;
}

.confirm-head {
  padding: 16px 20px 0;
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}
.confirm-title {
  font-size: 15px;
  font-weight: 700;
}
.confirm-summary {
  font-size: 12px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.confirm-head .chev {
  margin-left: auto;
  color: var(--text-tertiary);
  transition: transform 0.18s ease;
  display: grid;
  place-items: center;
}
.confirm-card.open .confirm-head .chev {
  transform: rotate(180deg);
}

.confirm-body {
  padding: 14px 20px 6px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}
.field-label {
  font-size: 12.5px;
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

.run-fold {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  margin: 8px 0 10px;
  overflow: hidden;
  background: var(--bg-main);
}
.run-fold-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  color: var(--text-secondary);
}
.run-fold-head:hover {
  background: var(--row-hover);
}
.run-fold-head .chev {
  margin-left: auto;
  transition: transform 0.18s ease;
}
.run-fold.open .run-fold-head .chev {
  transform: rotate(180deg);
}
.run-fold-body {
  padding: 10px 12px;
  border-top: 1px solid var(--border-subtle);
}

.confirm-foot {
  padding: 10px 20px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.confirm-foot .spacer {
  flex: 1;
}

.ack-stamp {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}
.ack-stamp.ok {
  background: #d1fae5;
  color: #047857;
}
.ack-stamp.no {
  background: #f3f4f6;
  color: #6b7280;
}
</style>
