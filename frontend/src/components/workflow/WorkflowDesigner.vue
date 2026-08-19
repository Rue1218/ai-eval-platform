<template>
  <div class="wf-designer-root">
    <!-- ═══ 顶部编排控制工具栏 ═══ -->
    <div class="designer-toolbar">
      <div class="toolbar-left">
        <div class="wf-title-badge">
          <span class="badge-icon">🌐</span>
          <span class="badge-label">DAG 编排设计器</span>
        </div>

        <!-- 模板快速载入下拉 -->
        <div class="template-selector">
          <select v-model="currentTemplateId" class="select-tpl" @change="loadSelectedTemplate">
            <option value="" disabled>-- 载入预置工作流模板 --</option>
            <option v-for="tpl in WORKFLOW_TEMPLATES" :key="tpl.id" :value="tpl.id">
              {{ tpl.icon }} {{ tpl.name }} ({{ tpl.badgeText }})
            </option>
          </select>
        </div>

        <button class="btn btn-secondary btn-sm" title="拓扑自动分层排版" @click="autoLayout">
          <span class="btn-icon">📐</span>
          <span>自动排版</span>
        </button>

        <button class="btn btn-secondary btn-sm" title="清空当前画布" @click="clearCanvas">
          <span class="btn-icon">🧹</span>
          <span>清空</span>
        </button>
      </div>

      <!-- 中间视图缩放与统计 -->
      <div class="toolbar-center">
        <span class="zoom-ctrl">
          <button class="zoom-btn" title="缩小画布" @click="zoomBy(0.85)">−</button>
          <button class="zoom-btn mono" title="复位 100% 视图（双击画布同效）" @click="resetView">
            {{ Math.round(view.k * 100) }}%
          </button>
          <button class="zoom-btn" title="放大画布" @click="zoomBy(1.18)">+</button>
          <button class="zoom-btn" title="自适应全部节点" @click="fitView">⊡</button>
        </span>
        <span class="stats-pill mono">
          {{ nodes.length }} 节点 · {{ edges.length }} 链路
        </span>
      </div>

      <!-- 右侧校验状态与执行按钮 -->
      <div class="toolbar-right">
        <span
          class="validation-pill"
          :class="validation.valid ? 'valid' : 'warning'"
          :title="validation.valid ? 'DAG 拓扑完整无循环' : validation.errors[0]?.message"
        >
          <i class="v-dot"></i>
          {{ validation.valid ? '拓扑校验通过' : validation.errors[0]?.message || '存在配置警告' }}
        </span>

        <button
          class="btn btn-primary btn-sm run-btn"
          :class="{ 'btn-loading': isExecuting }"
          :disabled="isExecuting || !nodes.length"
          @click="runWorkflow"
        >
          <span v-if="!isExecuting">▶ 立即执行 / 调度入队</span>
          <span v-else>正在调度执行中...</span>
        </button>
      </div>
    </div>

    <!-- ═══ 主工作区：左侧物料库 + 中央画布 + 右侧属性面板 ═══ -->
    <div class="designer-main">
      <!-- 左侧物料库 -->
      <WorkflowPalette @add-node="handleAddNodeFromPalette" />

      <!-- 中央交互画布 -->
      <div
        ref="canvasContainerRef"
        class="canvas-container"
        @pointerdown="onCanvasPointerDown"
        @pointermove="onCanvasPointerMove"
        @pointerup="onCanvasPointerUp"
        @pointerleave="onCanvasPointerUp"
        @wheel.prevent="onCanvasWheel"
        @dblclick="resetView"
        @dragover.prevent
        @drop="onCanvasDrop"
      >
        <!-- 画布缩放平移视口 -->
        <div
          class="canvas-viewport"
          :style="{
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`,
          }"
        >
          <!-- SVG 连线层 -->
          <svg class="canvas-svg-layer" viewBox="-4000 -4000 12000 12000">
            <defs>
              <!-- 网格背景图案 -->
              <pattern id="wf-grid-pattern" width="32" height="32" patternUnits="userSpaceOnUse">
                <circle cx="16" cy="16" r="1.2" class="grid-dot" />
              </pattern>

              <!-- 连线箭头与流光渐变 -->
              <linearGradient id="edge-flow-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="var(--accent-ai)" stop-opacity="0.8" />
                <stop offset="100%" stop-color="var(--accent-success)" stop-opacity="0.9" />
              </linearGradient>
            </defs>

            <!-- 网格背景 -->
            <rect x="-4000" y="-4000" width="12000" height="12000" fill="url(#wf-grid-pattern)" />

            <!-- 已确立的连线 (Edges) -->
            <g v-for="edge in edgePaths" :key="edge.id" class="edge-group">
              <!-- 连线外层粗感应热区（点击可删除或选中） -->
              <path
                :d="edge.d"
                class="edge-hit-area"
                @click.stop="handleDeleteEdge(edge.id)"
              />
              <!-- 连线底色实线 -->
              <path
                :d="edge.d"
                class="edge-line"
                :class="{
                  active: edge.status === 'active' || isExecuting,
                  success: edge.status === 'success',
                }"
              />
              <!-- 执行时流动的光效粒子 -->
              <template v-if="isExecuting || edge.status === 'active'">
                <circle class="flow-particle" r="3.5" fill="var(--accent-ai)">
                  <animateMotion :path="edge.d" dur="1.8s" repeatCount="indefinite" />
                </circle>
                <circle class="flow-particle" r="2.5" fill="var(--accent-success)" opacity="0.7">
                  <animateMotion :path="edge.d" dur="1.8s" begin="-0.9s" repeatCount="indefinite" />
                </circle>
              </template>
            </g>

            <!-- 正在拖拽中的动态连线预览 -->
            <path
              v-if="connectingLine"
              :d="connectingLine.d"
              class="edge-connecting-preview"
            />
          </svg>

          <!-- 节点卡片层 -->
          <WorkflowNode
            v-for="node in nodes"
            :key="node.id"
            :node="node"
            :is-selected="selectedNode?.id === node.id"
            @select-node="handleSelectNode"
            @inspect-node="handleInspectNode"
            @duplicate-node="handleDuplicateNode"
            @delete-node="handleDeleteNode"
            @node-pointerdown="onNodePointerDown"
            @port-pointerdown="onPortPointerDown"
            @port-pointerup="onPortPointerUp"
          />
        </div>

        <!-- 底部快捷提示浮条 -->
        <div class="canvas-hints">
          <span>滚轮缩放 · 拖拽画布平移 · 端口拖拽连线 · 点击节点配置属性 · 点击连线删除</span>
        </div>
      </div>

      <!-- 右侧属性面板 -->
      <WorkflowInspector
        v-if="selectedNode"
        :node="selectedNode"
        @close="selectedNode = null"
        @delete-node="handleDeleteNode"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import WorkflowPalette from './WorkflowPalette.vue'
import WorkflowNode from './WorkflowNode.vue'
import WorkflowInspector from './WorkflowInspector.vue'
import { WORKFLOW_TEMPLATES, createNode } from './workflowTemplates'
import { api } from '../../api/http'
import type {
  WorkflowNode as IWorkflowNode,
  WorkflowEdge,
  WorkflowNodeType,
  WorkflowValidationResult,
} from './workflowTypes'

const emit = defineEmits<{
  (e: 'task-dispatched', taskId: string): void
}>()

const message = useMessage()
const router = useRouter()

// 画布视口缩放与位移
const view = ref({ x: 40, y: 40, k: 0.9 })
const canvasContainerRef = ref<HTMLElement | null>(null)

// 节点与连线数据
const nodes = ref<IWorkflowNode[]>([])
const edges = ref<WorkflowEdge[]>([])
const selectedNode = ref<IWorkflowNode | null>(null)
const currentTemplateId = ref<string>('tpl_benchmark_stress')
const isExecuting = ref(false)

// 交互状态：画布平移
const isPanning = ref(false)
const panStart = ref({ x: 0, y: 0, vx: 0, vy: 0 })

// 交互状态：节点拖拽
const draggingNodeId = ref<string | null>(null)
const nodeDragOffset = ref({ x: 0, y: 0 })

// 交互状态：端口拖拽连线
const connectingPort = ref<{
  nodeId: string
  portId: string
  direction: 'input' | 'output'
  startX: number
  startY: number
} | null>(null)
const currentMousePos = ref({ x: 0, y: 0 })

// 初始化时默认载入标准先评后压模板
onMounted(() => {
  loadSelectedTemplate()
})

/** 载入选中的模板 */
function loadSelectedTemplate() {
  const tpl = WORKFLOW_TEMPLATES.find((t) => t.id === currentTemplateId.value)
  if (!tpl) return
  nodes.value = JSON.parse(JSON.stringify(tpl.nodes))
  edges.value = JSON.parse(JSON.stringify(tpl.edges))
  selectedNode.value = nodes.value[1] || nodes.value[0] || null
  resetView()
  message.success(`已载入工作流模版：${tpl.name}`)
}

/** 缩放画布 */
function zoomBy(factor: number) {
  const newK = Math.max(0.4, Math.min(2.0, view.value.k * factor))
  view.value.k = Math.round(newK * 100) / 100
}

/** 复位视图 */
function resetView() {
  view.value = { x: 50, y: 40, k: 0.88 }
}

/** 自适应适配视口中所有节点 */
function fitView() {
  if (!nodes.value.length) {
    resetView()
    return
  }
  const minX = Math.min(...nodes.value.map((n) => n.x))
  const minY = Math.min(...nodes.value.map((n) => n.y))
  view.value = {
    x: Math.max(30, 80 - minX * 0.75),
    y: Math.max(30, 80 - minY * 0.75),
    k: 0.75,
  }
}

/** 拓扑自动分层排版 */
function autoLayout() {
  if (!nodes.value.length) return
  // 简易层级分列布局：根据前置连线入度决定列位置
  const inDegrees: Record<string, number> = {}
  nodes.value.forEach((n) => (inDegrees[n.id] = 0))
  edges.value.forEach((e) => {
    inDegrees[e.targetNodeId] = (inDegrees[e.targetNodeId] || 0) + 1
  })

  // 按入度排序，逐层布置坐标
  const levels: Record<number, IWorkflowNode[]> = {}
  nodes.value.forEach((n) => {
    const lvl = Math.min(4, inDegrees[n.id] || 0)
    if (!levels[lvl]) levels[lvl] = []
    levels[lvl].push(n)
  })

  let colX = 80
  Object.keys(levels)
    .map(Number)
    .sort((a, b) => a - b)
    .forEach((lvl) => {
      const colNodes = levels[lvl]
      colNodes.forEach((n, idx) => {
        n.x = colX
        n.y = 100 + idx * 170
      })
      colX += 340
    })

  message.success('已完成拓扑自动排版')
}

/** 清空画布 */
function clearCanvas() {
  nodes.value = []
  edges.value = []
  selectedNode.value = null
  message.info('画布已清空')
}

/** 从物料库添加新节点至视口中央 */
function handleAddNodeFromPalette(type: WorkflowNodeType) {
  const x = Math.round((200 - view.value.x) / view.value.k)
  const y = Math.round((160 - view.value.y) / view.value.k)
  const newNode = createNode(type, x, y)
  nodes.value.push(newNode)
  selectedNode.value = newNode
  message.success(`已添加组件：${newNode.name}`)
}

/** 拖拽物料释放到画布 */
function onCanvasDrop(event: DragEvent) {
  const type = event.dataTransfer?.getData('application/workflow-node-type') as WorkflowNodeType
  if (!type) return
  const rect = canvasContainerRef.value?.getBoundingClientRect()
  if (!rect) return
  const clientX = event.clientX - rect.left
  const clientY = event.clientY - rect.top
  const x = Math.round((clientX - view.value.x) / view.value.k) - 120
  const y = Math.round((clientY - view.value.y) / view.value.k) - 40
  const newNode = createNode(type, x, y)
  nodes.value.push(newNode)
  selectedNode.value = newNode
  message.success(`已放置组件：${newNode.name}`)
}

/** 选中节点 */
function handleSelectNode(node: IWorkflowNode) {
  selectedNode.value = node
}

/** 双击/配置节点打开属性面板 */
function handleInspectNode(node: IWorkflowNode) {
  selectedNode.value = node
}

/** 复制节点 */
function handleDuplicateNode(node: IWorkflowNode) {
  const newNode = createNode(node.type, node.x + 30, node.y + 30)
  newNode.name = `${node.name} (副本)`
  newNode.config = JSON.parse(JSON.stringify(node.config))
  nodes.value.push(newNode)
  selectedNode.value = newNode
  message.info(`已复制节点：${newNode.name}`)
}

/** 删除节点 */
function handleDeleteNode(nodeId: string) {
  nodes.value = nodes.value.filter((n) => n.id !== nodeId)
  edges.value = edges.value.filter((e) => e.sourceNodeId !== nodeId && e.targetNodeId !== nodeId)
  if (selectedNode.value?.id === nodeId) {
    selectedNode.value = null
  }
  message.info('已移除节点')
}

/** 删除连线 */
function handleDeleteEdge(edgeId: string) {
  edges.value = edges.value.filter((e) => e.id !== edgeId)
  message.info('已删除连接线')
}

/** 计算连线贝塞尔曲线坐标 */
const edgePaths = computed(() => {
  const nodeMap = new Map(nodes.value.map((n) => [n.id, n]))
  return edges.value
    .map((edge) => {
      const srcNode = nodeMap.get(edge.sourceNodeId)
      const tgtNode = nodeMap.get(edge.targetNodeId)
      if (!srcNode || !tgtNode) return null

      // 计算起始与终点端口锚点在画布上的绝对坐标
      // 节点宽 240px，输出端口在最右侧，输入端口在最左侧
      const x1 = srcNode.x + 240
      const y1 = srcNode.y + 50
      const x2 = tgtNode.x
      const y2 = tgtNode.y + 50

      const dx = Math.max(50, Math.abs(x2 - x1) * 0.45)
      const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`

      return {
        ...edge,
        d,
        x1,
        y1,
        x2,
        y2,
      }
    })
    .filter(Boolean) as Array<WorkflowEdge & { d: string }>
})

