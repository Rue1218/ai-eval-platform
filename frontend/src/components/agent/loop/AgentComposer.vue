<template>
  <div class="loop-composer" @dragover.prevent @drop.prevent="drop">
    <div class="draft-files"><AttachmentPreview v-for="file in draft.files" :key="file.key" :attachment="{file_id:file.id,filename:file.filename,size:file.size,content_type:file.content_type,preview_url:file.source,uploading:file.uploading,uploadProgress:file.progress,error:!!file.error}" removable @remove="remove(file)"/></div>
    <textarea ref="input" v-model="draft.content" aria-label="消息" placeholder="输入任何评测问题或需求，Shift + Enter 换行，Enter 发送" rows="1" @input="resize" @keydown="keydown" />
    <div class="composer-bottom">
      <input ref="picker" type="file" multiple hidden :accept="ui?.attachments.upload_suffixes.join(',')" @change="pick"/>
      <button class="loop-control attach-trigger" aria-label="添加附件" type="button" :disabled="!ui" @click="picker?.click()"><n-icon :component="AddIcon" :size="15"/></button>
      <n-popover v-model:show="modelOpen" trigger="click" placement="top-start" :show-arrow="false">
        <template #trigger>
          <button class="loop-control model-trigger" type="button" aria-haspopup="dialog" :aria-expanded="modelOpen" :disabled="!profiles.length">
            <ProviderLogo v-if="profile" :provider="getProviderLogoKey({model:profile.model,name:profile.name})" compact/>
            <span class="model-name">{{ profile?.model || '未配置模型' }}</span><n-icon :component="ChevronDownIcon" :size="13" class="model-chevron"/>
          </button>
        </template>
        <section class="model-popover" aria-label="选择 AgentLoop 协议档">
          <header><strong>本轮模型</strong><p>仅列出可用于 AgentLoop 的协议档，切换后下一轮生效。</p></header>
          <button v-for="item in profiles" :key="item.id" class="model-option" :class="{selected:item.id===profile?.id}" type="button" @click="chooseModel(item.id)">
            <ProviderLogo :provider="getProviderLogoKey({model:item.model,name:item.name})" compact/><span><strong>{{ item.name }}</strong><small>{{ item.model }} · {{ protocolLabel(item.protocol) }}</small></span><n-icon v-if="item.id===profile?.id" :component="CheckmarkIcon" :size="16"/>
          </button>
        </section>
      </n-popover>
      <ThinkingControl :model-value="effort" :allowed="profile?.allowed_efforts || []" :model="profile?.model" @update:model-value="value => emit('effort', value)"/>
      <LoopContextMeter :meter="meter"/>
      <button
        class="loop-send"
        :class="{ 'is-busy': busy, 'is-cancelling': cancelling, 'is-ready': ready && draft.content.trim().length > 0 }"
        :aria-label="sendLabel"
        :title="sendLabel"
        :disabled="busy ? !canStop : !ready || !draft.content.trim() || draft.files.some(f => f.uploading || f.error) || draft.submitting"
        type="button"
        @click="busy ? emit('stop') : emit('submit')"
      >
        <svg
          v-if="busy"
          class="loop-send-icon stop-icon"
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden="true"
        >
          <rect x="6" y="6" width="12" height="12" rx="2" />
        </svg>
        <svg
          v-else
          class="loop-send-icon send-icon"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.5"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <line x1="12" y1="19" x2="12" y2="5"></line>
          <polyline points="5 12 12 5 19 12"></polyline>
        </svg>
        <span class="sr-only">{{ sendLabel }}</span>
      </button>
    </div>
    <p v-if="draft.pending" class="draft-note">提交结果待同步。<button :disabled="!ready" @click="emit('retry')">使用原请求 ID 重发</button></p>
    <p v-if="notice" class="draft-note" role="status">{{ notice }}</p>
    <footer class="conversation-metrics" aria-label="当前会话累计模型指标">
      <span title="已提交助手消息的累计输出 token 除以模型生成耗时"><n-icon :component="FastForwardIcon" :size="14"/>生成速度 {{ formatSpeed(metrics.outputTokensPerSecond) }}</span>
      <span title="仅在上游返回缓存读取 token 时计算"><n-icon :component="SwitcherIcon" :size="14"/>缓存命中 {{ formatRate(metrics.cacheHitRate) }}</span>
      <span title="当前会话已提交助手消息的累计用量"><n-icon :component="FileIcon" :size="14"/>输入 {{ formatTokens(metrics.inputTokens) }} · 输出 {{ formatTokens(metrics.outputTokens) }}</span>
    </footer>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { NIcon, NPopover } from 'naive-ui'
