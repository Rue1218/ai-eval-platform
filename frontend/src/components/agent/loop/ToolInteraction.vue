<template>
  <section class="interaction" aria-live="polite">
    <p v-if="interaction.restricted">交互内容受权限限制。</p>
    <template v-else>
      <strong>{{ titles[interaction.kind] }}</strong>
      <p v-if="interaction.kind === 'approval'" class="interaction-meta">
        <span v-if="interaction.permission_tier">权限档位：{{ tierLabels[interaction.permission_tier] || interaction.permission_tier }}</span>
        <span v-if="interaction.risk_level"> · 风险等级：{{ interaction.risk_level }}</span>
        <span v-if="interaction.risk_level === 'code'">（破坏性命令在所有档位都需批准）</span>
      </p>
      <pre v-if="interaction.display">{{ JSON.stringify(interaction.display, null, 2) }}</pre>
      <form v-if="interaction.kind === 'question' && !interaction.resolved" @submit.prevent="answer">
        <fieldset v-for="q in interaction.questions || []" :key="q.id" :disabled="disabled">
          <legend>{{ q.question || q.title }}{{ q.required === false ? '（选填）' : '' }}</legend>
          <template v-if="q.type !== 'text' && q.options?.length">
            <label v-for="option in q.options" :key="option.label"><input :type="q.type === 'checkbox' ? 'checkbox' : 'radio'" :name="interaction.key + q.id" :value="option.label" @change="choose(q.id, option.label, q.type === 'checkbox', ($event.target as HTMLInputElement).checked)" />{{ option.label }}<small v-if="option.description"> · {{ option.description }}</small></label>
          </template>
          <textarea v-else v-model="values[q.id]" :aria-label="q.question || q.title" :required="q.required !== false" rows="2" />
        </fieldset>
        <button class="loop-primary" :disabled="disabled">提交回答</button>
      </form>
      <div v-else-if="!interaction.resolved" class="interaction-actions">
        <template v-if="interaction.kind === 'approval'"><button :disabled="disabled" class="loop-primary" @click="respond({decision:'allow'})">允许一次</button><button :disabled="disabled" @click="respond({decision:'deny'})">拒绝</button><button :disabled="disabled" @click="respond({decision:'always'})">本连接持续允许</button></template>
        <template v-else><button :disabled="disabled" class="loop-primary" @click="respond({decision:'confirm'})">确认执行</button><button :disabled="disabled" @click="respond({decision:'reject'})">拒绝</button></template>
      </div>
      <p v-if="interaction.resolved">{{ interaction.decision || interaction.outcome || '已回答' }}<span v-if="interaction.answers"> · {{ JSON.stringify(interaction.answers) }}</span></p>
      <small v-else>{{ interaction.submitting ? '已提交，等待权威结果' : expired ? '交互已到期，等待服务端结算' : !canControl ? '当前连接没有控制权' : '操作仅在本回合和有效期内生效' }}</small>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed, reactive, ref, onBeforeUnmount } from 'vue'
import type { Data, InteractionRecord } from '../../../api/agentLoopTypes'
const props = defineProps<{ interaction: InteractionRecord; canControl: boolean; online: boolean }>()
const emit = defineEmits<{ respond: [InteractionRecord, Data] }>()
const now = ref(Date.now()), timer = setInterval(() => { now.value = Date.now() }, 1000)
onBeforeUnmount(() => clearInterval(timer))
const values = reactive<Record<string, string>>({}), selected = reactive<Record<string, string[]>>({})
const titles: Record<string, string> = { approval: '工具权限确认', question: '补充信息', task_confirmation: '确认冻结的评测规格' }
const tierLabels: Record<string, string> = { tier1: '档1 请求批准', tier2: '档2 帮我批准', tier3: '档3 完全访问' }
const expired = computed(() => props.interaction.expires_at && props.interaction.expires_at * 1000 <= now.value)
const disabled = computed(() => !props.canControl || !props.online || expired.value || props.interaction.submitting || props.interaction.resolved || !props.interaction.nonce)
/** 多选用标签数组往返，含逗号的标签不能拆分。 */
function choose(id: string, label: string, multiple: boolean, checked: boolean) { selected[id] = multiple ? [...(selected[id] || []).filter(v => v !== label), ...(checked ? [label] : [])] : [label] }
function answer() { respond({ answers: (props.interaction.questions || []).map((q: Data) => ({ question_id: q.id, answer: q.type === 'checkbox' ? selected[q.id] || [] : selected[q.id]?.[0] || values[q.id] || '' })) }) }
function respond(data: Data) { if (!disabled.value) emit('respond', props.interaction, data) }
</script>
<style scoped>.interaction{border-top:1px solid #dbe8e1;margin-top:12px;padding:14px 0 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto}.interaction-actions{display:flex;flex-wrap:wrap;gap:8px}button{padding:7px 12px;border:1px solid #cdded5;border-radius:7px;cursor:pointer;background:transparent}button:disabled{opacity:.5;cursor:default}fieldset{border:0;padding:10px 0}label{display:block;padding:5px}textarea{width:100%;box-sizing:border-box}small{display:block;color:#64748b;margin-top:8px}</style>