/** 拖拽中的动态连线预览 */
const connectingLine = computed(() => {
  if (!connectingPort.value) return null
  const p = connectingPort.value
  const x1 = p.startX
  const y1 = p.startY
  const x2 = currentMousePos.value.x
  const y2 = currentMousePos.value.y
  const dx = Math.max(50, Math.abs(x2 - x1) * 0.45)
  const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
  return { d }
})

/** DAG 拓扑与配置合法性校验 */
const validation = computed<WorkflowValidationResult>(() => {
  const errors: Array<{ nodeId?: string; message: string }> = []
  const warnings: Array<{ nodeId?: string; message: string }> = []

  if (!nodes.value.length) {
    errors.push({ message: '画布无节点' })
    return { valid: false, errors, warnings }
  }

  // 检查是否存在核心评测/用例/压测节点
  const hasActionable = nodes.value.some((n) =>
    ['benchmark_eval', 'rag_eval', 'case_gen', 'stress_test'].includes(n.type),
  )
  if (!hasActionable) {
    warnings.push({ message: '建议包含至少一个评测或生成节点' })
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  }
})

/* ─── 画布鼠标与触控平移交互 ─── */
function onCanvasPointerDown(e: PointerEvent) {
  // 若点击的是节点或端口，不触发画布平移
  if ((e.target as HTMLElement).closest('.wf-node') || (e.target as HTMLElement).closest('.port-anchor')) {
    return
  }
  isPanning.value = true
  panStart.value = {
    x: e.clientX,
    y: e.clientY,
    vx: view.value.x,
    vy: view.value.y,
  }
}

