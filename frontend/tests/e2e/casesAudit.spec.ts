import { expect, test, type Page, type Route } from '@playwright/test'

/** 完整用例包含页面未直接编辑的字段，检验读取与保存不会丢失业务数据。 */
function row(id = 'row-a', name = '原始用例') {
  return { id, code: 'TC-001', name, strategy: '正向', priority: 'HX', module: '账户',
    submodule: '登录', feature_point: '身份验证', precondition: '已有账号', steps: '1. 登录',
    expected: '登录成功', test_type: '回归', mapped: true, pending_complete: false, custom_field: '保留扩展数据' }
}

/** 真实页面 HTTP 夹具支持延迟与失败，不连接真实供应商或数据库。 */
async function setup(page: Page) {
  const saves: { id: string; cases: Record<string, unknown>[]; expected_revision: number; column_schema: Record<string, unknown>[] }[] = []
  const confirms: string[] = []
  const generations: Record<string, unknown>[] = []
  const analyses: Record<string, unknown>[] = []
  const candidateCreates: { name: string; cases: Record<string, unknown>[] }[] = []
  const imports: { id: string; mode: string | null; expectedRevision: string | null }[] = []
  const newImports: string[] = []
  const held: Record<string, Route> = {}
  const holds = new Set<string>()
  let failSave = false
  let failNewImport = false
  let failCandidateCreate = false
  let failGenerate = false
  let failUpload = false
  let createCalls = 0
  const sets = ['a', 'b', 'c'].map(id => ({ id, task_id: id === 'b' ? 'task-b' : null, name: `用例集${id.toUpperCase()}`, status: 'generated',
    revision: 0, generated_count: 1, confirmed_count: 0, checks: [], column_schema: [{ key: 'custom_field', name: '扩展属性', type: 'text' }] }))
  const rows: Record<string, Record<string, unknown>[]> = { a: [row()], b: [row('row-b', 'B用例')], c: [row('row-c', 'C用例')] }
  await page.route(/^http:\/\/127\.0\.0\.1:5273\/api\//, async route => {
    const url = new URL(route.request().url())
    const id = url.pathname.split('/')[3]
    if (url.pathname === '/api/files') {
      if (holds.has('fileUpload')) { held.fileUpload = route; return }
      if (failUpload) return route.fulfill({ status: 400, json: { code: 'VALIDATION', message: '上传失败' } })
      return route.fulfill({ json: { id: 'source-doc-1', filename: '需求.md', size: 12 } })
    }
    if (url.pathname === '/api/case-sets/from-candidates') {
      const payload = route.request().postDataJSON()
      candidateCreates.push(payload)
      if (failCandidateCreate) return route.fulfill({ status: 400, json: { code: 'VALIDATION', message: '候选保存失败' } })
      if (holds.has('candidateCreate')) { held.candidateCreate = route; return }
      const created = { id: `generated-${candidateCreates.length}`, task_id: null, name: payload.name, status: 'generated',
        revision: 1, generated_count: payload.cases.length, confirmed_count: 0, checks: [], column_schema: [] }
      sets.push(created)
      rows[created.id] = payload.cases.map((item: Record<string, unknown>, i: number) => ({ ...item, id: `generated-row-${i}` }))
      return route.fulfill({ status: 201, json: { ...created, cases: rows[created.id] } })
    }
    if (url.pathname === '/api/case-sets/import') {
      newImports.push(route.request().postData() || '')
      if (failNewImport) return route.fulfill({ status: 400, json: { code: 'VALIDATION', message: '无法解析 Excel' } })
      const created = { id: 'imported', task_id: null, name: 'cases', status: 'generated',
        revision: 1, generated_count: 1, confirmed_count: 0, checks: [], column_schema: [] }
      sets.push(created)
      rows.imported = [row('import-row', 'Excel 导入用例')]
      return route.fulfill({ status: 201, json: { case_set_id: created.id, ok: true, revision: 1,
        imported_count: 1, skipped_count: 0, generated_count: 1, checks: [], format: 'simple', mode: 'replace' } })
    }
    if (url.pathname === '/api/case-sets') {
      if (route.request().method() === 'POST') {
        createCalls++
        const created = { id: 'imported', task_id: null, name: route.request().postDataJSON().name, status: 'generated',
          revision: 0, generated_count: 0, confirmed_count: 0, checks: [], column_schema: [] }
        sets.push(created)
        rows.imported = []
        return route.fulfill({ json: created })
      }
      return route.fulfill({ json: { items: sets } })
    }
    if (url.pathname === '/api/case-sets/generation-skills') return route.fulfill({ json: { items: [{
      id: 'functional-test-design', name: '功能测试设计', description: '风险与需求驱动的人工用例设计',
      version: '1.0.0', license: 'MIT', source_url: 'https://github.com/jaktestowac/awesome-copilot-for-testers',
    }] } })
    if (url.pathname === '/api/case-sets/ai-design') {
      const payload = route.request().postDataJSON()
      analyses.push(payload)
      if (holds.has('design')) { held.design = route; return }
      return route.fulfill({ json: { design: { source_digest: '0'.repeat(64), summary: '登录功能测试设计', questions: ['错误提示需确认'], assumptions: [],
        test_points: [1, 2].map(i => ({ id: `TP-00${i}`, title: `登录测试点 ${i}`, module: '账户', risk: 'high',
          expected: '进入工作台', constraints: '', source_quote: payload.source_text || '登录需求', strategies: ['positive', 'negative'] })) },
        loaded_sections: ['workflow', 'design'] } })
    }
    if (url.pathname === '/api/case-sets/ai-generate') {
      generations.push(route.request().postDataJSON())
      if (failGenerate) return route.fulfill({ status: 502, json: { code: 'UPSTREAM', message: '生成失败' } })
      if (holds.has('generate')) { held.generate = route; return }
      return route.fulfill({ json: { items: [{ ...row('candidate', '生成候选'), test_point_id: 'TP-001',
        requirement_quote: '登录功能需求', risk: 'high' }] } })
    }
    if (url.pathname.startsWith('/api/tasks/')) {
      const status = url.pathname.endsWith('task-failed') ? 'failed' : url.pathname.endsWith('task-cancelled') ? 'cancelled' : 'running'
      return route.fulfill({ json: { id: url.pathname.split('/')[3], kind: 'testcase', status } })
    }
    if (url.pathname.endsWith('/cases')) {
      const payload = route.request().postDataJSON()
      saves.push({ id, cases: payload.cases, expected_revision: payload.expected_revision, column_schema: payload.column_schema })
      if (failSave) return route.fulfill({ status: 400, json: { error: { code: 'VALIDATION', message: '保存失败' } } })
      const set = sets.find(s => s.id === id)!
      if (payload.expected_revision !== set.revision) return route.fulfill({ status: 409, json: { code: 'CONCURRENCY', message: '用例已由其他操作更新，请刷新后再保存' } })
      set.column_schema = payload.column_schema
      set.revision++
      if (holds.has('save')) { held.save = route; return }
      rows[id] = saves.at(-1)!.cases.map((item, i) => ({ ...item, id: item.id || `saved-${i}` }))
      return route.fulfill({ json: { items: rows[id], revision: set.revision, checks: set.checks } })
    }
    if (url.pathname.endsWith('/confirm')) {
      const set = sets.find(s => s.id === id)!
      if (route.request().postDataJSON().expected_revision !== set.revision) return route.fulfill({ status: 409, json: { code: 'CONCURRENCY', message: '用例已由其他操作更新，请刷新后再确认' } })
      confirms.push(id)
      set.status = 'confirmed'
      return route.fulfill({ json: set })
    }
    if (url.pathname.endsWith('/cancel')) {
      const set = sets.find(s => s.id === id)!
      if (route.request().postDataJSON().expected_revision !== set.revision) return route.fulfill({ status: 409, json: { code: 'CONCURRENCY', message: '用例已由其他操作更新，请刷新后再废弃' } })
      set.status = 'cancelled'
      return route.fulfill({ json: set })
    }
    if (url.pathname.endsWith('/import')) {
      imports.push({ id, mode: url.searchParams.get('mode'), expectedRevision: url.searchParams.get('expected_revision') })
      const set = sets.find(s => s.id === id)!
      if (Number(url.searchParams.get('expected_revision')) !== set.revision) {
        return route.fulfill({ status: 409, json: { code: 'CONCURRENCY', message: '用例已更新' } })
      }
      set.revision++
      rows[id] = [row('import-row', 'Excel 导入用例')]
      return route.fulfill({ json: { ok: true, revision: set.revision, imported_count: 1, skipped_count: 0 } })
    }
    if (url.pathname.endsWith('/export')) return route.fulfill({ body: `export:${url.searchParams.get('fmt')}` })
    if (url.pathname === `/api/case-sets/${id}`) {
      if (route.request().method() === 'PUT') return route.fulfill({ json: { ...sets.find(s => s.id === id), ...route.request().postDataJSON() } })
      if (holds.has(id)) { held[id] = route; return }
      return route.fulfill({ json: { ...sets.find(s => s.id === id), cases: rows[id] } })
    }
    return route.fulfill({ json: { items: [] } })
  })
  await page.goto('/tests/cases-audit-fixture.html')
  await expect(page.locator('.data-row')).toHaveCount(1)
  return { saves, confirms, generations, analyses, candidateCreates, imports, newImports, held, holds, rows, sets,
    get createCalls() { return createCalls }, failSave: () => { failSave = true }, recoverSave: () => { failSave = false },
    failNewImport: () => { failNewImport = true },
    failCandidateCreate: () => { failCandidateCreate = true }, recoverCandidateCreate: () => { failCandidateCreate = false },
    failGenerate: () => { failGenerate = true }, failUpload: () => { failUpload = true } }
}

