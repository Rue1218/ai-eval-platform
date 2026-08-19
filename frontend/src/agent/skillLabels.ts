/**
 * 技能徽标文案（开发说明书 §16.7 冻结）。
 * 写在 slash 注册表旁；思考卡头展示，不单开事件。
 */
export const SKILL_LABELS: Record<string, string> = {
  'skill-benchmark': '技能 · 基准对比',
  'skill-rag': '技能 · RAG 评估',
  'skill-testcase': '技能 · 用例生成',
  'skill-stress': '技能 · 先评后压',
}

export function skillLabel(skillId?: string | null): string {
  if (!skillId) return ''
  return SKILL_LABELS[skillId] || ''
}