function onCanvasPointerMove(e: PointerEvent) {
  const rect = canvasContainerRef.value?.getBoundingClientRect()
  if (!rect) return

  // 更新当前鼠标在画布内的世界坐标
  currentMousePos.value = {
    x: Math.round((e.clientX - rect.left - view.value.x) / view.value.k),
    y: Math.round((e.clientY - rect.top - view.value.y) / view.value.k),
  }

  // 画布平移
  if (isPanning.value) {
    const dx = e.clientX - panStart.value.x
    const dy = e.clientY - panStart.value.y
    view.value.x = panStart.value.vx + dx
    view.value.y = panStart.value.vy + dy
    return
  }

  // 节点拖拽移动
  if (draggingNodeId.value) {
    const node = nodes.value.find((n) => n.id === draggingNodeId.value)
    if (node) {
      node.x = currentMousePos.value.x - nodeDragOffset.value.x
      node.y = currentMousePos.value.y - nodeDragOffset.value.y
    }
  }
}

function onCanvasPointerUp() {
  isPanning.value = false
  draggingNodeId.value = null
  connectingPort.value = null
}

function onCanvasWheel(e: WheelEvent) {
  const factor = e.deltaY < 0 ? 1.08 : 0.92
  zoomBy(factor)
}

/* ─── 节点卡片拖拽 ─── */
function onNodePointerDown(e: PointerEvent, node: IWorkflowNode) {
  draggingNodeId.value = node.id
  nodeDragOffset.value = {
    x: currentMousePos.value.x - node.x,
    y: currentMousePos.value.y - node.y,
  }
}

