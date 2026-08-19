<template>
  <div v-if="node" class="wf-inspector">
    <!-- 面板顶栏 -->
    <div class="inspector-header">
      <div class="inspector-title-wrap">
        <div class="node-icon-box" :style="{ '--node-accent': node.color }">
          <span>{{ node.icon }}</span>
        </div>
        <div>
          <div class="inspector-title">{{ node.name }}</div>
          <div class="inspector-subtitle">{{ node.description }}</div>
        </div>
      </div>
      <button class="close-btn" title="关闭面板" @click="$emit('close')">×</button>
    </div>

    <!-- 面板内容滚动区 -->
    <div class="inspector-body">
      <!-- 基础通用配置 -->
      <div class="form-section">
        <div class="section-title">基础属性</div>
        <div class="field mb12">
          <label class="field-label">节点名称</label>
          <input v-model="node.name" class="input" placeholder="输入节点自定义名称" />
        </div>
        <div class="field mb12">
          <label class="field-label">节点描述</label>
          <input v-model="node.description" class="input" placeholder="简要说明该节点作用" />
        </div>
      </div>

      <!-- 业务专项配置 -->
      <div class="form-section">
        <div class="section-title">参数配置 ({{ categoryLabel }})</div>

        <!-- 1. Agent 调度内核配置 -->
        <template v-if="node.type === 'agent_kernel'">
          <div class="field mb12">
            <label class="field-label">分发策略 (Strategy)</label>
            <select v-model="node.config.strategy" class="select">
              <option value="负载均衡">负载均衡 (Round Robin & Weight)</option>
              <option value="优先级抢占">优先级抢占 (Priority Preemption)</option>
              <option value="亲和性">亲和性调度 (Affinity Binding)</option>
            </select>
          </div>
          <div class="field mb12">
            <div class="row-between">
              <label class="field-label">最大并发任务数 (max_running_tasks)</label>
              <span class="mono font-bold" style="color: var(--accent-ai)">{{ node.config.max_running_tasks }}</span>
            </div>
            <input
              v-model.number="node.config.max_running_tasks"
              type="range"
              class="cap-slider"
              min="1"
              max="8"
              step="1"
            />
          </div>
          <div class="field mb12">
            <label class="field-label">心跳轮询周期 (ms)</label>
            <input v-model.number="node.config.heartbeat_ms" type="number" class="input num" min="100" max="5000" step="100" />
          </div>
        </template>

        <!-- 2. Worker 执行节点配置 -->
        <template v-if="node.type === 'worker_target'">
          <div class="field mb12">
            <label class="field-label">绑定 Worker 节点</label>
            <select v-model="node.config.worker_id" class="select" @change="onWorkerChange">
              <option v-for="w in availableWorkers" :key="w.id" :value="w.id">
                {{ w.id }} · {{ w.name }} ({{ w.state }})
              </option>
            </select>
          </div>
          <div class="field mb12">
            <label class="field-label">调度权重 (Weight)</label>
            <input v-model.number="node.config.weight" type="number" class="input num" min="10" max="500" />
          </div>
        </template>

        <!-- 3. 基准数据集源配置 -->
        <template v-if="node.type === 'dataset_source'">
          <div class="field mb12">
            <label class="field-label">选择基准数据集</label>
            <select v-model="node.config.dataset_id" class="select" @change="onDatasetChange">
              <option value="">-- 选择已有数据集 --</option>
              <option v-for="ds in availableDatasets" :key="ds.id" :value="ds.id">
                {{ ds.name }} (v{{ ds.version }} · {{ ds.row_count }} 行)
              </option>
            </select>
          </div>
          <div class="field mb12">
            <div class="row-between">
              <label class="field-label">样本抽样数量 (Sample Size)</label>
              <span class="mono font-bold" style="color: var(--c-datasets)">{{ node.config.sample_size }}</span>
            </div>
            <input
              v-model.number="node.config.sample_size"
              type="range"
              class="cap-slider"
              min="10"
              max="500"
              step="10"
            />
          </div>
          <div class="field mb12">
            <label class="field-label">主要评测指标 (Metric)</label>
            <select v-model="node.config.metric" class="select">
              <option value="contain">包含率 (Contain Rate)</option>
              <option value="exact">精确匹配 (Exact Match)</option>
              <option value="judge">裁判打分 (LLM Judge)</option>
              <option value="mrr">平均倒数排名 (MRR)</option>
            </select>
          </div>
        </template>

        <!-- 4. PRD 智能用例生成配置 -->
        <template v-if="node.type === 'case_gen'">
          <div class="field mb12">
            <label class="field-label">用例集名称</label>
            <input v-model="node.config.name" class="input" placeholder="例如：支付中心 PRD 用例生成" />
          </div>
          <div class="field mb12">
            <label class="field-label">PRD 需求文本 / 描述</label>
            <textarea
              v-model="node.config.prd_text"
              class="input textarea"
              rows="4"
              placeholder="输入 PRD 文本或接口规范..."
            ></textarea>
          </div>
          <div class="field mb12">
            <label class="field-label">入库映射目标</label>
            <select v-model="node.config.mapping_target" class="select">
              <option value="dataset">映射并创建为基准数据集 (Dataset)</option>
              <option value="gold_qa">映射为知识库黄金 QA (Gold QA)</option>
            </select>
          </div>
        </template>

        <!-- 5. 大模型基准评测配置 -->
        <template v-if="node.type === 'benchmark_eval'">
          <div class="field mb12">
            <label class="field-label">被测模型协议档 (支持多选对比)</label>
            <div class="profile-chips">
              <label
                v-for="p in availableProfiles"
                :key="p.id"
                class="profile-checkbox-chip"
                :class="{ checked: (node.config.profile_ids || []).includes(p.id) }"
              >
                <input
                  type="checkbox"
                  :value="p.id"
                  :checked="(node.config.profile_ids || []).includes(p.id)"
                  @change="toggleProfile(p.id)"
                />
                <span class="mono">{{ p.name }}</span>
                <span class="tertiary" style="font-size: 10px">({{ p.protocol }})</span>
              </label>
            </div>
          </div>
          <div class="grid-2 mb12">
            <div class="field">
              <label class="field-label">采样温度 (Temperature)</label>
              <input v-model.number="node.config.temperature" type="number" class="input num" min="0" max="1" step="0.1" />
            </div>
            <div class="field">
              <label class="field-label">单任务预算 ($)</label>
              <input v-model.number="node.config.max_usd" type="number" class="input num" min="1" max="100" step="1" />
            </div>
          </div>
          <div class="field mb12">
            <label class="checkbox-label">
              <input v-model="node.config.with_stress" type="checkbox" />
              <span>评测成功后自动派生共享压测（先评后压）</span>
            </label>
          </div>
        </template>

        <!-- 6. RAG 知识库评测配置 -->
        <template v-if="node.type === 'rag_eval'">
          <div class="field mb12">
            <label class="field-label">选择知识库 (KB)</label>
            <select v-model="node.config.kb_id" class="select" @change="onKbChange">
              <option value="">-- 选择已有知识库 --</option>
              <option v-for="kb in availableKbs" :key="kb.id" :value="kb.id">
                {{ kb.name }} ({{ kb.kind }})
              </option>
            </select>
          </div>
          <div class="field mb12">
            <label class="field-label">LightRAG 检索模式</label>
            <div class="row wrap" style="gap: 8px">
              <label
                v-for="mode in ['hybrid', 'local', 'global', 'naive']"
                :key="mode"
                class="chip-checkbox"
                :class="{ checked: (node.config.rag_modes || []).includes(mode) }"
              >
                <input
                  type="checkbox"
                  :value="mode"
                  :checked="(node.config.rag_modes || []).includes(mode)"
                  @change="toggleRagMode(mode)"
                />
                <span>{{ mode }}</span>
              </label>
            </div>
          </div>
          <div class="field mb12">
            <div class="row-between">
              <label class="field-label">Top-K 相似度召回数</label>
              <span class="mono font-bold" style="color: var(--c-kb)">{{ node.config.top_k }}</span>
            </div>
            <input
              v-model.number="node.config.top_k"
              type="range"
              class="cap-slider"
              min="1"
              max="20"
              step="1"
            />
          </div>
        </template>

        <!-- 7. 大模型裁判 (LLM Judge) 配置 -->
        <template v-if="node.type === 'llm_judge'">
          <div class="field mb12">
            <label class="field-label">裁判模型 Profile</label>
            <select v-model="node.config.judge_profile_id" class="select">
              <option v-for="p in availableProfiles" :key="p.id" :value="p.id">
                {{ p.name }} ({{ p.protocol }})
              </option>
            </select>
          </div>
          <div class="field mb12">
            <label class="field-label">裁判及格分 (Pass Score, 0-5分)</label>
            <input v-model.number="node.config.pass_score" type="number" class="input num" min="0" max="5" step="0.1" />
          </div>
          <div class="field mb12">
            <label class="field-label">裁判提示词 (Judge Prompt)</label>
            <textarea
              v-model="node.config.judge_prompt"
              class="input textarea"
              rows="3"
            ></textarea>
          </div>
        </template>

        <!-- 8. 质量门禁 (Quality Gate) 配置 -->
        <template v-if="node.type === 'quality_gate'">
          <div class="field mb12">
            <label class="field-label">判定指标</label>
            <select v-model="node.config.metric" class="select">
              <option value="contain_rate">包含准确率 (Contain Rate %)</option>
              <option value="exact_match_rate">精确匹配率 (Exact Match %)</option>
              <option value="judge_score">裁判得分 (Judge Score)</option>
              <option value="hit_rate">RAG 命中文档率 (Hit Rate %)</option>
              <option value="strategy_coverage">用例策略覆盖率 (Coverage %)</option>
            </select>
          </div>
          <div class="grid-2 mb12">
            <div class="field">
              <label class="field-label">判定条件</label>
              <select v-model="node.config.operator" class="select">
                <option value=">=">&gt;= (大于等于)</option>
                <option value=">">&gt; (大于)</option>
                <option value="<=">&lt;= (小于等于)</option>
              </select>
            </div>
            <div class="field">
              <label class="field-label">阈值</label>
              <input v-model.number="node.config.threshold" type="number" class="input num" step="1" />
            </div>
          </div>
          <p class="small tertiary">
            达标走 Pass 端口（触发压测/入库）；不达标走 Fail 端口（告警阻断）。
          </p>
        </template>

        <!-- 9. 共享压测引擎配置 -->
        <template v-if="node.type === 'stress_test'">
          <div class="field mb12">
            <label class="field-label">目标环境 (Env)</label>
            <select v-model="node.config.env" class="select">
              <option value="test">测试环境 (test · 默认免审批)</option>
              <option value="prod">生产环境 (prod · 需二次审批)</option>
            </select>
          </div>
          <div class="grid-2 mb12">
            <div class="field">
              <label class="field-label">起始/目标 QPS</label>
              <input v-model.number="node.config.qps" type="number" class="input num" min="1" max="500" step="5" />
            </div>
            <div class="field">
              <label class="field-label">发压时长 (秒)</label>
              <input v-model.number="node.config.duration_seconds" type="number" class="input num" min="10" max="600" step="10" />
            </div>
          </div>
          <div class="field mb12">
            <label class="field-label">SLA P99 延迟阈值 (ms)</label>
            <input v-model.number="node.config.sla_p99_ms" type="number" class="input num" min="100" max="10000" step="100" />
          </div>
        </template>

        <!-- 10. 评测报告输出配置 -->
        <template v-if="node.type === 'eval_report'">
          <div class="field mb12">
            <label class="field-label">导出与呈现格式</label>
            <select v-model="node.config.format" class="select">
              <option value="all">全量雷达图 + 折线图 + 指标大盘</option>
              <option value="markdown">Markdown 简报</option>
              <option value="json">JSON 原始指标流</option>
            </select>
          </div>
          <div class="field mb12">
            <label class="checkbox-label">
              <input v-model="node.config.auto_share" type="checkbox" />
              <span>生成免登录公开分享链接</span>
            </label>
          </div>
        </template>
      </div>

      <!-- 端口概要说明 -->
      <div class="form-section">
        <div class="section-title">端口与连接</div>
        <div class="ports-summary">
          <div class="small font-bold mb4">输入端口 (Inputs)</div>
          <div v-if="node.inputs.length" class="ports-tag-list">
            <span v-for="p in node.inputs" :key="p.id" class="port-desc-tag in">
              {{ p.label }} <span class="mono">({{ p.type }})</span>
            </span>
          </div>
          <div v-else class="small tertiary">无输入（根触发节点）</div>

          <div class="small font-bold mt8 mb4">输出端口 (Outputs)</div>
          <div v-if="node.outputs.length" class="ports-tag-list">
            <span v-for="p in node.outputs" :key="p.id" class="port-desc-tag out">
              {{ p.label }} <span class="mono">({{ p.type }})</span>
            </span>
          </div>
          <div v-else class="small tertiary">无输出（终点汇总节点）</div>
        </div>
      </div>
    </div>

    <!-- 底部操作条 -->
    <div class="inspector-footer">
      <button class="btn btn-secondary btn-sm" @click="$emit('delete-node', node.id)">
        删除节点
      </button>
      <button class="btn btn-primary btn-sm" @click="$emit('close')">
        完成设置
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '../../api/http'
import type { WorkflowNode } from './workflowTypes'
import type { Profile, Dataset, KnowledgeBase, DispatchWorker } from '../../api/types'

