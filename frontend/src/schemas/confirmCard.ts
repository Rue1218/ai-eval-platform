/**
 * AI 测试与评估平台 — 任务规格 TaskSpec 校验与默认值构建
 * 依据：PRD 5.1.2、F-AGT-04/07、设计规范 §6
 */
import type { TaskSpec, TaskKind, StressConfig, RunConfig } from '../api/types'

export interface ValidationResult {
  valid: boolean
  errors: Record<string, string>
}

export function getDefaultRunConfig(): RunConfig {
  return {
    sample_size: 1000,
    concurrency: 4,
    timeout_s: 60,
    retry: 1,
    temperature: 0,
    max_tokens: 1024,
    system_prompt: '',
    k: 5,
    use_judge: false,
  }
}

export function getDefaultStressConfig(): StressConfig {
  return {
    env: 'test',
    qps: 10,
    duration_s: 120,
    sla_p99_ms: undefined,
  }
}

export function createDefaultTaskSpec(kind: TaskKind = 'benchmark'): TaskSpec {
  return {
    kind,
    profile_ids: [],
    dataset_id: undefined,
    kb_id: undefined,
    gold_qa_id: undefined,
    rag_mode: ['hybrid'],
    case_source: { text: '' },
    run: getDefaultRunConfig(),
    with_stress: false,
    stress: getDefaultStressConfig(),
  }
}

export function validateTaskSpec(spec: TaskSpec): ValidationResult {
  const errors: Record<string, string> = {}

  if (!spec.kind) {
    errors.kind = '请选择任务类型'
    return { valid: false, errors }
  }

  // 1. 基准评测
  if (spec.kind === 'benchmark') {
    if (!spec.profile_ids || spec.profile_ids.length === 0) {
      errors.profile_ids = '请至少选择 1 个被测协议档'
    } else if (spec.profile_ids.length > 5) {
      errors.profile_ids = '被测协议档不能超过 5 个'
    }
    if (!spec.dataset_id) {
      errors.dataset_id = '请选择评测数据集'
    }
  }

  // 2. RAG 评测
  if (spec.kind === 'rag') {
    if (!spec.kb_id) {
      errors.kb_id = '请选择知识库'
    }
    if (!spec.gold_qa_id) {
      errors.gold_qa_id = '请选择黄金 QA 数据集'
    }
    if (!spec.rag_mode || spec.rag_mode.length === 0) {
      errors.rag_mode = '请至少选择 1 种检索模式'
    }
  }

  // 3. 用例生成
  if (spec.kind === 'testcase') {
    const hasFile = !!spec.case_source?.file_id
    const hasText = !!spec.case_source?.text && spec.case_source.text.trim().length > 0
    if (!hasFile && !hasText) {
      errors.case_source = '请上传需求文档或输入需求文本'
    }
  }

  // 4. 压测部分校验（若勾选了 with_stress 或直接为 stress 任务）
  if (spec.with_stress || spec.kind === 'stress') {
    if (!spec.stress) {
      errors.stress = '请配置压测参数'
    } else {
      if (!spec.stress.qps || spec.stress.qps <= 0) {
        errors['stress.qps'] = 'QPS 必须大于 0'
      } else if (spec.stress.qps > 1000) {
        errors['stress.qps'] = 'QPS 超出单机发压上限 1000'
      }
      if (!spec.stress.duration_s || spec.stress.duration_s < 10) {
        errors['stress.duration_s'] = '压测时长至少 10 秒'
      } else if (spec.stress.duration_s > 3600) {
        errors['stress.duration_s'] = '压测时长不能超过 1 小时'
      }
    }
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
  }
}