import AddIcon from 'naive-ui/es/_internal/icons/Add'
import CheckmarkIcon from 'naive-ui/es/_internal/icons/Checkmark'
import ChevronDownIcon from 'naive-ui/es/_internal/icons/ChevronDown'
import FastForwardIcon from 'naive-ui/es/_internal/icons/FastForward'
import FileIcon from 'naive-ui/es/_internal/icons/File'
import SwitcherIcon from 'naive-ui/es/_internal/icons/Switcher'
import { api } from '../../../api/http'
import { createRequestId } from '../../../utils/requestId'
import type { ConversationMetrics, Effort, LoopMeter, LoopProfile, LoopUi } from '../../../api/agentLoopTypes'
import type { DraftFile, LoopDraft } from '../../../agent/loop/store'
import AttachmentPreview from '../AttachmentPreview.vue'
import ProviderLogo from '../../ProviderLogo.vue'
import { getProviderLogoKey } from '../../../utils/providerLogo'
import ThinkingControl from './ThinkingControl.vue'
import LoopContextMeter from './LoopContextMeter.vue'

const props = defineProps<{ draft: LoopDraft; ui: LoopUi | null; profile: LoopProfile | null; profiles: LoopProfile[]; effort: Effort | null; meter?: LoopMeter | null; metrics: ConversationMetrics; busy: boolean; cancelling: boolean; canStop: boolean; ready: boolean }>()
const emit = defineEmits<{ submit: []; stop: []; retry: []; effort: [Effort]; model: [string] }>()
const picker = ref<HTMLInputElement>(), input = ref<HTMLTextAreaElement>(), notice = ref(''), modelOpen = ref(false)
const sendLabel = computed(() => props.busy ? (props.cancelling ? '正在取消' : '停止执行') : props.draft.submitting ? '正在提交' : '发送')
const protocolLabels: Record<string, string> = { openai_chat: 'OpenAI 兼容', anthropic_messages: 'Anthropic' }
/** IME 选词不提交；运行中的 Enter 保留下一轮草稿。 */
function keydown(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); if (!props.busy && props.ready && props.draft.content.trim() && !props.draft.submitting && !props.draft.files.some(f => f.uploading || f.error)) emit('submit') } }
function resize() { const el = input.value; if (el) { el.style.height = 'auto'; el.style.height = Math.min(200, Math.max(52, el.scrollHeight)) + 'px' } }
function focus() { nextTick(() => { input.value?.focus(); resize() }) }
function chooseModel(id: string) { modelOpen.value = false; emit('model', id) }
function protocolLabel(protocol: string) { return protocolLabels[protocol] || protocol }
function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}K`
  return String(Math.round(value))
}
function formatSpeed(value: number | null): string { return value === null ? '—' : `${formatTokens(value)}/s` }
function formatRate(value: number | null): string { return value === null ? '—' : `${value.toFixed(value >= 10 ? 0 : 1)}%` }
defineExpose({ focus })
/** Tombstone 先标记再移除；迟到上传只结束请求，不能复活草稿引用。 */
function remove(file: DraftFile) { file.removed = true; URL.revokeObjectURL(file.source); props.draft.files = props.draft.files.filter(f => f.key !== file.key) }
async function upload(files: File[]) {
  // 新建/切换会话时能力尚在读取，不能把此时拖入的文件误报为不支持的类型。
  if (!props.ui) { notice.value = '正在读取附件能力，请稍后重试'; return }
  const draft = props.draft
  for (const file of files) {
    const caps = props.ui?.attachments, suffix = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!caps || !caps.upload_suffixes.includes(suffix) || file.size > caps.max_bytes || (caps.image_suffixes.includes(suffix) && file.size > caps.max_image_bytes)) { notice.value = `附件 ${file.name} 不符合服务端类型或大小限制`; continue }
    const value: DraftFile = { key: createRequestId(), filename: file.name, size: file.size, content_type: file.type, source: URL.createObjectURL(file), uploading: true, progress: 0, removed: false }
    draft.files.push(value)
    // 操作响应式代理，上传回调仍然绑定原会话草稿。
    const staged = draft.files[draft.files.length - 1]
    try { const result = await api.files.upload(file, progress => { if (!staged.removed) staged.progress = progress }); if (!staged.removed) Object.assign(staged, { id: result.id, uploading: false, progress: 100 }) }
    catch { if (!staged.removed) { staged.uploading = false; staged.error = '上传失败，请移除后重试' } }
  }
}
function pick(event: Event) { const el = event.target as HTMLInputElement; void upload(Array.from(el.files || [])); el.value = '' }
function drop(event: DragEvent) { void upload(Array.from(event.dataTransfer?.files || [])) }
</script>
<style scoped>
.loop-composer{border:1px solid #d8e2de;border-radius:20px;background:#fff;box-shadow:0 4px 20px -2px rgba(23,74,58,.06),0 2px 6px -1px rgba(15,23,42,.04);padding:12px 14px 10px;transition:border-color .2s ease,box-shadow .2s ease,background-color .2s ease}.loop-composer:hover{border-color:#c4d8ce;box-shadow:0 6px 24px -2px rgba(23,74,58,.09),0 3px 8px -1px rgba(15,23,42,.05)}.loop-composer:focus-within{border-color:#1f5947;box-shadow:0 8px 30px -2px rgba(23,74,58,.12),0 0 0 3px rgba(31,89,71,.12)}.loop-composer textarea{display:block;box-sizing:border-box;resize:none;width:100%;border:0;outline:none;background:transparent;color:#263548;font:inherit;font-size:14.5px;min-height:52px;max-height:200px;padding:6px 8px 8px;line-height:1.6}.loop-composer textarea::placeholder{color:#99a6b6}[data-theme='dark'] .loop-composer{background:#111827;border-color:rgba(255,255,255,.12);box-shadow:0 4px 24px -2px rgba(0,0,0,.5),0 2px 6px -1px rgba(0,0,0,.3)}[data-theme='dark'] .loop-composer textarea{color:#f3f4f6}[data-theme='dark'] .loop-composer:focus-within{border-color:#16977a;box-shadow:0 8px 30px -2px rgba(0,0,0,.6),0 0 0 3px rgba(22,151,122,.2)}.composer-bottom{display:flex;min-width:0;min-height:34px;align-items:center;gap:3px}.loop-control{display:inline-flex;min-width:0;align-items:center;border:1px solid transparent;border-radius:8px;background:transparent;color:#667487;padding:6px 7px;font-size:12px;line-height:18px;cursor:pointer}.loop-control:hover:not(:disabled){background:#f3f7f5;color:#304a3e}.loop-control:disabled{cursor:default;opacity:.55}.attach-trigger{width:28px;height:30px;justify-content:center;padding:0}.model-trigger{max-width:min(250px,42vw);gap:5px}.model-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.model-chevron{flex:0 0 auto;color:#8895a4}.model-popover{width:min(330px,calc(100vw - 30px));padding:5px}.model-popover header{padding:7px 8px 9px}.model-popover header strong{font-size:13px;color:#2e3b4c}.model-popover header p{margin:3px 0 0;color:#7a8798;font-size:11px;line-height:1.45}.model-option{display:flex;width:100%;align-items:center;gap:7px;border:1px solid transparent;border-radius:9px;background:transparent;color:#3d4b5c;padding:8px;text-align:left;cursor:pointer}.model-option:hover,.model-option.selected{background:#f2f7f4;border-color:#dae9e0}.model-option>span{display:grid;min-width:0;gap:1px}.model-option strong,.model-option small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.model-option strong{font-size:12px}.model-option small{color:#7c8998;font-size:11px}.model-option>.n-icon{margin-left:auto;color:#287551}.loop-send{display:inline-flex;flex:0 0 auto;width:32px;height:32px;margin-left:auto;align-items:center;justify-content:center;border:0;border-radius:50%;background:#edf1f2;color:#94a3b8;padding:0;cursor:pointer;transition:background-color .18s ease,color .18s ease,transform .15s ease,box-shadow .18s ease,opacity .18s ease}.loop-send:not(:disabled){background:#1f5947;color:#fff;box-shadow:0 1px 3px rgba(23,74,58,.25)}.loop-send:not(:disabled):hover{background:#184738;color:#fff;transform:scale(1.05);box-shadow:0 2px 6px rgba(23,74,58,.35)}.loop-send:not(:disabled):active{background:#143d30;transform:scale(.96)}.loop-send:disabled{cursor:not-allowed;opacity:.65}.loop-send.is-cancelling{opacity:.8;cursor:wait}.loop-send-icon{display:block;flex-shrink:0}[data-theme='dark'] .loop-send{background:rgba(255,255,255,.08);color:rgba(255,255,255,.3)}[data-theme='dark'] .loop-send:not(:disabled){background:#16977a;color:#fff;box-shadow:0 1px 3px rgba(0,0,0,.4)}[data-theme='dark'] .loop-send:not(:disabled):hover{background:#148369;color:#fff}.draft-files{display:flex;flex-wrap:wrap;gap:8px;padding:2px 2px 5px}.draft-note{margin:6px 5px 1px;color:#718277;font-size:11px}.draft-note button{border:0;background:transparent;color:#356f59;padding:0;text-decoration:underline;cursor:pointer}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);clip-path:inset(50%);white-space:nowrap}@media(max-width:560px){.loop-composer{border-radius:14px;padding:7px}.loop-composer textarea{font-size:13px}.model-trigger{max-width:44vw}.model-popover{width:min(310px,calc(100vw - 22px))}}@media(prefers-reduced-motion:reduce){.loop-composer,.loop-send{transition:none}}
.conversation-metrics{display:flex;flex-wrap:wrap;align-items:center;gap:5px 14px;margin:7px 5px 1px;color:#8290a0;font-size:11px;font-variant-numeric:tabular-nums}.conversation-metrics span{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}.conversation-metrics .n-icon{color:#7388a0}.loop-composer textarea:focus,.loop-composer textarea:focus-visible{border:0!important;outline:0!important;box-shadow:none!important}
</style>