/** 双击单元格进入现有编辑交互，再显式失焦完成编辑。 */
async function rename(page: Page, text: string, index = 0) {
  const cell = page.locator('.data-row').nth(index).locator('td').nth(3)
  await cell.click()
  await cell.click()
  await cell.locator('input').fill(text)
  await cell.locator('input').press('Tab')
}

async function generateCandidate(page: Page) {
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await page.getByPlaceholder('粘贴需求文档段落、状态转移逻辑或 OpenAPI 规范...').fill('登录功能需求')
  if (await page.getByRole('button', { name: '分析需求与测试点' }).isVisible()) await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await page.getByRole('button', { name: '生成候选用例' }).click()
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toBeVisible()
}

test('PRD 生成请求遵循真实后端字段契约', async ({ page }) => {
  const ctx = await setup(page)
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await page.getByPlaceholder('粘贴需求文档段落、状态转移逻辑或 OpenAPI 规范...').fill('测试登录需求')
  if (await page.getByRole('button', { name: '分析需求与测试点' }).isVisible()) await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await page.getByRole('button', { name: '生成候选用例' }).click()
  await expect.poll(() => ctx.generations.length).toBe(1)
  expect(Object.keys(ctx.generations[0]).sort()).toEqual(['design', 'max_count', 'skill_id', 'source_text', 'strategy_weights'])
  expect(ctx.generations[0].source_text).toBeTruthy()
  await page.getByLabel('追加到当前草稿「用例集A」').check()
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].cases[1]).toMatchObject({ name: '生成候选', submodule: '登录', feature_point: '身份验证', custom_field: '保留扩展数据' })
  expect(ctx.saves[0].cases[1]).not.toHaveProperty('id')
  expect(ctx.saves[0].expected_revision).toBe(0)
  expect(ctx.saves[0].column_schema).toHaveLength(1)
})

test('任务深链优先于当前用例集，保留未保存草稿并等待 Worker 生成', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, '待保存的 A 草稿')
  await page.evaluate(() => (window as any).__casesRouter.push('/?task_id=task-b'))
  await expect(page.getByText('存在未保存的用例修改')).toBeVisible()
  await expect(page.locator('.main-dataset-title')).toHaveText('用例集A')
  await page.getByRole('button', { name: '保存并切换', exact: true }).click()
  await expect(page.locator('.main-dataset-title')).toHaveText('用例集B')
  expect(ctx.saves[0]).toMatchObject({ id: 'a', cases: [{ name: '待保存的 A 草稿' }] })

  await page.evaluate(() => (window as any).__casesRouter.push('/?task_id=task-pending'))
  await expect(page.getByText('测试用例生成中')).toBeVisible()
  await expect(page.getByText('任务 task-pending 尚未生成对应用例集')).toBeVisible()
  ctx.sets[2].task_id = 'task-pending'
  await page.getByRole('button', { name: '刷新用例集' }).click()
  await expect(page.locator('.main-dataset-title')).toHaveText('用例集C')

  await page.evaluate(() => (window as any).__casesRouter.push('/?set_id=a'))
  await expect(page.locator('.main-dataset-title')).toHaveText('用例集A')
})