const props = defineProps<{
  node: WorkflowNode | null
}>()

defineEmits<{
  (e: 'close'): void
  (e: 'delete-node', nodeId: string): void
}>()

const availableProfiles = ref<Profile[]>([])
const availableDatasets = ref<Dataset[]>([])
const availableKbs = ref<KnowledgeBase[]>([])
const availableWorkers = ref<DispatchWorker[]>([])

onMounted(async () => {
  try {
    const [profs, dss, kbs, workers] = await Promise.all([
      api.profiles.list().catch(() => []),
      api.datasets.list().catch(() => []),
      api.kb.list().catch(() => []),
      api.dispatch.workers().catch(() => []),
    ])
    availableProfiles.value = profs
    availableDatasets.value = dss
    availableKbs.value = kbs
    availableWorkers.value = workers || []
  } catch (err) {
    console.error('Failed to load asset lists in inspector', err)
  }
})

const categoryLabel = computed(() => {
  if (!props.node) return ''
  switch (props.node.category) {
    case 'trigger':
      return '调度触发'
    case 'eval':
      return '评测引擎'
    case 'data':
      return '数据与用例'
    case 'gate_stress':
      return '门禁与压测'
    case 'output':
      return '汇总输出'
    default:
      return '组件配置'
  }
})

function onDatasetChange() {
  if (!props.node) return
  const ds = availableDatasets.value.find((x) => x.id === props.node?.config.dataset_id)
  if (ds) {
    props.node.config.dataset_name = ds.name
    props.node.config.metric = ds.metric || 'contain'
  }
}

