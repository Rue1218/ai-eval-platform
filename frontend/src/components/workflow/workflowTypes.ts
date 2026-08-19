/**
 * AI 测试与评估平台 — 工作流与编排设计器类型定义 (workflowTypes.ts)
 * 依据：PRD §5.5 调度中心、§5.8 前端信息架构、API V1.3 §3.13 与 §3.8
 */
import type { TaskKind, TaskStatus } from '../../api/types'

/** 节点大类 */
export type WorkflowNodeCategory =
  | 'trigger'      // 触发与调度
  | 'eval'         // 评测引擎
  | 'data'         // 数据与用例输入
  | 'gate_stress'  // 门禁与压测
  | 'output'       // 汇总与输出

/** 节点具体类型枚举 */
export type WorkflowNodeType =
  | 'agent_kernel'     // Agent 调度内核
  | 'worker_target'    // Worker 执行节点
  | 'dataset_source'   // 基准数据集源
  | 'case_gen'         // PRD 智能用例生成
  | 'benchmark_eval'   // 大模型基准评测
  | 'rag_eval'         // RAG 知识库评测
  | 'llm_judge'        // 大模型裁判 (LLM Judge)
  | 'quality_gate'     // 质量门禁 (条件分支)
  | 'stress_test'      // 共享压测引擎
  | 'eval_report'      // 评测报告输出

/** 端口数据类型 */
export type PortDataType =
  | 'any'
  | 'dataset'
  | 'case_set'
  | 'eval_result'
  | 'gate_passed'
  | 'gate_failed'
  | 'worker_signal'
  | 'report'

/** 端口定义 */
export interface PortDef {
  id: string
  label: string
  type: PortDataType
  direction: 'input' | 'output'
  description?: string
  required?: boolean
}

/** 节点实时执行状态 */
export type NodeExecStatus = 'idle' | 'queued' | 'running' | 'succeeded' | 'failed' | 'skipped'

/** 工作流节点定义 */
export interface WorkflowNode {
  id: string
  type: WorkflowNodeType
  category: WorkflowNodeCategory
  name: string
  description: string
  icon: string
  color: string // 节点主题色变量，例如 'var(--c-agent)'
  x: number
  y: number
  inputs: PortDef[]
  outputs: PortDef[]
  config: Record<string, any>
  status: NodeExecStatus
  progress?: number
  statusMessage?: string
  disabled?: boolean
  taskId?: string // 绑定的后端真实任务 ID
}

/** 连线 (Edge / Link) */
export interface WorkflowEdge {
  id: string
  sourceNodeId: string
  sourcePortId: string
  targetNodeId: string
  targetPortId: string
  label?: string
  animated?: boolean
  status?: 'idle' | 'active' | 'success' | 'error'
}

/** 工作流元数据与图结构 */
export interface WorkflowGraph {
  id: string
  name: string
  description: string
  version: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  created_at?: string
  updated_at?: string
}

/** 节点元数据定义（用于物料库注册） */
export interface NodeMeta {
  type: WorkflowNodeType
  category: WorkflowNodeCategory
  name: string
  description: string
  icon: string
  color: string
  defaultInputs: PortDef[]
  defaultOutputs: PortDef[]
  defaultConfig: Record<string, any>
}

/** 预置工作流模板 */
export interface WorkflowTemplate {
  id: string
  name: string
  category: 'benchmark' | 'rag' | 'cases' | 'agent'
  description: string
  icon: string
  badgeText: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

/** DAG 拓扑校验结果 */
export interface WorkflowValidationResult {
  valid: boolean
  errors: Array<{
    nodeId?: string
    edgeId?: string
    message: string
  }>
  warnings: Array<{
    nodeId?: string
    message: string
  }>
}

/** 编排执行日志条目 */
export interface WorkflowExecutionLog {
  time: string
  nodeId: string
  nodeName: string
  level: 'info' | 'warn' | 'error' | 'success'
  message: string
}
