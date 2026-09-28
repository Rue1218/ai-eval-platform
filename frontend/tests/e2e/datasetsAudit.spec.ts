import { expect, test, type Page, type Route } from '@playwright/test'

/** 拦截生产页面的数据请求，验证草稿在失败转场后仍可编辑。 */
async function setup(page: Page, options: { goldQa?: boolean } = {}) {
  const datasets = ['a', 'b'].map(id => ({ id, name: `数据集${id.toUpperCase()}`, version: 1,
    row_count: 1, pending_complete_count: 0, metric: 'contain', owner: 'qa', column_schema: [], created_at: '2026-09-28T00:00:00Z' }))
  const rows: Record<string, Record<string, unknown>[]> = {
    a: [{ row_no: 1, question: 'A 原始问句', reference: 'A 答案', context: null }],
    b: [{ row_no: 1, question: 'B 原始问句', reference: 'B 答案', context: null }],
  }
  const saves: { id: string; rows: Record<string, unknown>[] }[] = []
  const creations: string[] = []
  let failSave = true
  let holdSave = false
  let heldSave: { route: Route; data: Record<string, unknown>[] } | null = null
  let holdRowLoadId = ''
  let heldRowLoad: { route: Route; id: string } | null = null
  await page.route(/^http:\/\/127\.0\.0\.1:5273\/api\//, route => {
    const url = new URL(route.request().url())
    const parts = url.pathname.split('/')
    if (options.goldQa && url.pathname === '/api/kb') return route.fulfill({ json: { items: [{ id: 'kb-1' }] } })
    if (options.goldQa && url.pathname === '/api/kb/kb-1/gold-qa') {
      return route.fulfill({ json: { items: [{ id: 'qa-1', kb_id: 'kb-1', name: '黄金QA', version: 1,
        row_count: 2, owner: 'qa', created_at: '2026-09-28T00:00:00Z' }] } })
    }
    if (url.pathname === '/api/datasets') {
      if (route.request().method() === 'POST') {
        const name = route.request().postDataJSON().name
        creations.push(name)
        const created = { ...datasets[0], id: 'new', name, row_count: 0 }
        datasets.push(created)
        rows.new = []
        return route.fulfill({ json: created })
      }
      return route.fulfill({ json: { items: datasets } })
    }
    if (parts[2] === 'datasets' && parts[4] === 'rows') {
      const id = parts[3]
      if (route.request().method() === 'PUT') {
        const data = route.request().postDataJSON().rows
        saves.push({ id, rows: data })
        if (failSave) return route.fulfill({ status: 400, json: { error: { code: 'VALIDATION', message: '保存失败' } } })
        rows[id] = data
        if (holdSave) {
          heldSave = { route, data }
          holdSave = false
          return
        }
        return route.fulfill({ json: { items: data } })
      }
      if (id === holdRowLoadId) {
        heldRowLoad = { route, id }
        holdRowLoadId = ''
        return
      }
      return route.fulfill({ json: { items: rows[id] } })
    }
    return route.fulfill({ json: { items: [] } })
  })
  await page.goto('/tests/datasets-audit-fixture.html')
  await expect(page.locator('.data-row')).toHaveCount(1)
  return { saves, creations,
    allowSave: () => { failSave = false },
    holdNextSave: () => { holdSave = true },
    isSaveHeld: () => heldSave !== null,
    holdNextRowLoad: (id: string) => { holdRowLoadId = id },
    isRowLoadHeld: () => heldRowLoad !== null,
    releaseRowLoad: async () => {
      if (!heldRowLoad) throw new Error('行请求未挂起')
      const pending = heldRowLoad
      heldRowLoad = null
      await pending.route.fulfill({ json: { items: rows[pending.id] } })
    },
    releaseSave: async () => {
      if (!heldSave) throw new Error('保存请求未挂起')
      const pending = heldSave
      heldSave = null
      await pending.route.fulfill({ json: { items: pending.data } })
    },
  }
}

async function editQuestion(page: Page, value: string) {
  const cell = page.locator('.data-row').first().locator('td').nth(2)
  await cell.click()
  await cell.locator('input').fill(value)
  await cell.locator('input').press('Tab')
}