function onKbChange() {
  if (!props.node) return
  const kb = availableKbs.value.find((x) => x.id === props.node?.config.kb_id)
  if (kb) {
    props.node.config.kb_name = kb.name
  }
}

function onWorkerChange() {
  if (!props.node) return
  const w = availableWorkers.value.find((x) => x.id === props.node?.config.worker_id)
  if (w) {
    props.node.config.name = w.name
    props.node.config.caps = w.caps
    props.node.config.weight = w.weight
  }
}

function toggleProfile(profileId: string) {
  if (!props.node) return
  const ids: string[] = props.node.config.profile_ids || []
  const idx = ids.indexOf(profileId)
  if (idx >= 0) {
    ids.splice(idx, 1)
  } else {
    ids.push(profileId)
  }
  props.node.config.profile_ids = [...ids]
}

function toggleRagMode(mode: string) {
  if (!props.node) return
  const modes: string[] = props.node.config.rag_modes || []
  const idx = modes.indexOf(mode)
  if (idx >= 0) {
    modes.splice(idx, 1)
  } else {
    modes.push(mode)
  }
  props.node.config.rag_modes = [...modes]
}
</script>

<style scoped>
.wf-inspector {
  width: 320px;
  background: var(--bg-main);
  border-left: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  z-index: 10;
  box-shadow: -4px 0 16px rgba(0, 0, 0, 0.06);
}

