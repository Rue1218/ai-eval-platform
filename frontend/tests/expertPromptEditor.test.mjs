import assert from 'node:assert/strict'
import test from 'node:test'
import { useExpertPromptEditor } from '../src/composables/useExpertPromptEditor.ts'

/** 可控异步请求用于确定性模拟乱序和延迟，不依赖定时器。 */
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

/** 构造不同专家的独立提示词快照。 */
function doc(id, content = '内置内容') {
  return { expert_id: id, name: id, content, builtin_content: '内置内容', revision: '1234567890abcdef', overridden: content !== '内置内容' }
}

test('切换专家后旧成功或失败响应都不能覆盖新草稿', async () => {
  for (const fail of [false, true]) {
    const old = deferred()
    const editor = useExpertPromptEditor({ getAgentExpertPrompt: id => id === 'old' ? old.promise : Promise.resolve(doc(id)) })
    const loading = editor.load('old')
    await editor.load('new')
    editor.draft.value = '新专家草稿'
    if (fail) old.reject(new Error('旧请求失败'))
    else old.resolve(doc('old'))
    await loading
    assert.equal(editor.document.value.expert_id, 'new')
    assert.equal(editor.draft.value, '新专家草稿')
    assert.equal(editor.loadError.value, '')
  }
})

test('刷新清除旧修订且加载中不能保存，关闭后请求失效', async () => {
  const pending = deferred()
  const editor = useExpertPromptEditor({ getAgentExpertPrompt: id => id === 'first' ? Promise.resolve(doc(id)) : pending.promise })
  await editor.load('first')
  editor.draft.value = '草稿'
  const loading = editor.load('next')
  assert.equal(editor.document.value, null)
  assert.equal(editor.canSave.value, false)
  assert.equal(await editor.save(), null)
  editor.reset()
  pending.resolve(doc('next'))
  await loading
  assert.equal(editor.document.value, null)
  assert.equal(editor.loading.value, false)
})

test('保存使用文档 ID 与修订，重复提交被拒绝，新输入不被响应覆盖', async () => {
  const pending = deferred()
  const calls = []
  const editor = useExpertPromptEditor({
    getAgentExpertPrompt: async id => doc(id),
    updateAgentExpertPrompt: (id, body) => { calls.push([id, body]); return pending.promise },
  })
  await editor.load('expert')
  assert.equal(editor.canSave.value, false)
  editor.draft.value = '第一次修改'
  const saving = editor.save()
  assert.equal(await editor.save(), null)
  editor.draft.value = '保存期间的新修改'
  pending.resolve({ ...doc('expert', '第一次修改'), revision: 'abcdef1234567890' })
  await saving
  assert.deepEqual(calls, [['expert', { content: '第一次修改', expected_revision: '1234567890abcdef' }]])
  assert.equal(editor.draft.value, '保存期间的新修改')
  assert.equal(editor.document.value.revision, 'abcdef1234567890')
  assert.equal(editor.canSave.value, true)
})

test('保存失败保留草稿，恢复内置不自动写入', async () => {
  let calls = 0
  const editor = useExpertPromptEditor({
    getAgentExpertPrompt: async id => doc(id, '当前定制'),
    updateAgentExpertPrompt: async () => { calls += 1; throw new Error('修订冲突') },
  })
  await editor.load('expert')
  editor.restoreBuiltin()
  assert.equal(calls, 0)
  assert.equal(editor.draft.value, '内置内容')
  assert.equal(editor.canSave.value, true)
  await assert.rejects(editor.save(), /修订冲突/)
  assert.equal(editor.draft.value, '内置内容')
  assert.equal(editor.document.value.content, '当前定制')
  assert.equal(editor.saving.value, false)
  editor.draft.value = '  \r\n '
  assert.equal(editor.canSave.value, false)
})

test('旧保存完成不能回写到后来打开的专家', async () => {
  const pending = deferred()
  const editor = useExpertPromptEditor({
    getAgentExpertPrompt: async id => doc(id),
    updateAgentExpertPrompt: () => pending.promise,
  })
  await editor.load('old')
  editor.draft.value = '旧专家修改'
  const saving = editor.save()
  await editor.load('new')
  pending.resolve(doc('old', '旧专家修改'))
  await saving
  assert.equal(editor.document.value.expert_id, 'new')
  assert.equal(editor.draft.value, '内置内容')
})

test('发布基线与旧覆盖文本一致时仍可保存以清除覆盖', async () => {
  const editor = useExpertPromptEditor({
    getAgentExpertPrompt: async id => ({ ...doc(id), overridden: true }),
    updateAgentExpertPrompt: async id => doc(id),
  })
  await editor.load('expert')
  editor.restoreBuiltin()
  assert.equal(editor.canSave.value, true)
  await editor.save()
  assert.equal(editor.document.value.overridden, false)
  assert.equal(editor.canSave.value, false)
})
