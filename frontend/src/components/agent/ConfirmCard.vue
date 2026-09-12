<template>
  <div
    class="confirm-card"
    :class="{ acked: item.isAcked, open: item.open, 'no-anim': item.noAnim }"
    :data-od-id="`confirm-card-${item.card.kind}`"
  >
    <div class="confirm-head" @click="item.isAcked && (item.open = !item.open)">
      <KindTag :kind="item.card.kind" />
      <span class="confirm-title">{{ confirmTitle }}</span>
      <span class="confirm-summary">{{ item.summary }}</span>
      <svg class="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </div>

    <div class="confirm-body">
      <template v-if="item.card.kind === 'benchmark'">
        <div class="field">
          <span class="field-label">kind</span>
          <div>
            <KindTag kind="benchmark" />
            <span class="small tertiary">&#x3000;一任务一种 kind</span>
          </div>
        </div>

        <div class="field">
          <span class="field-label">profile_ids（被测协议档，1–5 个）<i class="req">*</i></span>
          <div class="chip-group">
            <button
              v-for="p in availableProfiles"
              :key="p.id"
              class="chip"
              :class="{ on: item.card.profile_ids?.includes(p.id) }"
              @click="toggleProfile(p.id)"
            >
              {{ p.name }} <span class="mono" style="opacity: 0.7">{{ p.model }}</span>
            </button>
          </div>
          <div v-if="item.fieldErrors?.profile_ids" class="field-error">{{ item.fieldErrors.profile_ids }}</div>
        </div>

        <div class="field">
          <span class="field-label">dataset_id <i class="req">*</i></span>
          <select v-model="item.card.dataset_id" class="select">
            <option v-for="d in availableDatasets" :key="d.id" :value="d.id">
              {{ d.name }} v{{ d.version }} · {{ d.row_count }} 行
            </option>
          </select>
        </div>
      </template>

      <template v-else-if="item.card.kind === 'rag'">
        <div class="field">
          <span class="field-label">kind</span>
          <div><KindTag kind="rag" /></div>
        </div>

        <div class="form-row">
          <div class="field">
            <span class="field-label">kb_id <i class="req">*</i></span>
            <select v-model="item.card.kb_id" class="select" @change="onKbChange">
              <option v-for="k in availableKbs" :key="k.id" :value="k.id">
                {{ k.name }}（{{ k.kind === 'lightrag' ? 'LightRAG' : '外部 Chat' }}）
              </option>
            </select>
          </div>
          <div class="field">
            <span class="field-label">gold_qa_id <i class="req">*</i></span>
            <select v-model="item.card.gold_qa_id" class="select">
              <option v-for="g in availableGoldQas" :key="g.id" :value="g.id">
                {{ g.name }} v{{ g.version }} · {{ g.row_count }} 条
              </option>
            </select>
          </div>
        </div>

        <div v-if="isExternalKb" class="field">
          <span class="field-label">profile_ids（外部 RAG 服务档，恰好 1 个）<i class="req">*</i></span>
          <select
            class="select"
            :value="item.card.profile_ids?.[0] || ''"
            @change="onExternalProfileChange(($event.target as HTMLSelectElement).value)"
          >
            <option value="" disabled>请选择外部 RAG 服务档</option>
            <option v-for="p in availableProfiles" :key="p.id" :value="p.id">
              {{ p.name }} · {{ p.model }}
            </option>
          </select>
          <div v-if="item.fieldErrors?.profile_ids" class="field-error">{{ item.fieldErrors.profile_ids }}</div>
        </div>
        <div v-else class="field">
          <span class="field-label">rag_mode（1–4 个，默认 hybrid）</span>
          <div class="chip-group">
            <button
              v-for="m in ['naive', 'local', 'global', 'hybrid']"
              :key="m"
              class="chip"
              :class="{ on: item.card.rag_mode?.includes(m) }"
              @click="toggleRagMode(m)"
            >
              {{ m }}
            </button>
          </div>
          <div v-if="item.fieldErrors?.rag_mode" class="field-error">{{ item.fieldErrors.rag_mode }}</div>
        </div>
      </template>

      <template v-else-if="item.card.kind === 'testcase'">
        <div class="field">
          <span class="field-label">kind</span>
          <div><KindTag kind="testcase" /></div>
        </div>
        <div class="field">
          <span class="field-label">case_source <i class="req">*</i></span>
          <textarea
            v-model="item.card.case_source.text"
            class="textarea"
            placeholder="粘贴 PRD / 接口描述文本（或用附件上传 OpenAPI / Excel）"
            @input="clearFieldError('case_source')"
          ></textarea>
          <div v-if="item.fieldErrors?.case_source" class="field-error">{{ item.fieldErrors.case_source }}</div>
        </div>
        <div class="field-hint">
          规模参考上限：PRD 简单 / 中 / 复杂 → 20 / 45 / 80 条；超上限将停止并提示拆分。生成后需在 72h 内确认入库。
        </div>
      </template>

      <div v-if="['benchmark', 'rag'].includes(item.card.kind)" class="fold-card" :class="{ open: item.showRunConfig }">
        <div class="fold-head" @click="item.showRunConfig = !item.showRunConfig">
          <span class="fold-title">高级运行参数</span>
          <span class="small tertiary mono">sample {{ item.card.run?.sample_size ?? 1000 }} · 并发 {{ item.card.run?.concurrency ?? 4 }} · 超时 {{ item.card.run?.timeout_s ?? 60 }}s · 重试 {{ item.card.run?.retry ?? 1 }} · T={{ item.card.run?.temperature ?? 0 }} · {{ item.card.run?.max_tokens ?? 1024 }} tokens</span>
          <svg class="chev" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </div>
        <div v-show="item.showRunConfig" class="fold-body">
          <div class="form-row">
            <div class="field">
              <span class="field-label">sample_size（抽样行数）</span>
              <n-input-number v-model:value="item.card.run.sample_size" :min="1" :max="1000" placeholder="默认 1000" size="small" />
            </div>
            <div class="field">
              <span class="field-label">concurrency（并发数）</span>
              <n-input-number v-model:value="item.card.run.concurrency" :min="1" :max="64" placeholder="默认 4" size="small" />
            </div>
          </div>
          <div class="form-row">
            <div class="field">
              <span class="field-label">timeout_s（单次超时秒）</span>
              <n-input-number v-model:value="item.card.run.timeout_s" :min="1" placeholder="默认 60s" size="small" />
            </div>
            <div class="field">
              <span class="field-label">retry（失败重试次数）</span>
              <n-input-number v-model:value="item.card.run.retry" :min="0" :max="5" placeholder="默认 1" size="small" />
            </div>
          </div>
          <div class="form-row">
            <div class="field">
              <span class="field-label">temperature（采样温度）</span>
              <n-input-number v-model:value="item.card.run.temperature" :min="0" :max="2" :step="0.1" placeholder="默认 0" size="small" />
            </div>
            <div class="field">
              <span class="field-label">max_tokens（最大生成 tokens）</span>
              <n-input-number v-model:value="item.card.run.max_tokens" :min="1" placeholder="默认 1024" size="small" />
            </div>
          </div>
          <div class="field">
            <span class="field-label">max_usd（单任务预算上限）</span>
            <n-input-number v-model:value="item.card.run.max_usd" :min="0" :step="0.5" placeholder="默认 5" size="small" />
            <span class="field-hint">累计 usage 超限即停并返回 BUDGET_EXCEEDED（F-CM-06）</span>
          </div>
          <div class="field" style="margin-bottom: 0">
            <span class="field-label">system_prompt（可选）</span>
            <n-input v-model:value="item.card.run.system_prompt" placeholder="留空则不注入" size="small" />
          </div>
        </div>
      </div>

      <div v-if="['benchmark', 'rag'].includes(item.card.kind)" class="fold-card" :class="{ open: item.card.with_stress }">
        <div class="fold-head" @click="item.card.with_stress = !item.card.with_stress">
          <label class="row" style="gap: 8px; cursor: pointer" @click.stop>
            <input v-model="item.card.with_stress" type="checkbox" />
            <span class="fold-title">先评后压（质量成功后自动派生共享压测）</span>
          </label>
          <svg class="chev" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </div>
        <div v-show="item.card.with_stress" class="fold-body">
          <div class="form-row">
            <div class="field">
              <span class="field-label">压测环境 (env) <i class="req">*</i></span>
              <select v-model="item.card.stress.env" class="select">
                <option value="dev">dev · 开发环境</option>
                <option value="test">test · 测试环境（免会签）</option>
                <option value="staging">staging · 预发环境</option>
                <option value="prod">prod · 生产环境（需双人会签）</option>
              </select>
            </div>
            <div class="field">
              <span class="field-label">目标 QPS (qps) <i class="req">*</i></span>
              <n-input-number v-model:value="item.card.stress.qps" :min="1" :max="1000" placeholder="例如 50" size="small" />
            </div>
          </div>
          <div class="form-row">
            <div class="field">
              <span class="field-label">压测时长 duration_s（秒）<i class="req">*</i></span>
              <n-input-number v-model:value="item.card.stress.duration_s" :min="10" :max="3600" placeholder="默认 60s" size="small" />
            </div>
            <div class="field">
              <span class="field-label">sla_p99_ms（可选）</span>
              <n-input-number v-model:value="item.card.stress.sla_p99_ms" :min="1" placeholder="如 1500" size="small" />
              <span class="field-hint">不填不出「是否达标」</span>
            </div>
          </div>
          <div v-if="item.card.stress.env === 'prod'" class="badge badge-warning" style="margin-top: 6px">
            ⚠ prod 生产压测：评测成功后子任务将处于待会签状态，会签完成后才开始发压。会签人：{{ prodApproversText }}
          </div>
        </div>
      </div>
    </div>

    <div class="confirm-foot">
      <template v-if="!item.isAcked">
        <span class="confirm-note" :class="{ warn: !!activeTask }">
          {{
            !canConfirm
              ? `等待 ${confirmAuthorLabel} 确认`
              : activeTask
                ? '当前会话已有任务进行中（槽位含压测子任务），完成后才能再开新长任务'
                : '未确认不入队；确认前可修改字段'
          }}
        </span>
        <span class="spacer"></span>
        <template v-if="canConfirm">
          <button class="btn btn-secondary" @click="emit('cancel')">取消</button>
          <button class="btn btn-sign" :disabled="!!activeTask" @click="emit('confirm')">确认并开始</button>
        </template>
      </template>
      <template v-else>
        <span class="ack-stamp" :class="item.ackResult ? 'ok' : 'no'">
          {{ item.ackResult ? '已确认 · 任务入队 queued' : '已取消 · confirm_ack { ok: false }' }}
        </span>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NInput, NInputNumber } from 'naive-ui'
