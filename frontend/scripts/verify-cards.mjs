/** 看板 / 澄清卡投影冒烟：不启浏览器也能核对字段与发送门禁。 */
import {
  canSubmitClarify,
  composeClarifyReply,
  parseClarifyQuestions,
} from '../src/utils/clarifyReply.ts'
import { buildToolInputFields, buildToolOutputFields } from '../src/utils/toolIo.ts'

const questions = parseClarifyQuestions([
  {
    id: 'dataset',
    question: '用哪个数据集？',
    options: [{ label: 'MMLU' }, { label: 'C-Eval' }],
  },
  { id: 'note', question: '补充说明', type: 'text', required: false },
])
if (!questions || questions.length !== 2) throw new Error('questions 解析失败')
if (canSubmitClarify(questions, {}, '')) throw new Error('必答未选时不应发送')
if (!canSubmitClarify(questions, { dataset: 'MMLU' }, '')) throw new Error('点选项后应可发送')
const reply = composeClarifyReply(questions, { dataset: 'MMLU', note: '先跑 10 条' }, '')
if (reply !== 'MMLU\n先跑 10 条') throw new Error(`回复拼装错误: ${reply}`)
const skipped = composeClarifyReply(questions, { note: '只要第二题' }, '')
if (skipped !== '\n只要第二题') throw new Error(`空行应对齐到第二题: ${JSON.stringify(skipped)}`)

const input = buildToolInputFields('TaskCreate', { title: '拆解评测', description: '先选数据集' })
if (!input.some((field) => field.name === 'subject' && field.value === '拆解评测')) {
  throw new Error('TaskCreate 入参未归一 subject')
}

const output = buildToolOutputFields(
  'TaskCreate',
  {
    id: 'task_abc',
    status: 'success',
    task: { id: 'task_abc', subject: '拆解评测', status: 'pending' },
  },
  {},
  'ok',
)
if (!output.some((field) => field.name === 'task.id' && field.value === 'task_abc')) {
  throw new Error('TaskCreate 输出缺少 task.id')
}

console.log('clarify/task card projection ok')