test('编辑往返保留真实 ID、固定字段和扩展数据', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, '修改后的名称')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].cases[0]).toMatchObject({ ...row(), name: '修改后的名称' })
  expect(ctx.saves[0].cases[0]).not.toHaveProperty('preconditions')
})

test('保存失败阻止确认入库和保存并切换', async ({ page }) => {
  const ctx = await setup(page)
  ctx.failSave()
  await rename(page, '未保存草稿')
  await page.getByRole('button', { name: '确认入库用例集' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  await expect(page.getByRole('button', { name: '保存用例修改' })).toBeEnabled()
  expect(ctx.confirms).toEqual([])
  await page.locator('.file-node').filter({ hasText: '用例集B' }).click()
  await page.getByRole('button', { name: '保存并切换', exact: true }).click()
  await expect.poll(() => ctx.saves.length).toBe(2)
  await expect(page.locator('.main-dataset-title')).toHaveText('用例集A')
  await expect(page.locator('.data-row')).toContainText('未保存草稿')
})

test('他人更新草稿后拒绝旧版本保存，保留本地编辑供人工核对', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, '本地未保存改动')
  await page.getByRole('button', { name: '新增扩展属性列' }).click()
  await page.getByPlaceholder('如 env, api_path').fill('environment')
  await page.getByPlaceholder('如 运行环境, 接口路径').fill('运行环境')
  await page.getByRole('button', { name: '确认添加' }).click()
  ctx.sets[0].revision++
  ctx.rows.a.push(row('external', '他人新增用例'))
  const refreshed = page.waitForResponse(response => response.url().endsWith('/api/case-sets') && response.request().method() === 'GET')
  await page.evaluate(() => (window as any).__casesRouter.push('/?set_id=a'))
  await refreshed
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].expected_revision).toBe(0)
  expect(ctx.saves[0].column_schema).toHaveLength(2)
  expect(ctx.sets[0].column_schema).toHaveLength(1)
  expect(ctx.rows.a).toContainEqual(expect.objectContaining({ name: '他人新增用例' }))
  await expect(page.getByText('用例已在其他窗口更新；本地修改已保留，请备份后刷新核对')).toBeVisible()
  await expect(page.locator('.data-row')).toContainText('本地未保存改动')
  await expect(page.getByRole('button', { name: '保存用例修改' })).toBeEnabled()
  expect(ctx.confirms).toEqual([])
})

test('确认入库检查修订号，旧页面不能确认他人更新的草稿', async ({ page }) => {
  const ctx = await setup(page)
  ctx.sets[0].revision++
  await page.getByRole('button', { name: '确认入库用例集' }).click()
  await expect(page.getByText('用例已在其他窗口更新，请刷新核对后再确认入库')).toBeVisible()
  expect(ctx.confirms).toEqual([])
  await expect(page.locator('.main-toolbar .status-badge')).toContainText('草稿待审')
})

test('废弃草稿保留只读记录并显示真实状态', async ({ page }) => {
  await setup(page)
  await page.locator('.file-node').filter({ hasText: '用例集A' }).click({ button: 'right' })
  await page.getByText('废弃草稿用例集', { exact: true }).click()
  await page.getByRole('button', { name: '确认废弃' }).click()
  await expect(page.locator('.file-node').filter({ hasText: '用例集A' })).toContainText('已废弃')
  await expect(page.locator('.main-toolbar .status-badge')).toContainText('已废弃')
  await expect(page.getByRole('button', { name: '新增测试用例' })).toHaveCount(0)
  await page.locator('.data-row .td-chk').first().click()
  await expect(page.getByText('该用例集仅供查看')).toBeVisible()
  await expect(page.getByRole('button', { name: /批量删除/ })).toHaveCount(0)
})

test('侧栏废弃 B 不清除当前 A 的未保存草稿', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, 'A 待保存草稿')
  await page.locator('.file-node').filter({ hasText: '用例集B' }).click({ button: 'right' })
  await page.getByText('废弃草稿用例集', { exact: true }).click()
  await page.getByRole('button', { name: '确认废弃' }).click()
  await expect(page.locator('.file-node').filter({ hasText: '用例集B' })).toContainText('已废弃')
  await expect(page.locator('.main-dataset-title')).toHaveText('用例集A')
  await expect(page.locator('.data-row')).toContainText('A 待保存草稿')
  await expect(page.getByRole('button', { name: '保存用例修改' })).toBeEnabled()
  expect(ctx.saves).toHaveLength(0)
})

test('旧页面不能废弃他人已更新的草稿', async ({ page }) => {
  const ctx = await setup(page)
  ctx.sets[0].revision++
  await page.locator('.file-node').filter({ hasText: '用例集A' }).click({ button: 'right' })
  await page.getByText('废弃草稿用例集', { exact: true }).click()
  await page.getByRole('button', { name: '确认废弃' }).click()
  await expect(page.getByText('用例已在其他窗口更新，请刷新核对后再废弃')).toBeVisible()
  expect(ctx.sets[0].status).toBe('generated')
})

test('失败和已取消的任务深链不再显示永久生成中', async ({ page }) => {
  await setup(page)
  await page.evaluate(() => (window as any).__casesRouter.push('/?task_id=task-failed'))
  await expect(page.getByText('测试用例生成失败')).toBeVisible()
  await page.evaluate(() => (window as any).__casesRouter.push('/?task_id=task-cancelled'))
  await expect(page.getByText('测试用例生成已取消')).toBeVisible()
})

test('迟到的用例集响应不能覆盖后来选择的用例集', async ({ page }) => {
  const ctx = await setup(page)
  ctx.holds.add('b')
  await page.locator('.file-node').filter({ hasText: '用例集B' }).click()
  await expect.poll(() => !!ctx.held.b).toBe(true)
  await page.locator('.file-node').filter({ hasText: '用例集C' }).click()
  await expect(page.locator('.data-row')).toContainText('C用例')
  await ctx.held.b.fulfill({ json: { ...ctx.sets[1], cases: ctx.rows.b } })
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await expect(page.locator('.data-row')).toContainText('C用例')
})