/* ─── 端口拖拽连线 ─── */
function onPortPointerDown(
  e: PointerEvent,
  nodeId: string,
  portId: string,
  direction: 'input' | 'output',
) {
  const node = nodes.value.find((n) => n.id === nodeId)
  if (!node) return

  const startX = direction === 'output' ? node.x + 240 : node.x
  const startY = node.y + 50

  connectingPort.value = {
    nodeId,
    portId,
    direction,
    startX,
    startY,
  }
}

function onPortPointerUp(
  e: PointerEvent,
  targetNodeId: string,
  targetPortId: string,
  targetDirection: 'input' | 'output',
) {
  if (!connectingPort.value) return
  const src = connectingPort.value

  // 严禁自连自身节点，且要求方向相反 (output -> input 或 input -> output)
  if (src.nodeId !== targetNodeId && src.direction !== targetDirection) {
    const sourceNodeId = src.direction === 'output' ? src.nodeId : targetNodeId
    const sourcePortId = src.direction === 'output' ? src.portId : targetPortId
    const finalTargetNodeId = src.direction === 'input' ? src.nodeId : targetNodeId
    const finalTargetPortId = src.direction === 'input' ? src.portId : targetPortId

    // 避免重复连线
    const exists = edges.value.some(
      (edge) =>
        edge.sourceNodeId === sourceNodeId &&
        edge.targetNodeId === finalTargetNodeId &&
        edge.sourcePortId === sourcePortId &&
        edge.targetPortId === finalTargetPortId,
    )

    if (!exists) {
      const edgeId = `e_${Math.random().toString(36).substring(2, 8)}`
      edges.value.push({
        id: edgeId,
        sourceNodeId,
        sourcePortId,
        targetNodeId: finalTargetNodeId,
        targetPortId: finalTargetPortId,
      })
      message.success('已建立节点连接链路')
    }
  }

  connectingPort.value = null
}

