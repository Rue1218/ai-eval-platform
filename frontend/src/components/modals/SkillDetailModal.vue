<template>
  <n-modal
    :show="show"
    preset="card"
    :trap-focus="false"
    :auto-focus="false"
    :title="`Agent 技能编排详情 · ${skill?.name || ''}`"
    style="width: 760px; max-width: 95vw; border-radius: 14px"
    @update:show="$emit('update:show', $event)"
  >
    <div v-if="skill" class="skill-modal-content">
      <!-- 头部概览条 -->
      <div class="skill-modal-header">
        <div class="skill-title-row">
          <span class="skill-icon">{{ skill.icon }}</span>
          <div style="flex: 1">
            <div class="row-between">
              <div class="row" style="gap: 8px; align-items: center">
                <span class="skill-name">{{ skill.name }}</span>
                <span class="tag-soft mono" style="font-size: 11px">{{ skill.id }}</span>
                <span class="tag-soft skill-builtin-badge">内置核心技能</span>
              </div>
              <span class="status-badge-active">● 运行就绪</span>
            </div>
            <div v-if="hintSummary" class="skill-hint">{{ hintSummary }}</div>
            <div class="skill-desc">{{ skill.desc }}</div>
          </div>
        </div>
      </div>

      <!-- 核心调优与运行指标 -->
      <div class="spec-grid">
        <div class="spec-item">
          <span class="spec-label">适用场景</span>
          <span class="spec-value">{{ skill.scenario }}</span>
        </div>
        <div class="spec-item">
          <span class="spec-label">采样温度 (Temperature)</span>
          <span class="spec-value mono text-ai">{{ skill.temperature }}</span>
        </div>
        <div class="spec-item">
          <span class="spec-label">最大输出 Token (Max Tokens)</span>
          <span class="spec-value mono">{{ skill.maxTokens }}</span>
        </div>
        <div class="spec-item">
          <span class="spec-label">Top-P 核心采样</span>
          <span class="spec-value mono">{{ skill.topP }}</span>
        </div>
      </div>

      <!-- 触发机制与斜杠命令 -->
      <div class="section-block">
        <div class="section-title">
          <span>⚡ 触发机制与斜杠命令 (Trigger & Commands)</span>
        </div>
        <div class="trigger-box">
          <div class="row" style="gap: 8px; align-items: center; flex-wrap: wrap">
            <span class="small tertiary">快捷斜杠命令:</span>
            <span v-for="cmd in skill.slashCommands" :key="cmd" class="cmd-pill mono">{{ cmd }}</span>
            <span class="small tertiary" style="margin-left: 8px">或通过自然语言直接描述意图唤醒</span>
          </div>
        </div>
      </div>

      <!-- 依赖的 MCP 受控短工具 -->
      <div class="section-block">
        <div class="section-title">
          <span>🛠️ 绑定的受控短工具矩阵 (Bound MCP Short Tools)</span>
          <span class="small tertiary">共 {{ skill.tools.length }} 个受控工具 · 毫秒级直连</span>
        </div>
        <div class="tools-grid">
          <div v-for="t in skill.tools" :key="t" class="tool-item-card">
            <div class="row-between">
              <span class="tool-item-name mono">{{ t }}</span>
              <span class="tag-soft" style="font-size: 10px">{{ t.includes('create') || t.includes('confirm') ? 'WRITE' : 'READ' }}</span>
            </div>
            <div class="tool-item-desc small">{{ getToolSimpleDesc(t) }}</div>
          </div>
        </div>
      </div>

      <!-- 执行时序与工作流拓扑 -->
      <div class="section-block">
        <div class="section-title">
          <span>🔄 执行拓扑与意图解析流 (Execution Pipeline)</span>
        </div>
        <div class="pipeline-flow">
          <div class="flow-step">
            <span class="step-num">1</span>
            <span class="step-text">意图解析 & 实体提取</span>
          </div>
          <span class="flow-arrow">➔</span>
          <div class="flow-step">
            <span class="step-num">2</span>
            <span class="step-text">资产查询 (MCP Tools)</span>
          </div>
          <span class="flow-arrow">➔</span>
          <div class="flow-step">
            <span class="step-num">3</span>
            <span class="step-text">TaskSpec 构建 & 确认卡</span>
          </div>
          <span class="flow-arrow">➔</span>
          <div class="flow-step highlight">
            <span class="step-num">4</span>
            <span class="step-text">入队并派生压测</span>
          </div>
        </div>
      </div>

      <!-- 安全与 System Prompt 托管说明 -->
      <div class="section-block guardrail-box">
        <div class="guardrail-title">🔒 System Prompt 安全沙箱与边界说明 (PRD 5.5.2 & API §3.6.2)</div>
        <div class="guardrail-desc">
          本技能的完整工作流存放于统一 <code>SKILL.md</code>，仅在预览或 Agent 选中技能后按需读取。核心 System Prompt 由 Harness 固定生成；管理端只能为特定 Agent 协议档维护受审计的补充提示词，不能覆盖安全规则。
        </div>
      </div>
    </div>

    <template #footer>
      <div class="row-between" style="width: 100%">
        <span class="small tertiary mono">Agent Skills Orchestration · V1.0 Controlled Vault</span>
        <button class="btn btn-secondary btn-sm" @click="$emit('update:show', false)">关闭</button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NModal } from 'naive-ui'