test('保存期间的新编辑保持待保存，新行回写服务端 ID', async ({ page }) => {
  const ctx = await setup(page)
  await page.getByRole('button', { name: '新增测试用例' }).click()
  await page.locator('.data-row').nth(1).locator('input').fill('新用例')
  await page.locator('.data-row').nth(1).locator('input').press('Tab')
  ctx.holds.add('save')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => !!ctx.held.save).toBe(true)
  await rename(page, '保存期间的新编辑', 1)
  await ctx.held.save.fulfill({ json: { items: ctx.saves[0].cases.map((item, i) => ({ ...item, id: item.id || `saved-${i}` })), revision: ctx.sets[0].revision } })
  await expect(page.getByRole('button', { name: '保存用例修改' })).toBeEnabled()
  ctx.holds.delete('save')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(2)
  expect(ctx.saves[0].cases[1]).not.toHaveProperty('id')
  expect(ctx.saves[1].cases[1]).toMatchObject({ id: 'saved-1', name: '保存期间的新编辑' })
  expect(ctx.saves[1].expected_revision).toBe(1)
})

test('Excel 与 XMind 导出触发真实文件下载', async ({ page }) => {
  await setup(page)
  for (const [label, extension] of [['导出为 Excel (XLSX)', 'xlsx'], ['导出为 XMind 脑图', 'xmind']]) {
    await page.getByRole('button', { name: '更多操作', exact: true }).click()
    const download = page.waitForEvent('download')
    await page.getByText(label, { exact: true }).click()
    expect((await download).suggestedFilename()).toBe(`用例集A.${extension}`)
  }
})

test('Excel 导入入口将当前集修订号传给导入接口并刷新用例', async ({ page }) => {
  const ctx = await setup(page)
  await page.getByRole('button', { name: '导入 Excel 用例' }).click()
  await expect(page.getByText('导入 Excel 用例', { exact: true })).toBeVisible()
  await page.locator('.n-modal input[type=file]').setInputFiles({ name: 'cases.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('fixture') })
  await page.getByRole('button', { name: '开始导入' }).click()
  await expect.poll(() => ctx.imports).toEqual([{ id: 'a', mode: 'append', expectedRevision: '0' }])
  await expect(page.locator('.data-row')).toContainText('Excel 导入用例')
})

test('当前集有未保存草稿时只能导入新集，导入完成仍保护原草稿', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, 'A 未保存草稿')
  await page.getByRole('button', { name: '导入 Excel 用例' }).click()
  await expect(page.getByRole('radio', { name: '导入到当前用例集' })).toBeDisabled()
  await page.locator('.n-modal input[type=file]').setInputFiles({ name: 'cases.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('fixture') })
  await page.getByRole('button', { name: '开始导入' }).click()
  await expect.poll(() => ctx.newImports.length).toBe(1)
  expect(ctx.imports).toEqual([])
  expect(ctx.createCalls).toBe(0)
  await expect(page.getByText('存在未保存的用例修改')).toBeVisible()
  await expect(page.locator('.main-dataset-title')).toHaveText('用例集A')
  await expect(page.locator('.data-row')).toContainText('A 未保存草稿')
  await expect(page.getByRole('button', { name: '保存用例修改' })).toBeEnabled()
})

test('新集 Excel 导入失败时不先创建空用例集，且保留文件以便重试', async ({ page }) => {
  const ctx = await setup(page)
  ctx.failNewImport()
  await rename(page, 'A 未保存草稿')
  await page.getByRole('button', { name: '导入 Excel 用例' }).click()
  await page.locator('.n-modal input[type=file]').setInputFiles({ name: 'bad.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('invalid') })
  await page.getByRole('button', { name: '开始导入' }).click()
  await expect.poll(() => ctx.newImports.length).toBe(1)
  expect(ctx.createCalls).toBe(0)
  expect(ctx.sets).toHaveLength(3)
  await expect(page.getByText('导入 Excel 用例', { exact: true })).toBeVisible()
  await expect(page.locator('.n-modal .n-upload-file')).toContainText('bad.xlsx')
  await expect(page.locator('.data-row')).toContainText('A 未保存草稿')
})

test('确认操作等待正在保存的请求，保存后展示最新自检并等待再次确认', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, '待确认版本')
  ctx.holds.add('save')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => !!ctx.held.save).toBe(true)
  await page.getByRole('button', { name: '确认入库用例集' }).click()
  expect(ctx.confirms).toEqual([])
  expect(ctx.saves).toHaveLength(1)
  await ctx.held.save.fulfill({ json: { items: ctx.saves[0].cases, revision: ctx.sets[0].revision,
    checks: [{ level: 'error', code: 'missing_step', message: '请核对新增用例步骤' }] } })
  await expect(page.locator('.review-check')).toContainText('请核对新增用例步骤')
  expect(ctx.confirms).toEqual([])
  await expect(page.locator('.main-toolbar .status-badge')).toContainText('草稿')
  await page.getByRole('button', { name: '确认入库用例集' }).click()
  await expect.poll(() => ctx.confirms).toEqual(['a'])
  await expect(page.locator('.main-toolbar .status-badge')).toContainText('已确认入库')
  await page.locator('.data-row .td-chk').first().click()
  await expect(page.getByRole('button', { name: /批量删除/ })).toHaveCount(0)
})

test('直接确认未保存编辑时仅保存草稿，第二次点击才入库', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, '先审核后入库')
  await page.getByRole('button', { name: '确认入库用例集' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  await expect(page.locator('.main-toolbar .status-badge')).toContainText('草稿')
  expect(ctx.confirms).toEqual([])
  await page.getByRole('button', { name: '确认入库用例集' }).click()
  await expect.poll(() => ctx.confirms).toEqual(['a'])
})

test('放弃旧草稿切换后，旧保存响应不清除新用例集草稿', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, 'A提交版本')
  ctx.holds.add('save')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => !!ctx.held.save).toBe(true)
  await page.locator('.file-node').filter({ hasText: '用例集B' }).click()
  await page.getByRole('button', { name: '放弃修改', exact: true }).click()
  await expect(page.locator('.data-row')).toContainText('B用例')
  await rename(page, 'B新草稿')
  await ctx.held.save.fulfill({ json: { items: ctx.saves[0].cases, revision: ctx.sets[0].revision } })
  await expect(page.getByRole('button', { name: '保存用例修改' })).toBeEnabled()
  ctx.holds.delete('save')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(2)
  expect(ctx.saves[1]).toMatchObject({ id: 'b', cases: [{ id: 'row-b', name: 'B新草稿' }] })
})