import type { Dataset, GoldQA, KnowledgeBase, Profile } from '../../api/types'
import KindTag from '../common/KindTag.vue'

/** 确认卡展示所需的会话流条目（与 Agent.vue StreamItem 确认卡字段对齐）。 */
export interface ConfirmCardItem {
  card?: any
  isAcked?: boolean
  ackResult?: boolean
  summary?: string
  open?: boolean
  showRunConfig?: boolean
  noAnim?: boolean
  fieldErrors?: Record<string, string>
}

const props = defineProps<{
  item: ConfirmCardItem
  availableProfiles: Profile[]
  availableDatasets: Dataset[]
  availableKbs: KnowledgeBase[]
  availableGoldQas: GoldQA[]
  activeTask: unknown
  prodApproversText: string
  canConfirm: boolean
  confirmAuthorLabel: string
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const confirmTitle = computed(() => {
  const titles: Record<string, string> = {
    benchmark: '确认基准评测',
    rag: '确认 RAG 评测',
    testcase: '确认生成用例',
    stress: '确认压测',
  }
  return titles[props.item.card?.kind] || '确认评测任务'
})

/** F10：当前选中知识库是否为外部 Chat 库（无 rag_mode，改选恰好 1 个外部 RAG 服务档）。 */
const isExternalKb = computed(() => {
  return props.availableKbs.find((kb) => kb.id === props.item.card?.kb_id)?.kind === 'external_chat'
})

function clearFieldError(key: string) {
  if (props.item.fieldErrors) delete props.item.fieldErrors[key]
}

function toggleProfile(pid: string) {
  const card = props.item.card
  if (!card.profile_ids) card.profile_ids = []
  const idx = card.profile_ids.indexOf(pid)
  if (idx >= 0) card.profile_ids.splice(idx, 1)
  else card.profile_ids.push(pid)
  clearFieldError('profile_ids')
}

function toggleRagMode(mode: string) {
  const card = props.item.card
  if (!card.rag_mode) card.rag_mode = ['hybrid']
  const idx = card.rag_mode.indexOf(mode)
  if (idx >= 0) {
    if (card.rag_mode.length > 1) card.rag_mode.splice(idx, 1)
  } else {
    card.rag_mode.push(mode)
  }
  clearFieldError('rag_mode')
}

function onKbChange() {
  props.item.card.profile_ids = []
  clearFieldError('profile_ids')
  clearFieldError('rag_mode')
}

function onExternalProfileChange(pid: string) {
  props.item.card.profile_ids = pid ? [pid] : []
  clearFieldError('profile_ids')
}
</script>