.inspector-header {
  height: 52px;
  padding: 0 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-subtle);
}

.inspector-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.node-icon-box {
  width: 30px;
  height: 30px;
  border-radius: 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  flex-shrink: 0;
}

.inspector-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.inspector-subtitle {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.close-btn {
  background: transparent;
  border: none;
  font-size: 18px;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
}

.close-btn:hover {
  background: var(--row-hover);
  color: var(--text-primary);
}

.inspector-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-section {
  display: flex;
  flex-direction: column;
}

.section-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-tertiary);
  margin-bottom: 8px;
}

.field-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 4px;
  display: block;
}

.input,
.select {
  width: 100%;
  padding: 6px 10px;
  font-size: 12px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  color: var(--text-primary);
  outline: none;
}

.input:focus,
.select:focus {
  border-color: var(--accent-ai);
}

.textarea {
  resize: vertical;
}

.cap-slider {
  width: 100%;
  accent-color: var(--accent-ai);
  cursor: pointer;
}

.profile-chips {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 140px;
  overflow-y: auto;
  padding: 4px;
  background: var(--bg-elevated);
  border-radius: 6px;
}

.profile-checkbox-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.15s;
}

.profile-checkbox-chip:hover {
  background: var(--bg-main);
}

.profile-checkbox-chip.checked {
  background: var(--t-tasks);
  color: var(--c-tasks);
}

.chip-checkbox {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 4px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  font-size: 11px;
  cursor: pointer;
}

.chip-checkbox.checked {
  background: var(--t-kb);
  color: var(--c-kb);
  border-color: var(--t-kb);
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-primary);
  cursor: pointer;
}

.ports-summary {
  background: var(--bg-elevated);
  padding: 10px;
  border-radius: 6px;
}

.ports-tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.port-desc-tag {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
}

.port-desc-tag.in {
  color: var(--accent-ai);
}

.port-desc-tag.out {
  color: var(--accent-success);
}

.inspector-footer {
  height: 48px;
  padding: 0 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
}
</style>