test('删除最后一行保存空数组，加载中不允许新增或确认', async ({ page }) => {
  const ctx = await setup(page)
  await page.getByRole('button', { name: '删除用例 TC-001' }).click()
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].cases).toEqual([])
  ctx.holds.add('b')
  await page.locator('.file-node').filter({ hasText: '用例集B' }).click()
  await expect.poll(() => !!ctx.held.b).toBe(true)
  await expect(page.getByRole('button', { name: '新增测试用例' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '确认入库用例集' })).toBeDisabled()
  await ctx.held.b.fulfill({ json: { ...ctx.sets[1], cases: ctx.rows.b } })
  await expect(page.getByRole('button', { name: '新增测试用例' })).toBeEnabled()
})

test('真实六策略候选可筛选且保存规范名称，旧策略别名兼容加载', async ({ page }) => {
  const ctx = await setup(page)
  await page.route('**/api/case-sets/ai-generate', route => route.fulfill({ json: { items:
    ['正向', '反向', '边界', '等价类', '状态迁移', '场景'].map((strategy, i) => ({ ...row(`candidate-${i}`, `${strategy}候选`), strategy })) } }))
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await page.getByPlaceholder('粘贴需求文档段落、状态转移逻辑或 OpenAPI 规范...').fill('测试六策略需求')
  if (await page.getByRole('button', { name: '分析需求与测试点' }).isVisible()) await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await page.getByRole('button', { name: '生成候选用例' }).click()
  await page.getByLabel('追加到当前草稿「用例集A」').check()
  await page.getByRole('button', { name: '采纳并保存候选 (6 条)' }).click()
  await expect(page.getByText('✓ 6 大策略完备覆盖')).toBeVisible()
  await page.locator('.strategy-pill').filter({ hasText: '等价类' }).click()
  await expect(page.locator('.data-row')).toHaveCount(1)
  await rename(page, '修改等价类候选')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(2)
  expect(ctx.saves[1].cases[4]).toMatchObject({ name: '修改等价类候选', strategy: '等价类' })
  expect(ctx.saves[1].cases[5].strategy).toBe('状态迁移')
  ctx.rows.b[0].strategy = '等价'
  await page.locator('.file-node').filter({ hasText: '用例集B' }).click()
  await expect(page.locator('.data-row')).toContainText('等价类')
  await rename(page, '旧别名用例')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(3)
  expect(ctx.saves[2].cases[0].strategy).toBe('等价类')
})

test('用例生成与 AI 补全允许等待服务端模型的 120 秒预算', async ({ page }) => {
  await setup(page)
  const timeouts = await page.evaluate(async () => {
    const modulePath = '/src/api/http.ts'
    const { default: http, api } = await import(modulePath)
    const requests: number[] = []
    const interceptor = http.interceptors.request.use((config: { timeout: number }) => {
      requests.push(config.timeout)
      return config
    })
    try {
      await api.cases.generateCases({ source_text: '测试需求', strategy_weights: { positive: 100 }, max_count: 1 })
      await api.cases.aiFillCases('a', { case_ids: ['row-a'] })
      return requests
    } finally { http.interceptors.request.eject(interceptor) }
  })
  expect(timeouts).toEqual([130000, 130000])
})

test('候选完整审核后原子保存为新草稿，步骤与功能点可在详细编辑中修改', async ({ page }) => {
  const ctx = await setup(page)
  await generateCandidate(page)
  await expect(page.getByLabel('新建草稿并保存候选')).toBeChecked()
  await page.getByRole('textbox', { name: '候选 1 名称' }).fill('审核后登录用例')
  await page.getByRole('textbox', { name: '候选 1 功能点' }).fill('登录令牌刷新')
  await page.getByRole('textbox', { name: '候选 1 执行步骤' }).fill('1. 输入账号\n2. 提交登录')
  await page.getByRole('textbox', { name: '新草稿名称' }).fill('登录功能草稿')
  if (process.env.CASE_REVIEW_SHOTS) await page.screenshot({ path: 'test-results/cases-candidate-desktop.png', fullPage: true })
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => ctx.candidateCreates.length).toBe(1)
  expect(ctx.createCalls).toBe(0)
  expect(ctx.candidateCreates[0]).toMatchObject({ name: '登录功能草稿', cases: [{
    name: '审核后登录用例', feature_point: '登录令牌刷新', steps: '1. 输入账号\n2. 提交登录',
  }] })
  expect(ctx.candidateCreates[0].cases[0]).not.toHaveProperty('id')
  await expect(page.locator('.main-dataset-title')).toHaveText('登录功能草稿')
  await page.getByRole('button', { name: '详细编辑用例 TC-001' }).click()
  await page.getByRole('textbox', { name: '编辑功能点' }).fill('登录验证码')
  await page.getByRole('textbox', { name: '编辑执行步骤' }).fill('1. 输入验证码\n2. 验证成功')
  await page.getByRole('button', { name: '保存修改', exact: true }).last().click()
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].cases[0]).toMatchObject({ feature_point: '登录验证码', steps: '1. 输入验证码\n2. 验证成功' })
})

test('原子采纳失败保留候选且不创建空集', async ({ page }) => {
  const ctx = await setup(page)
  ctx.failCandidateCreate()
  await generateCandidate(page)
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => ctx.candidateCreates.length).toBe(1)
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toBeVisible()
  expect(ctx.sets).toHaveLength(3)
  expect(ctx.createCalls).toBe(0)
})