test('保存失败不能切换数据集，当前草稿继续可保存', async ({ page }) => {
  const ctx = await setup(page)
  await editQuestion(page, 'A 待保存草稿')
  await page.locator('.file-node').filter({ hasText: '数据集B' }).click()
  await page.getByRole('button', { name: '保存并切换' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  await expect(page.locator('.main-dataset-title')).toHaveText('数据集A')
  await expect(page.locator('.data-row')).toContainText('A 待保存草稿')
  await expect(page.getByRole('button', { name: '保存当前修改' })).toBeEnabled()
})

test('直接新建遇到保存失败不创建新集，也不丢当前草稿', async ({ page }) => {
  const ctx = await setup(page)
  await editQuestion(page, 'A 待保存草稿')
  await page.locator('.folder-node').first().click({ button: 'right' })
  await page.getByText('新建空数据集', { exact: true }).click()
  await page.getByRole('button', { name: '保存并新建' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.creations).toHaveLength(0)
  await expect(page.locator('.main-dataset-title')).toHaveText('数据集A')
  await expect(page.locator('.data-row')).toContainText('A 待保存草稿')
  await expect(page.getByRole('button', { name: '保存当前修改' })).toBeEnabled()
})

test('保存响应迟到时不清除保存期间的新编辑', async ({ page }) => {
  const ctx = await setup(page)
  ctx.allowSave()
  await editQuestion(page, '首次提交内容')
  ctx.holdNextSave()
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(ctx.isSaveHeld).toBe(true)
  await editQuestion(page, '保存期间的新编辑')
  await ctx.releaseSave()
  await expect(page.locator('.data-row')).toContainText('保存期间的新编辑')
  await expect(page.getByRole('button', { name: '保存当前修改' })).toBeEnabled()
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(2)
  expect(ctx.saves[0]).toMatchObject({ id: 'a', rows: [{ question: '首次提交内容' }] })
  expect(ctx.saves[1]).toMatchObject({ id: 'a', rows: [{ question: '保存期间的新编辑' }] })
})

test('切换到 B 后，A 的迟到保存响应不清除 B 草稿', async ({ page }) => {
  const ctx = await setup(page)
  ctx.allowSave()
  await editQuestion(page, 'A 首次提交')
  ctx.holdNextSave()
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(ctx.isSaveHeld).toBe(true)
  await page.locator('.file-node').filter({ hasText: '数据集B' }).click()
  await page.getByRole('button', { name: '放弃修改' }).click()
  await expect(page.locator('.main-dataset-title')).toHaveText('数据集B')
  await editQuestion(page, 'B 新草稿')
  await ctx.releaseSave()
  await expect(page.locator('.data-row')).toContainText('B 新草稿')
  await expect(page.getByRole('button', { name: '保存当前修改' })).toBeEnabled()
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(2)
  expect(ctx.saves[1]).toMatchObject({ id: 'b', rows: [{ question: 'B 新草稿' }] })
})

test('切换到 B 后，A 的迟到行数据不覆盖 B 草稿', async ({ page }) => {
  const ctx = await setup(page)
  await page.locator('.file-node').filter({ hasText: '数据集B' }).click()
  await expect(page.locator('.data-row')).toContainText('B 原始问句')
  ctx.holdNextRowLoad('a')
  await page.locator('.file-node').filter({ hasText: '数据集A' }).click()
  await expect.poll(ctx.isRowLoadHeld).toBe(true)
  await page.locator('.file-node').filter({ hasText: '数据集B' }).click()
  await expect(page.locator('.data-row')).toContainText('B 原始问句')
  await editQuestion(page, 'B 待保存草稿')
  await ctx.releaseRowLoad()
  await expect(page.locator('.main-dataset-title')).toHaveText('数据集B')
  await expect(page.locator('.data-row')).toContainText('B 待保存草稿')
  await expect(page.getByRole('button', { name: '保存当前修改' })).toBeEnabled()
})

test('放弃 A 草稿切换 B 时，等待 B 行数据期间不显示 A 的旧行', async ({ page }) => {
  const ctx = await setup(page)
  await editQuestion(page, 'A 待放弃草稿')
  ctx.holdNextRowLoad('b')
  await page.locator('.file-node').filter({ hasText: '数据集B' }).click()
  await page.getByRole('button', { name: '放弃修改' }).click()
  await expect.poll(ctx.isRowLoadHeld).toBe(true)
  await expect(page.locator('.main-dataset-title')).toHaveText('数据集B')
  await expect(page.locator('.data-row')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '保存当前修改' })).toBeDisabled()
  await ctx.releaseRowLoad()
  await expect(page.locator('.data-row')).toContainText('B 原始问句')
})

test('上传新数据集后保留已选中的黄金 QA 资产', async ({ page }) => {
  const ctx = await setup(page, { goldQa: true })
  await page.locator('.file-node').filter({ hasText: '黄金QA' }).click()
  await expect(page.locator('.main-dataset-title')).toHaveText('黄金QA')
  await page.getByRole('button', { name: '上传数据集文件' }).click()
  await page.getByPlaceholder('例如：smoke-20 或 支付问答集').fill('新上传数据集')
  await page.locator('input[type="file"]').setInputFiles({ name: 'dataset.jsonl', mimeType: 'application/json',
    buffer: Buffer.from('{"question":"Q","reference":"A"}\n') })
  await page.getByRole('button', { name: '上传并创建' }).click()
  await expect.poll(() => ctx.creations.length).toBe(1)
  await expect(page.locator('.main-dataset-title')).toHaveText('黄金QA')
  await expect(page.locator('.asset-type-badge')).toHaveText('黄金 QA')
})
