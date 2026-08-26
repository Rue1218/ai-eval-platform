/**
 * 技能徽标文案与一句话 summary（对齐 M10 SKILL_CATALOG / SkillHint）。
 * 写在 slash 注册表旁；思考卡头与 PlanCard 展示，不单开事件。
 */

export const SKILL_LABELS: Record<string, string> = {
  'skill-benchmark': '技能 · 基准对比',
  'skill-rag': '技能 · RAG 评估',
  'skill-testcase': '技能 · 用例生成',
  'skill-stress': '技能 · 先评后压',
}

/** 与后端 `harness/skills/registry.py` SKILL_CATALOG 一句话描述对齐 */
export const SKILL_SUMMARIES: Record<string, string> = {
  'skill-benchmark': '执行大模型基准评测',
  'skill-rag': '执行知识库评测',
  'skill-testcase': '生成评测测试用例',
  'skill-stress': '执行共享压测',
}

export function skillLabel(skillId?: string | null): string {
  if (!skillId) return ''
  return SKILL_LABELS[skillId] || ''
}

export function skillSummary(skillId?: string | null): string {
  if (!skillId) return ''
  return SKILL_SUMMARIES[skillId] || ''
}