test('当前草稿保存失败后可重试，候选不重复追加', async ({ page }) => {
  const ctx = await setup(page)
  ctx.failSave()
  await generateCandidate(page)
  await page.getByLabel('追加到当前草稿「用例集A」').check()
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  await expect(page.getByRole('button', { name: '重试保存候选' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toBeDisabled()
  await page.getByRole('button', { name: '返回用例库', exact: true }).click()
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await expect(page.getByLabel('追加到当前草稿「用例集A」')).toBeChecked()
  await expect(page.getByRole('button', { name: '重试保存候选' })).toBeVisible()
  ctx.recoverSave()
  await page.getByRole('button', { name: '重试保存候选' }).click()
  await expect.poll(() => ctx.saves.length).toBe(2)
  expect(ctx.saves[1].cases).toHaveLength(2)
  await expect(page.locator('.data-row')).toHaveCount(2)
})

test('当前草稿修订冲突时保留候选并提示核对，不诱导重复重试', async ({ page }) => {
  const ctx = await setup(page)
  await generateCandidate(page)
  await page.getByLabel('追加到当前草稿「用例集A」').check()
  ctx.sets[0].revision++
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  await expect(page.getByRole('button', { name: '版本冲突，请先核对' })).toBeDisabled()
  await expect(page.locator('.data-row')).toHaveCount(2)
  expect(ctx.rows.a).toHaveLength(1)
})

test('已编辑候选关闭后重开仍保留，重新生成需确认覆盖', async ({ page }) => {
  await setup(page)
  await generateCandidate(page)
  await page.getByRole('textbox', { name: '候选 1 名称' }).fill('人工修订的候选')
  await page.getByRole('button', { name: '返回用例库', exact: true }).click()
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toHaveValue('人工修订的候选')
  await page.getByRole('button', { name: '返回测试设计' }).click()
  if (await page.getByRole('button', { name: '分析需求与测试点' }).isVisible()) await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await page.getByRole('button', { name: '生成候选用例' }).click()
  await expect(page.getByText('重新生成候选？')).toBeVisible()
  await page.getByRole('button', { name: '保留候选' }).click()
  await page.getByRole('button', { name: '返回用例库', exact: true }).click()
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toHaveValue('人工修订的候选')
})

test('覆盖重新生成失败时仍保留已编辑候选', async ({ page }) => {
  const ctx = await setup(page)
  await generateCandidate(page)
  await page.getByRole('textbox', { name: '候选 1 名称' }).fill('保留的人工修订')
  await page.getByRole('button', { name: '返回测试设计' }).click()
  ctx.failGenerate()
  if (await page.getByRole('button', { name: '分析需求与测试点' }).isVisible()) await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await page.getByRole('button', { name: '生成候选用例' }).click()
  await page.getByRole('button', { name: '覆盖并重新生成' }).click()
  await expect.poll(() => ctx.generations.length).toBe(2)
  await page.getByRole('button', { name: '返回用例库', exact: true }).click()
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toHaveValue('保留的人工修订')
})

test('原草稿未保存时新生成草稿仍可从侧栏找回', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, 'A 未保存编辑')
  await generateCandidate(page)
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => ctx.candidateCreates.length).toBe(1)
  await expect(page.getByText('存在未保存的用例修改')).toBeVisible()
  await expect(page.locator('.file-node').filter({ hasText: '需求用例-' })).toBeVisible()
  await expect(page.locator('.data-row')).toContainText('A 未保存编辑')
})

test('已入库集仍可把生成候选保存到新草稿', async ({ page }) => {
  const ctx = await setup(page)
  ctx.sets[0].status = 'confirmed'
  await page.reload()
  await generateCandidate(page)
  await expect(page.getByLabel('新建草稿并保存候选')).toBeChecked()
  await expect(page.getByLabel('追加到当前草稿「用例集A」')).toHaveCount(0)
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => ctx.candidateCreates.length).toBe(1)
})

test('上传需求文件通过 source_doc_id 生成，数量可调至 1–80', async ({ page }) => {
  const ctx = await setup(page)
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await expect(page.getByPlaceholder('粘贴需求文档段落、状态转移逻辑或 OpenAPI 规范...')).toHaveValue('')
  await page.getByLabel('上传需求文件').check()
  await page.getByLabel('选择需求文件').setInputFiles({ name: '需求.md', mimeType: 'text/markdown', buffer: Buffer.from('登录需求') })
  await expect(page.getByText('需求.md', { exact: true })).toBeVisible()
  if (await page.getByRole('button', { name: '分析需求与测试点' }).isVisible()) await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await page.getByRole('button', { name: '生成候选用例' }).click()
  await expect.poll(() => ctx.generations.length).toBe(1)
  expect(ctx.generations[0]).toMatchObject({ source_doc_id: 'source-doc-1', source_text: '' })
  await page.getByRole('button', { name: '返回测试设计' }).click()
  const count = page.getByRole('spinbutton', { name: '最多生成条数' })
  await expect(count).toHaveAttribute('min', '1')
  await expect(count).toHaveAttribute('max', '80')
})

test('需求文件慢上传显示进度，且请求使用 180 秒超时', async ({ page }) => {
  const ctx = await setup(page)
  await page.evaluate(async () => {
    const { default: http } = await import('/src/api/http.ts')
    ;(window as any).__fileUploadTimeouts = []
    http.interceptors.request.use(config => {
      if (config.url === '/api/files') (window as any).__fileUploadTimeouts.push(config.timeout)
      return config
    })
  })
  ctx.holds.add('fileUpload')
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await page.getByLabel('上传需求文件').check()
  await page.getByLabel('选择需求文件').setInputFiles({ name: '需求.md', mimeType: 'text/markdown', buffer: Buffer.from('登录需求') })
  await expect.poll(() => !!ctx.held.fileUpload).toBe(true)
  await expect.poll(() => page.evaluate(() => (window as any).__fileUploadTimeouts)).toEqual([180_000])
  await expect(page.locator('.source-upload [role=status]')).toContainText(/已上传 \d+%/)
  await expect(page.getByLabel('选择需求文件')).toBeDisabled()
  await ctx.held.fileUpload.fulfill({ json: { id: 'source-doc-1', filename: '需求.md', size: 12 } })
  await expect(page.getByText('需求.md', { exact: true })).toBeVisible()
})

test('替换需求文件上传失败时保留之前可用的来源', async ({ page }) => {
  const ctx = await setup(page)
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await page.getByLabel('上传需求文件').check()
  await page.getByLabel('选择需求文件').setInputFiles({ name: '需求.md', mimeType: 'text/markdown', buffer: Buffer.from('原始需求') })
  await expect(page.getByText('需求.md', { exact: true })).toBeVisible()
  ctx.failUpload()
  await page.getByLabel('选择需求文件').setInputFiles({ name: '新需求.md', mimeType: 'text/markdown', buffer: Buffer.from('新需求') })
  await expect(page.getByText('需求.md', { exact: true })).toBeVisible()
  if (await page.getByRole('button', { name: '分析需求与测试点' }).isVisible()) await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await page.getByRole('button', { name: '生成候选用例' }).click()
  await expect.poll(() => ctx.generations.length).toBe(1)
  expect(ctx.generations[0].source_doc_id).toBe('source-doc-1')
})