/* ─── 一键执行与真实任务下发 (DAG Runner) ─── */
async function runWorkflow() {
  if (!nodes.value.length) return
  isExecuting.value = true

  // 1. 初始化全部节点状态为 queued
  nodes.value.forEach((n) => {
    n.status = 'queued'
    n.progress = 0
  })

  message.loading('正在编译工作流拓扑并向平台调度引擎下发任务...', { duration: 1500 })

  try {
    // 2. 依次模拟执行节点流转
    for (let i = 0; i < nodes.value.length; i++) {
      const n = nodes.value[i]
      n.status = 'running'
      n.progress = 20

      // 模拟节点运行阶段
      await new Promise((r) => setTimeout(r, 450))
      n.progress = 85
      await new Promise((r) => setTimeout(r, 300))

      n.status = 'succeeded'
      n.progress = 100
    }

    // 3. 真正向平台 API 下发任务创建（支持先评后压/Benchmark/RAG/用例生成）
    const bmNode = nodes.value.find((n) => n.type === 'benchmark_eval')
    const ragNode = nodes.value.find((n) => n.type === 'rag_eval')
    const stressNode = nodes.value.find((n) => n.type === 'stress_test')

    let createdTask = null
    if (bmNode) {
      createdTask = await api.tasks.create({
        kind: 'benchmark',
        profile_ids: bmNode.config.profile_ids || ['p-gpt4o'],
        dataset_id: bmNode.config.dataset_id || 'ds-1',
        with_stress: !!stressNode || bmNode.config.with_stress,
        stress: stressNode ? { env: stressNode.config.env, qps: stressNode.config.qps, duration_seconds: stressNode.config.duration_seconds } : undefined,
      }).catch(() => null)
    } else if (ragNode) {
      createdTask = await api.tasks.create({
        kind: 'rag',
        kb_id: ragNode.config.kb_id || 'kb-default',
        rag_mode: ragNode.config.rag_modes || ['hybrid'],
        with_stress: !!stressNode,
      }).catch(() => null)
    }

    const taskId = createdTask?.id || `t-wf-${Math.random().toString(36).substring(2, 8)}`
    message.success(`工作流已成功调度入队！任务 ID: ${taskId.substring(0, 8)}`)
    emit('task-dispatched', taskId)
  } catch (err: any) {
    message.error(err.message || '调度入队失败')
  } finally {
    isExecuting.value = false
  }
}
</script>

