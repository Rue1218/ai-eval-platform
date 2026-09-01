/** 澄清卡回复拼装：与后端 answers_from_reply 的按行投影对齐。 */

export interface ClarifyReplyQuestion {
  id: string
  question: string
  header?: string
  options: string[]
  multiSelect: boolean
  required: boolean
  type: 'radio' | 'checkbox' | 'text'
}

/** 把 WS payload.questions 收成澄清卡可用结构；非法项丢弃。 */
export function parseClarifyQuestions(raw: unknown): ClarifyReplyQuestion[] | null {
  if (!Array.isArray(raw)) return null
  const items: ClarifyReplyQuestion[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const rec = item as Record<string, unknown>
    const id = String(rec.id || '').trim()
    const question = String(rec.question || '').trim()
    if (!id || !question) continue
    const options = (Array.isArray(rec.options) ? rec.options : [])
      .map((opt) => (typeof opt === 'string' ? opt : String((opt as { label?: string })?.label || '')))
      .map((label) => label.trim())
      .filter(Boolean)
    const typeRaw = String(rec.type || '').trim()
    const type: ClarifyReplyQuestion['type'] =
      typeRaw === 'checkbox' || typeRaw === 'text' || typeRaw === 'radio' ? typeRaw : 'radio'
    items.push({
      id,
      question,
      header: String(rec.header || '').trim() || undefined,
      options,
      multiSelect: rec.multi_select === true || type === 'checkbox',
      required: rec.required !== false,
      type,
    })
  }
  return items.length ? items : null
}

function selectedText(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim()).filter(Boolean).join(', ')
  }
  return String(value || '').trim()
}

/** 按问题顺序拼出上行 answer：一行一题，供后端按行投影为 answers[]。 */
export function composeClarifyReply(
  questions: ClarifyReplyQuestion[],
  selected: Record<string, string | string[]>,
  fallback: string,
): string {
  if (!questions.length) return fallback.trim()
  return questions.map((item) => selectedText(selected[item.id])).join('\n')
}

/** 必答项已选/已填，且整段回复非空时才允许发送。 */
export function canSubmitClarify(
  questions: ClarifyReplyQuestion[],
  selected: Record<string, string | string[]>,
  fallback: string,
): boolean {
  if (!questions.length) return Boolean(fallback.trim())
  const missingRequired = questions.some((item) => item.required && !selectedText(selected[item.id]))
  return !missingRequired && Boolean(composeClarifyReply(questions, selected, fallback).trim())
}