test('窄屏仍可操作保存、确认及完整候选审核工作台', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await setup(page)
  for (const name of ['保存用例修改', '确认入库用例集']) {
    const button = page.getByRole('button', { name })
    await button.scrollIntoViewIfNeeded()
    const box = await button.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.x + box!.width).toBeLessThanOrEqual(390)
  }
  await generateCandidate(page)
  const apply = page.getByRole('button', { name: '采纳并保存候选 (1 条)' })
  await apply.scrollIntoViewIfNeeded()
  const box = await apply.boundingBox()
  expect(box).not.toBeNull()
  expect(box!.x + box!.width).toBeLessThanOrEqual(390)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  if (process.env.CASE_REVIEW_SHOTS) await page.screenshot({ path: 'test-results/cases-candidate-mobile.png', fullPage: true })
})

test('目录发现后逐步分析、选择测试点，需求依据随候选保存', async ({ page }) => {
  const ctx = await setup(page)
  await page.getByRole('button', { name: 'AI 生成工作台', exact: true }).click()
  await expect(page.getByRole('combobox', { name: '用例设计 Skill' })).toHaveValue('functional-test-design')
  expect(ctx.analyses).toHaveLength(0)
  expect(ctx.generations).toHaveLength(0)
  await page.getByRole('textbox', { name: '需求正文' }).fill('登录功能需求')
  await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await expect(page.getByRole('region', { name: '需求待澄清事项' })).toContainText('错误提示需确认')
  await page.getByLabel('选择测试点 TP-002').uncheck()
  await page.getByRole('textbox', { name: '测试点 TP-001 预期' }).fill('成功登录并进入工作台')
  if (process.env.CASE_REVIEW_SHOTS) {
    await page.locator('.studio-scroll').evaluate(node => { node.scrollTop = 0 })
    await page.screenshot({ path: 'test-results/cases-design-desktop.png', fullPage: true })
  }
  await page.getByRole('button', { name: '生成候选用例', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toBeVisible()
  expect(ctx.analyses).toHaveLength(1)
  expect(ctx.generations[0].design).toMatchObject({ test_points: [{ id: 'TP-001', expected: '成功登录并进入工作台' }] })
  expect((ctx.generations[0].design as { test_points: unknown[] }).test_points).toHaveLength(1)
  await page.getByText('需求依据', { exact: true }).click()
  await expect(page.locator('.requirement-evidence')).toContainText('登录功能需求')
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => ctx.candidateCreates.length).toBe(1)
  expect(ctx.candidateCreates[0].cases[0]).toMatchObject({ test_point_id: 'TP-001', requirement_quote: '登录功能需求' })
  await page.getByRole('button', { name: '详细编辑用例 TC-001' }).click()
  await expect(page.locator('.case-evidence')).toContainText('TP-001')
})

test('技能目录失联不能开始分析，可重试后恢复', async ({ page }) => {
  const ctx = await setup(page)
  await page.route('**/api/case-sets/generation-skills', route => route.fulfill({ status: 503, json: { code: 'INTERNAL', message: '技能暂不可用' } }))
  await page.getByRole('button', { name: 'AI 生成工作台', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('技能暂不可用')
  await expect(page.getByRole('button', { name: '分析需求与测试点' })).toBeDisabled()
  expect(ctx.analyses).toHaveLength(0)
  await page.unroute('**/api/case-sets/generation-skills')
  await page.getByRole('button', { name: '重试加载' }).click()
  await expect(page.getByRole('button', { name: '分析需求与测试点' })).toBeEnabled()
})

test('需求分析失败保留正文，修改来源后旧测试设计失效', async ({ page }) => {
  const ctx = await setup(page)
  await page.route('**/api/case-sets/ai-design', route => route.fulfill({ status: 502, json: { code: 'UPSTREAM', message: '需求分析失败' } }))
  await page.getByRole('button', { name: 'AI 生成工作台', exact: true }).click()
  await page.getByRole('textbox', { name: '需求正文' }).fill('第一版需求')
  await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await expect(page.getByRole('alert')).toContainText('需求分析失败')
  await expect(page.getByRole('textbox', { name: '需求正文' })).toHaveValue('第一版需求')
  expect(ctx.generations).toHaveLength(0)
  await page.unroute('**/api/case-sets/ai-design')
  await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await page.getByRole('button', { name: '返回修改需求' }).click()
  await page.getByRole('textbox', { name: '需求正文' }).fill('第二版需求')
  await expect(page.getByRole('button', { name: '2 测试设计', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await expect(page.locator('.test-point blockquote').first()).toContainText('第二版需求')
  expect(ctx.analyses.map(item => item.source_text)).toEqual(['第一版需求', '第二版需求'])
})

test('筛选库状态或候选不丢弃编辑，并支持暗色工作台', async ({ page }) => {
  const ctx = await setup(page)
  ctx.sets[1].status = 'confirmed'
  await page.reload()
  await rename(page, '保留的草稿')
  await page.locator('.library-status').getByRole('button', { name: '已入库 1', exact: true }).click()
  await expect(page.locator('.file-node')).toHaveCount(1)
  await expect(page.locator('.data-row')).toContainText('保留的草稿')
  await generateCandidate(page)
  await page.getByRole('textbox', { name: '候选 1 名称' }).fill('人工核对后的用例')
  await page.getByLabel('仅看待补全').check()
  await expect(page.locator('.candidate-card')).toHaveCount(0)
  await page.getByLabel('仅看待补全').uncheck()
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toHaveValue('人工核对后的用例')
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'))
  await expect(page.locator('.generation-studio')).toHaveCSS('background-color', 'rgb(17, 24, 39)')
  if (process.env.CASE_REVIEW_SHOTS) {
    await page.locator('.studio-scroll').evaluate(node => { node.scrollTop = 0 })
    await page.screenshot({ path: 'test-results/cases-studio-dark.png', fullPage: true })
  }
  await page.getByRole('button', { name: '返回用例库' }).click()
  await expect(page.locator('.data-row')).toContainText('保留的草稿')
})

test('六策略允许明确输入整数百分比，合计错误时阻止生成', async ({ page }) => {
  const ctx = await setup(page)
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await page.getByPlaceholder('粘贴需求文档段落、状态转移逻辑或 OpenAPI 规范...').fill('登录功能需求')
  const positive = page.getByRole('spinbutton', { name: '正向策略百分比' })
  await expect(positive).toHaveValue('40')
  await positive.fill('100')
  await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await expect(page.getByRole('button', { name: '生成候选用例' })).toBeDisabled()
  for (const label of ['反向', '边界', '等价类', '状态迁移', '场景']) {
    await page.getByRole('spinbutton', { name: `${label}策略百分比` }).fill('0')
  }
  await expect(page.getByText('合计 100%')).toBeVisible()
  if (await page.getByRole('button', { name: '分析需求与测试点' }).isVisible()) await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await page.getByRole('button', { name: '生成候选用例' }).click()
  await expect.poll(() => ctx.generations.length).toBe(1)
  expect(ctx.generations[0].strategy_weights).toEqual({ positive: 100, negative: 0, boundary: 0, equivalence: 0, state: 0, scenario: 0 })
})

test('新草稿保存未完成时不能返回或修改候选，旧响应只完成本次采纳', async ({ page }) => {
  const ctx = await setup(page)
  await generateCandidate(page)
  ctx.holds.add('candidateCreate')
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => !!ctx.held.candidateCreate).toBe(true)
  await expect(page.getByRole('button', { name: '返回测试设计' })).toBeDisabled()
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '返回用例库', exact: true })).toBeDisabled()
  const payload = ctx.candidateCreates[0]
  const created = { id: 'generated-slow', task_id: null, name: payload.name, status: 'generated',
    revision: 1, generated_count: payload.cases.length, confirmed_count: 0, checks: [], column_schema: [] }
  ctx.sets.push(created)
  ctx.rows[created.id] = payload.cases.map((item, index) => ({ ...item, id: `slow-row-${index}` }))
  await ctx.held.candidateCreate.fulfill({ status: 201, json: { ...created, cases: ctx.rows[created.id] } })
  await expect(page.locator('.main-dataset-title')).toHaveText(created.name)
})

test('推导请求进行中冻结来源和策略，不能并行采纳旧候选', async ({ page }) => {
  const ctx = await setup(page)
  ctx.holds.add('generate')
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await page.getByPlaceholder('粘贴需求文档段落、状态转移逻辑或 OpenAPI 规范...').fill('来源 A')
  if (await page.getByRole('button', { name: '分析需求与测试点' }).isVisible()) await page.getByRole('button', { name: '分析需求与测试点' }).click()
  await page.getByRole('button', { name: '生成候选用例' }).click()
  await expect.poll(() => !!ctx.held.generate).toBe(true)
  await expect(page.getByRole('button', { name: '返回修改需求' })).toBeDisabled()
  await expect(page.getByRole('textbox', { name: '测试点 TP-001 名称' })).toBeDisabled()
  await expect(page.getByRole('spinbutton', { name: '正向策略百分比' })).toBeDisabled()
  await page.getByRole('button', { name: '返回用例库', exact: true }).click()
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await expect(page.getByRole('button', { name: /采纳并保存候选/ })).toHaveCount(0)
  await ctx.held.generate.fulfill({ json: { items: [row('candidate', '来源 A 候选')] } })
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toHaveValue('来源 A 候选')
  expect(ctx.generations[0].source_text).toBe('来源 A')
})

test('详情弹窗打开时不能切集，原行变化也不能写入别的用例', async ({ page }) => {
  const ctx = await setup(page)
  await page.getByRole('button', { name: '详细编辑用例 TC-001' }).click()
  await page.getByPlaceholder('输入用例名称...').fill('仅 A 的编辑')
  await page.locator('.file-node').filter({ hasText: '用例集B' }).evaluate((node: HTMLElement) => node.click())
  await expect(page.locator('.main-dataset-title')).toHaveText('用例集A')
  await page.getByRole('button', { name: '保存修改', exact: true }).last().click()
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].cases[0].name).toBe('仅 A 的编辑')
  expect(ctx.rows.b[0].name).toBe('B用例')
})