import { skillSummary } from '../../agent/skillLabels'

export interface SkillDetail {
  id: string
  icon: string
  name: string
  desc: string
  scenario: string
  tools: string[]
  slashCommands: string[]
  temperature: number
  maxTokens: number
  topP: number
}

const props = defineProps<{
  show: boolean
  skill: SkillDetail | null
}>()

defineEmits<{
  (e: 'update:show', val: boolean): void
}>()

const hintSummary = computed(() => skillSummary(props.skill?.id))

function getToolSimpleDesc(toolName: string): string {
  const map: Record<string, string> = {
    'model.list': '查询系统协议档与可用模型列表',
    'dataset.list': '检索标准测试集版本与样本总数',
    'kb.list': '查询知识库切块与黄金 QA 资产',
    'report.get': '读取已有评测报告并提取指标快照',
    'task.get': '实时查询任务状态机与样本进度',
    'task.create': '按 TaskSpec 创建任务并推入队列',
    'task.cancel': '请求中止排队中或运行中的任务',
    'dispatch.overview': '读取 Worker 算力节点健康与负载',
    'testcase.confirm': '确认 AI 生成的候选用例转正入库',
  }
  return map[toolName] || '受控内置短工具'
}
</script>

<style scoped>
.skill-modal-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.skill-modal-header {
  padding: 14px 16px;
  background: var(--bg-elevated, #f4f8f8);
  border-radius: 12px;
  border: 1px solid var(--border-subtle, #e5e7eb);
}
.skill-title-row {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.skill-icon {
  font-size: 32px;
  line-height: 1;
}
.skill-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary, #111827);
}
.skill-builtin-badge {
  background: rgba(99, 102, 241, 0.1);
  color: var(--accent-ai, #6366f1);
  border-color: rgba(99, 102, 241, 0.2);
  font-size: 11px;
}
.status-badge-active {
  font-size: 11px;
  color: var(--accent-success, #10b981);
  font-family: var(--font-mono, monospace);
  font-weight: 600;
}
.skill-hint {
  font-size: 12px;
  color: var(--c-agent, #10b981);
  margin-top: 6px;
  font-weight: 600;
}
.skill-desc {
  font-size: 13px;
  color: var(--text-secondary, #6b7280);
  margin-top: 6px;
  line-height: 1.5;
}
.spec-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
}
.spec-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 8px 12px;
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 8px;
  background: var(--bg-main, #ffffff);
}
.spec-label {
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
}
.spec-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #111827);
}
.text-ai {
  color: var(--accent-ai, #6366f1);
}
.section-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #111827);
}
.trigger-box {
  padding: 10px 12px;
  background: var(--bg-elevated, #f4f8f8);
  border-radius: 8px;
  border: 1px solid var(--border-subtle, #e5e7eb);
}
.cmd-pill {
  padding: 2px 8px;
  border-radius: 5px;
  background: #0f172a;
  color: #38bdf8;
  font-size: 11.5px;
  font-weight: 600;
}
.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 8px;
}
.tool-item-card {
  padding: 8px 10px;
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 8px;
  background: var(--bg-main, #ffffff);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tool-item-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--c-profiles, #b45309);
}
.tool-item-desc {
  color: var(--text-secondary, #6b7280);
  line-height: 1.4;
  font-size: 11px;
}
.pipeline-flow {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 10px 12px;
  background: var(--bg-elevated, #f4f8f8);
  border-radius: 8px;
  border: 1px solid var(--border-subtle, #e5e7eb);
}
.flow-step {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: var(--bg-main, #ffffff);
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 500;
}
.flow-step.highlight {
  background: rgba(99, 102, 241, 0.08);
  border-color: var(--accent-ai, #6366f1);
  color: var(--accent-ai, #6366f1);
}
.step-num {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--accent-ai, #6366f1);
  color: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
}
.flow-arrow {
  color: var(--text-tertiary, #9ca3af);
  font-size: 12px;
}
.guardrail-box {
  background: rgba(99, 102, 241, 0.05);
  border: 1px solid rgba(99, 102, 241, 0.18);
  border-radius: 8px;
  padding: 10px 12px;
}
.guardrail-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--accent-ai, #6366f1);
  margin-bottom: 4px;
}
.guardrail-desc {
  font-size: 12px;
  color: var(--text-secondary, #6b7280);
  line-height: 1.5;
}
</style>
