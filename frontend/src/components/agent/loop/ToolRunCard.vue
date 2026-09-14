<template>
  <details class="tool-run" :class="tool.status" :open="interactions.some(i => !i.resolved)">
    <summary><ToolIcon :name="tool.name"/><span class="tool-title">{{ toolAliases[tool.name] || tool.name }} <small>{{ tool.display.target }}</small></span><span class="tool-state">{{ statusLabels[tool.status] || tool.status }}</span><span v-if="tool.synthetic" class="tool-state">恢复补偿</span></summary>
    <div class="tool-body">
      <section><h4>参数</h4><pre>{{ tool.display.arguments_preview ?? '尚未提供安全参数预览' }}</pre></section>
      <section v-if="tool.event === 'tool.result'"><h4>结果 <span v-if="tool.exit_code !== undefined">· 退出码 {{ tool.exit_code }}</span></h4><details v-if="(tool.display.result_preview?.length || 0) > 2000"><summary>展开长输出</summary><pre>{{ tool.display.result_preview }}</pre></details><pre v-else>{{ tool.display.result_preview === '' ? '（空输出）' : tool.display.result_preview ?? '未提供结果预览' }}</pre></section>
      <p v-if="tool.display.truncated">预览已截断，未提供完整结果接口。</p>
      <p v-if="tool.display.unavailable_reason">{{ tool.display.unavailable_reason }}</p>
      <p v-if="tool.status === 'outcome_unknown'" role="status">执行结果未知，关联范围可能仍受限制；等待可信对账。</p>
      <ToolInteraction v-for="i in interactions.filter(item => item.kind === 'task_confirmation')" :key="i.key" :interaction="i" :can-control="canControl" :online="online" @respond="(record, data) => emit('respond', record, data)"/>
    </div>
  </details>
</template>
<script setup lang="ts">
import type { Data, InteractionRecord, ToolRun } from '../../../api/agentLoopTypes'
import { statusLabels, toolAliases } from '../../../agent/loop/toolPresentation'
import ToolIcon from './ToolIcon.vue'
import ToolInteraction from './ToolInteraction.vue'
defineProps<{ tool: ToolRun; interactions: InteractionRecord[]; canControl: boolean; online: boolean }>()
const emit = defineEmits<{ respond: [InteractionRecord, Data] }>()
</script>
<style scoped>.tool-run{border:1px solid var(--border,#dfe7e3);border-radius:10px;background:var(--bg-card,#fff);margin:10px 0;font-family:var(--font-body)}.tool-run>summary{display:flex;align-items:center;gap:10px;padding:12px;cursor:pointer;list-style:none}.tool-run>summary:after{content:'⌄';color:#7b8b83}.tool-title{flex:1;min-width:0;font-size:13px;font-weight:620}.tool-title small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#607489}.tool-state{font-size:11px;color:#28745d}.failed .tool-state,.outcome_unknown .tool-state{color:#b45309}.tool-body{padding:0 16px 14px}.tool-body h4{font-size:12px;color:#475569;margin:10px 0 5px}.tool-body pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:380px;overflow:auto;border:1px solid #dce5f0;background:linear-gradient(135deg,#f8fbff,#f3f7fd);padding:10px;border-radius:6px;color:#0f3d65;font:12px/1.65 var(--font-mono);font-variant-numeric:tabular-nums}.tool-body section:first-child pre{color:#7c2d12;background:linear-gradient(135deg,#fffaf5,#fff6eb)}.tool-body p{font-size:12px;color:#80644c}.raw-result{margin-top:8px}.raw-result>summary{cursor:pointer;color:#52718b;font-size:12px}</style>
