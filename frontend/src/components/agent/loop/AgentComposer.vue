<template>
  <div class="loop-composer" @dragover.prevent @drop.prevent="drop">
    <div class="draft-files"><AttachmentPreview v-for="file in draft.files" :key="file.key" :attachment="{file_id:file.id,filename:file.filename,size:file.size,content_type:file.content_type,preview_url:file.source,uploading:file.uploading,uploadProgress:file.progress,error:!!file.error}" removable @remove="remove(file)"/></div>
    <textarea ref="input" v-model="draft.content" aria-label="消息" placeholder="描述目标，或把文件拖到这里…" rows="2" @input="resize" @keydown="keydown" />
    <div class="composer-bottom">
      <input ref="picker" type="file" multiple hidden :accept="ui?.attachments.upload_suffixes.join(',')" @change="pick"/>
      <button class="loop-control" aria-label="添加附件" @click="picker?.click()">＋ 附件</button>
      <n-popover trigger="click" placement="top"><template #trigger><button class="loop-control model-trigger"><ProviderLogo v-if="ui?.profile" :provider="getProviderLogoKey({model:ui.profile.model})" :size="16"/>{{ ui?.profile?.model || '未配置模型' }} ▾</button></template><div class="model-popover"><strong>平台默认模型</strong><p>全局设置，切换后下一轮生效。</p><select v-if="ui?.permissions.settings" :value="ui.profile?.id" aria-label="平台默认模型" @change="emit('model', ($event.target as HTMLSelectElement).value)"><option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.name }}</option></select><p v-else>当前账号不能修改全局模型。</p><router-link to="/admin/profiles">管理协议档</router-link></div></n-popover>
      <ThinkingControl :model-value="effort" :allowed="ui?.allowed_efforts || []" :model="ui?.profile?.model" @update:model-value="value => emit('effort', value)"/>
      <LoopContextMeter :meter="meter"/>
      <button class="loop-send" :disabled="busy ? !canStop : !ready || !draft.content.trim() || draft.files.some(f => f.uploading || f.error) || draft.submitting" @click="busy ? emit('stop') : emit('submit')">{{ busy ? cancelling ? '取消中…' : '停止' : draft.submitting ? '提交中…' : '发送 ↑' }}</button>
    </div>
    <p v-if="draft.pending" class="draft-note">提交结果待同步。<button :disabled="!ready" @click="emit('retry')">使用原请求 ID 重发</button></p>
    <p v-if="notice" class="draft-note" role="status">{{ notice }}</p>
    <p class="draft-note">Enter 发送 · Shift+Enter 换行 · 附件需附正文；PDF/文档内联提取，音频和旧 Office 仅提供元信息。</p>
  </div>
</template>
<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { NPopover } from 'naive-ui'
import { api } from '../../../api/http'
import type { Profile } from '../../../api/types'
import type { Effort, LoopMeter, LoopUi } from '../../../api/agentLoopTypes'
import type { DraftFile, LoopDraft } from '../../../agent/loop/store'
import AttachmentPreview from '../AttachmentPreview.vue'
import ProviderLogo from '../../ProviderLogo.vue'
import { getProviderLogoKey } from '../../../utils/providerLogo'
import ThinkingControl from './ThinkingControl.vue'
import LoopContextMeter from './LoopContextMeter.vue'
const props = defineProps<{ draft: LoopDraft; ui: LoopUi | null; effort: Effort | null; profiles: Profile[]; meter?: LoopMeter | null; busy: boolean; cancelling: boolean; canStop: boolean; ready: boolean }>()
const emit = defineEmits<{ submit: []; stop: []; retry: []; effort: [Effort]; model: [string] }>()
const picker = ref<HTMLInputElement>(), input = ref<HTMLTextAreaElement>(), notice = ref('')
/** IME 选词不提交；运行中的 Enter 保留下一轮草稿。 */
function keydown(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); if (!props.busy && props.ready && props.draft.content.trim() && !props.draft.submitting && !props.draft.files.some(f => f.uploading || f.error)) emit('submit') } }
function resize() { const el = input.value; if (el) { el.style.height = 'auto'; el.style.height = Math.min(190, el.scrollHeight) + 'px' } }
function focus() { nextTick(() => { input.value?.focus(); resize() }) }
defineExpose({ focus })
/** Tombstone 先标记再移除；迟到上传只结束请求，不能复活草稿引用。 */
function remove(file: DraftFile) { file.removed = true; URL.revokeObjectURL(file.source); props.draft.files = props.draft.files.filter(f => f.key !== file.key) }
async function upload(files: File[]) {
  const draft = props.draft
  for (const file of files) {
    const caps = props.ui?.attachments, suffix = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!caps || !caps.upload_suffixes.includes(suffix) || file.size > caps.max_bytes || (caps.image_suffixes.includes(suffix) && file.size > caps.max_image_bytes)) { notice.value = `附件 ${file.name} 不符合服务端类型或大小限制`; continue }
    const value: DraftFile = { key: crypto.randomUUID(), filename: file.name, size: file.size, content_type: file.type, source: URL.createObjectURL(file), uploading: true, progress: 0, removed: false }
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
<style scoped>.loop-composer{border:1px solid #cadfd3;border-radius:16px;background:var(--bg-card,#fff);box-shadow:0 3px 18px #193b2510;padding:12px}.loop-composer textarea{display:block;box-sizing:border-box;resize:none;width:100%;border:0;outline:none;background:transparent;color:inherit;font:inherit;min-height:58px;max-height:190px;line-height:1.7}.composer-bottom{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.loop-send{margin-left:auto;background:#153d33;color:#fff;border:0;border-radius:9px;padding:10px 16px;font-weight:600;cursor:pointer}.loop-send:disabled{opacity:.45;cursor:default}.draft-files{display:flex;flex-wrap:wrap;gap:8px}.draft-note{font-size:11px;color:#718277;margin:7px 0 0}.model-trigger{display:flex;align-items:center;gap:5px;max-width:220px;overflow:hidden;text-overflow:ellipsis}.model-popover{max-width:280px}.model-popover select{max-width:100%}@media(max-width:480px){.model-trigger{max-width:150px}.loop-composer{padding:9px}.draft-note{font-size:10px}}</style>
