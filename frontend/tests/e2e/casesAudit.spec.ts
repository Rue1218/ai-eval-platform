import { expect, test, type Page, type Route } from '@playwright/test'

/** 完整用例包含页面未直接编辑的字段，检验读取与保存不会丢失业务数据。 */
function row(id = 'row-a', name = '原始用例') {
  return { id, code: 'TC-001', name, strategy: '正向', priority: 'HX', module: '账户',
    submodule: '登录', feature_point: '身份验证', precondition: '已有账号', steps: '1. 登录',
    expected: '登录成功', test_type: '回归', mapped: true, pending_complete: false, custom_field: '保留扩展数据' }
}

/** 真实页面 HTTP 夹具支持延迟与失败，不连接真实供应商或数据库。 */
async function setup(page: Page) {
  const saves: { id: string; cases: Record<string, unknown>[] }[] = []
  const confirms: string[] = []
  const generations: Record<string, unknown>[] = []
  const held: Record<string, Route> = {}
  const holds = new Set<string>()
  let failSave = false
  const sets = ['a', 'b', 'c'].map(id => ({ id, task_id: id === 'b' ? 'task-b' : null, name: `用例集${id.toUpperCase()}`, status: 'generated',
    generated_count: 1, confirmed_count: 0, checks: [], column_schema: [{ key: 'custom_field', name: '扩展属性', type: 'text' }] }))
  const rows: Record<string, Record<string, unknown>[]> = { a: [row()], b: [row('row-b', 'B用例')], c: [row('row-c', 'C用例')] }
  await page.route(/^http:\/\/127\.0\.0\.1:5273\/api\//, async route => {
    const url = new URL(route.request().url())
    const id = url.pathname.split('/')[3]
    if (url.pathname === '/api/case-sets') return route.fulfill({ json: { items: sets } })
    if (url.pathname === '/api/case-sets/ai-generate') {
      generations.push(route.request().postDataJSON())
      return route.fulfill({ json: { items: [row('candidate', '生成候选')] } })
    }
    if (url.pathname.endsWith('/cases')) {
      saves.push({ id, cases: route.request().postDataJSON().cases })
      if (failSave) return route.fulfill({ status: 400, json: { error: { code: 'VALIDATION', message: '保存失败' } } })
      if (holds.has('save')) { held.save = route; return }
      rows[id] = saves.at(-1)!.cases.map((item, i) => ({ ...item, id: item.id || `saved-${i}` }))
      return route.fulfill({ json: { items: rows[id] } })
    }
    if (url.pathname.endsWith('/confirm')) {
      confirms.push(id)
      sets.find(s => s.id === id)!.status = 'confirmed'
      return route.fulfill({ json: sets.find(s => s.id === id) })
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
  return { saves, confirms, generations, held, holds, rows, sets, failSave: () => { failSave = true } }
}

/** 双击单元格进入现有编辑交互，再显式失焦完成编辑。 */
async function rename(page: Page, text: string, index = 0) {
  const cell = page.locator('.data-row').nth(index).locator('td').nth(3)
  await cell.click()
  await cell.click()
  await cell.locator('input').fill(text)
  await cell.locator('input').press('Tab')
}

test('PRD 生成请求遵循真实后端字段契约', async ({ page }) => {
  const ctx = await setup(page)
  await page.getByRole('button', { name: 'PRD 用例推导向导', exact: true }).click()
  await page.getByRole('button', { name: '推导候选用例 →' }).click()
  await expect.poll(() => ctx.generations.length).toBe(1)
  expect(Object.keys(ctx.generations[0]).sort()).toEqual(['max_count', 'source_text', 'strategy_weights'])
  expect(ctx.generations[0].source_text).toBeTruthy()
  await page.getByRole('button', { name: '采纳导入用例集 (1 条)' }).click()
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].cases[1]).toMatchObject({ name: '生成候选', submodule: '登录', feature_point: '身份验证', custom_field: '保留扩展数据' })
  expect(ctx.saves[0].cases[1]).not.toHaveProperty('id')
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
  await ctx.held.save.fulfill({ json: { items: ctx.saves[0].cases.map((item, i) => ({ ...item, id: item.id || `saved-${i}` })) } })
  await expect(page.getByRole('button', { name: '保存用例修改' })).toBeEnabled()
  ctx.holds.delete('save')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(2)
  expect(ctx.saves[0].cases[1]).not.toHaveProperty('id')
  expect(ctx.saves[1].cases[1]).toMatchObject({ id: 'saved-1', name: '保存期间的新编辑' })
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

test('确认操作等待正在保存的同一个请求，保存完成后只确认一次', async ({ page }) => {
  const ctx = await setup(page)
  await rename(page, '待确认版本')
  ctx.holds.add('save')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => !!ctx.held.save).toBe(true)
  await page.getByRole('button', { name: '确认入库用例集' }).click()
  expect(ctx.confirms).toEqual([])
  expect(ctx.saves).toHaveLength(1)
  await ctx.held.save.fulfill({ json: { items: ctx.saves[0].cases } })
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
  await ctx.held.save.fulfill({ json: { items: ctx.saves[0].cases } })
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
  await page.getByRole('button', { name: '推导候选用例 →' }).click()
  await page.getByRole('button', { name: '采纳导入用例集 (6 条)' }).click()
  await expect(page.getByText('✓ 6 大策略完备覆盖')).toBeVisible()
  await page.locator('.strategy-pill').filter({ hasText: '等价类' }).click()
  await expect(page.locator('.data-row')).toHaveCount(1)
  await rename(page, '修改等价类候选')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].cases[4]).toMatchObject({ name: '修改等价类候选', strategy: '等价类' })
  expect(ctx.saves[0].cases[5].strategy).toBe('状态迁移')
  ctx.rows.b[0].strategy = '等价'
  await page.locator('.file-node').filter({ hasText: '用例集B' }).click()
  await expect(page.locator('.data-row')).toContainText('等价类')
  await rename(page, '旧别名用例')
  await page.getByRole('button', { name: '保存用例修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(2)
  expect(ctx.saves[1].cases[0].strategy).toBe('等价类')
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