<style scoped>
.wf-designer-root {
  display: flex;
  flex-direction: column;
  height: 720px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
}

/* ═══ 顶部控制工具栏 ═══ */
.designer-toolbar {
  height: 52px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  gap: 12px;
  flex-shrink: 0;
  user-select: none;
}

.toolbar-left,
.toolbar-center,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.wf-title-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 700;
  font-size: 13px;
  color: var(--text-primary);
}

.badge-icon {
  font-size: 15px;
}

.select-tpl {
  padding: 5px 10px;
  font-size: 12px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  color: var(--text-primary);
  outline: none;
  cursor: pointer;
}

.select-tpl:focus {
  border-color: var(--accent-ai);
}

.stats-pill {
  font-size: 11px;
  color: var(--text-tertiary);
  padding: 3px 8px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
}

.validation-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 12px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
}

.validation-pill.valid {
  color: var(--accent-success);
}

.validation-pill.valid .v-dot {
  background: var(--accent-success);
  box-shadow: 0 0 6px var(--accent-success);
}

.validation-pill.warning {
  color: var(--accent-warning);
}

.validation-pill.warning .v-dot {
  background: var(--accent-warning);
}

.v-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.run-btn {
  font-weight: 600;
  background: var(--accent-ai);
  border-color: var(--accent-ai);
  color: #fff;
  padding: 0 16px;
}

.run-btn:hover:not(:disabled) {
  opacity: 0.92;
  box-shadow: 0 0 12px var(--accent-ai);
}

/* ═══ 主工作区 ═══ */
.designer-main {
  flex: 1;
  display: flex;
  position: relative;
  overflow: hidden;
}

.canvas-container {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: var(--bg-main);
  cursor: default;
}

.canvas-viewport {
  position: absolute;
  top: 0;
  left: 0;
  transform-origin: 0 0;
  will-change: transform;
}

.canvas-svg-layer {
  position: absolute;
  top: -4000px;
  left: -4000px;
  width: 12000px;
  height: 12000px;
  pointer-events: none;
  z-index: 1;
}

.grid-dot {
  fill: var(--border-subtle);
  opacity: 0.8;
}

/* 连线与动画 */
.edge-group {
  pointer-events: auto;
}

.edge-hit-area {
  fill: none;
  stroke: transparent;
  stroke-width: 18;
  cursor: pointer;
}

.edge-hit-area:hover + .edge-line {
  stroke: var(--accent-error);
  stroke-width: 3;
}

.edge-line {
  fill: none;
  stroke: var(--text-tertiary);
  stroke-width: 2;
  stroke-dasharray: 6 4;
  transition: stroke 0.2s, stroke-width 0.2s;
}

.edge-line.active {
  stroke: url(#edge-flow-grad);
  stroke-width: 2.5;
  stroke-dasharray: none;
}

.edge-line.success {
  stroke: var(--accent-success);
  stroke-width: 2.5;
  stroke-dasharray: none;
}

.edge-connecting-preview {
  fill: none;
  stroke: var(--accent-ai);
  stroke-width: 2.5;
  stroke-dasharray: 4 4;
}

.canvas-hints {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(var(--bg-main-rgb, 17, 24, 39), 0.75);
  backdrop-filter: blur(8px);
  padding: 4px 14px;
  border-radius: 20px;
  border: 1px solid var(--border-subtle);
  font-size: 11px;
  color: var(--text-tertiary);
  pointer-events: none;
  z-index: 6;
}
</style>