test('当前草稿拒绝保存时可改存新草稿，失败不移除旧行，成功仅移除本批行', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, '旧草稿原有编辑')
  await generateCandidate(page)
  await page.getByLabel('追加到当前草稿「用例集A」').check()
  ctx.failSave()
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  await page.getByRole('button', { name: '返回用例库', exact: true }).click()
  await rename(page, '本批候选的后续编辑', 1)
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await page.getByRole('button', { name: '改存新草稿' }).click()
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toHaveValue('本批候选的后续编辑')
  ctx.failCandidateCreate()
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => ctx.candidateCreates.length).toBe(1)
  await page.getByRole('button', { name: '返回用例库', exact: true }).click()
  await expect(page.locator('.data-row')).toHaveCount(2)
  await expect(page.locator('.data-row').first()).toContainText('旧草稿原有编辑')
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  ctx.recoverCandidateCreate()
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await expect.poll(() => ctx.candidateCreates.length).toBe(2)
  expect(ctx.candidateCreates[1].cases[0].name).toBe('本批候选的后续编辑')
  await expect(page.locator('.data-row')).toHaveCount(1)
  await expect(page.locator('.data-row')).toContainText('旧草稿原有编辑')
  await expect(page.getByText('存在未保存的用例修改')).toBeVisible()
  expect(ctx.rows.a).toHaveLength(1)
})

test('旧保存请求不含本批候选时保留审核列表，重试后才清除候选', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, '旧保存快照')
  ctx.holds.add('save')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => !!ctx.held.save).toBe(true)
  await generateCandidate(page)
  await page.getByLabel('追加到当前草稿「用例集A」').check()
  await page.getByRole('button', { name: '采纳并保存候选 (1 条)' }).click()
  await ctx.held.save.fulfill({ json: { items: ctx.saves[0].cases, revision: ctx.sets[0].revision, checks: [] } })
  await expect(page.getByRole('button', { name: '重试保存候选' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '候选 1 名称' })).toBeVisible()
  expect(ctx.saves).toHaveLength(1)
  ctx.holds.delete('save')
  await page.getByRole('button', { name: '重试保存候选' }).click()
  await expect.poll(() => ctx.saves.length).toBe(2)
  expect(ctx.saves[1].cases).toHaveLength(2)
  await expect(page.locator('.data-row')).toHaveCount(2)
})
