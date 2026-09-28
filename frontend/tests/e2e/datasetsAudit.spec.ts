import { expect, test, type Page, type Route } from '@playwright/test'

/** 拦截生产页面的数据请求，验证草稿在失败转场后仍可编辑。 */
async function setup(page: Page, options: { goldQa?: boolean } = {}) {
  const datasets = ['a', 'b'].map(id => ({ id, name: `数据集${id.toUpperCase()}`, version: 1,
    row_count: 1, pending_complete_count: 0, metric: 'contain', owner: 'qa', column_schema: [], created_at: '2026-09-28T00:00:00Z' }))
  const rows: Record<string, Record<string, unknown>[]> = {
    a: [{ row_no: 1, question: 'A 原始问句', reference: 'A 答案', context: null }],
    b: [{ row_no: 1, question: 'B 原始问句', reference: 'B 答案', context: null }],
  }
  const saves: { id: string; rows: Record<string, unknown>[]; expectedVersion: number }[] = []
  const creations: string[] = []
  const uploads: string[] = []
  const metadataUpdates: string[] = []
  let failSave = true
  let failUpload = false
  let holdUpload = false
  let heldUpload: { route: Route; id: string } | null = null
  let holdSave = false
  let holdSaveBeforeCommit = false
  let heldSave: { route: Route; id: string; data: Record<string, unknown>[]; expectedVersion: number; commitOnRelease: boolean } | null = null
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
    if (parts[2] === 'datasets' && parts[4] === 'upload') {
      const id = parts[3]
      uploads.push(id)
      if (failUpload) return route.fulfill({ status: 400, json: { error: { code: 'VALIDATION', message: '上传失败' } } })
      if (holdUpload) {
        heldUpload = { route, id }
        holdUpload = false
        return
      }
      const dataset = datasets.find(item => item.id === id)
      if (dataset) {
        dataset.version++
        dataset.row_count = 1
      }
      rows[id] = [{ row_no: 1, question: '上传后问句', reference: '上传后答案', context: null }]
      return route.fulfill({ json: { version: dataset?.version, row_count: 1 } })
    }
    if (parts[2] === 'datasets' && parts[3] && !parts[4] && route.request().method() === 'PUT') {
      const dataset = datasets.find(item => item.id === parts[3])
      if (!dataset) return route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: '数据集不存在' } })
      Object.assign(dataset, route.request().postDataJSON())
      metadataUpdates.push(dataset.id)
      return route.fulfill({ json: dataset })
    }
    if (parts[2] === 'datasets' && parts[4] === 'rows') {
      const id = parts[3]
      if (route.request().method() === 'PUT') {
        const data = route.request().postDataJSON().rows
        const expectedVersion = Number(url.searchParams.get('expected_version'))
        saves.push({ id, rows: data, expectedVersion })
        if (failSave) return route.fulfill({ status: 400, json: { error: { code: 'VALIDATION', message: '保存失败' } } })
        const dataset = datasets.find(item => item.id === id)
        if (!dataset) return route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: '数据集不存在' } })
        if (dataset.version !== expectedVersion) {
          return route.fulfill({ status: 409, json: { code: 'CONCURRENCY', message: '数据集版本已变化' } })
        }
        if (holdSaveBeforeCommit) {
          heldSave = { route, id, data, expectedVersion, commitOnRelease: true }
          holdSaveBeforeCommit = false
          return
        }
        rows[id] = data
        dataset.version++
        if (holdSave) {
          heldSave = { route, id, data, expectedVersion, commitOnRelease: false }
          holdSave = false
          return
        }
        return route.fulfill({ json: { items: data, version: dataset.version } })
      }
      if (id === holdRowLoadId) {
        heldRowLoad = { route, id }
        holdRowLoadId = ''
        return
      }
      return route.fulfill({ json: { items: rows[id], version: datasets.find(item => item.id === id)?.version } })
    }
    return route.fulfill({ json: { items: [] } })
  })
  await page.goto('/tests/datasets-audit-fixture.html')
  await expect(page.locator('.data-row')).toHaveCount(1)
  return { saves, creations, uploads, metadataUpdates,
    allowSave: () => { failSave = false },
    overwriteOutsidePage: () => {
      datasets[0].version++
      rows.a = [{ row_no: 1, question: '外部上传问句', reference: '外部上传答案', context: null }]
    },
    deleteOutsidePage: () => {
      datasets.splice(datasets.findIndex(item => item.id === 'a'), 1)
      delete rows.a
    },
    serverRows: (id: string) => rows[id],
    failNextUpload: () => { failUpload = true },
    holdNextUpload: () => { holdUpload = true },
    isUploadHeld: () => heldUpload !== null,
    releaseUpload: async () => {
      if (!heldUpload) throw new Error('上传请求未挂起')
      const pending = heldUpload
      heldUpload = null
      const dataset = datasets.find(item => item.id === pending.id)
      if (dataset) {
        dataset.version++
        dataset.row_count = 1
      }
      rows[pending.id] = [{ row_no: 1, question: '上传后问句', reference: '上传后答案', context: null }]
      await pending.route.fulfill({ json: { version: dataset?.version, row_count: 1 } })
    },
    holdNextSave: () => { holdSave = true },
    holdNextSaveBeforeCommit: () => { holdSaveBeforeCommit = true },
    isSaveHeld: () => heldSave !== null,
    holdNextRowLoad: (id: string) => { holdRowLoadId = id },
    isRowLoadHeld: () => heldRowLoad !== null,
    releaseRowLoad: async () => {
      if (!heldRowLoad) throw new Error('行请求未挂起')
      const pending = heldRowLoad
      heldRowLoad = null
      await pending.route.fulfill({ json: { items: rows[pending.id], version: datasets.find(item => item.id === pending.id)?.version } })
    },
    releaseSave: async () => {
      if (!heldSave) throw new Error('保存请求未挂起')
      const pending = heldSave
      heldSave = null
      const dataset = datasets.find(item => item.id === pending.id)
      if (pending.commitOnRelease && dataset) {
        rows[pending.id] = pending.data
        dataset.version++
      }
      await pending.route.fulfill({ json: { items: pending.data, version: dataset?.version } })
    },
  }
}

async function openCurrentDatasetUpload(page: Page) {
  await page.locator('.file-node').filter({ hasText: '数据集A' }).click({ button: 'right' })
  await page.getByText('上传新版本 (v2)', { exact: true }).click()
}

async function chooseUploadFile(page: Page) {
  await page.locator('input[type="file"]').setInputFiles({ name: 'dataset.jsonl', mimeType: 'application/json',
    buffer: Buffer.from('{"question":"上传后问句","reference":"上传后答案"}\n') })
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
  expect(ctx.saves[1]).toMatchObject({ id: 'a', expectedVersion: 2, rows: [{ question: '保存期间的新编辑' }] })
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

test('保存期间 A 到 B 再到 A，旧响应不能提升重新加载行的版本', async ({ page }) => {
  const ctx = await setup(page)
  ctx.allowSave()
  await editQuestion(page, 'A 首次提交')
  ctx.holdNextSaveBeforeCommit()
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(ctx.isSaveHeld).toBe(true)
  await page.locator('.file-node').filter({ hasText: '数据集B' }).click()
  await page.getByRole('button', { name: '放弃修改' }).click()
  await page.locator('.file-node').filter({ hasText: '数据集A' }).click()
  await expect(page.locator('.data-row')).toContainText('A 原始问句')
  await editQuestion(page, 'A 返回后的新草稿')
  await ctx.releaseSave()
  await expect(page.locator('.data-row')).toContainText('A 返回后的新草稿')
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(2)
  expect(ctx.saves[1].expectedVersion).toBe(1)
  expect(ctx.serverRows('a')[0].question).toBe('A 首次提交')
  await expect(page.locator('.data-row')).toContainText('A 返回后的新草稿')
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

test('A 草稿覆盖上传成功后读取新版本，旧草稿不能再次保存', async ({ page }) => {
  const ctx = await setup(page)
  await editQuestion(page, 'A 未保存草稿')
  await openCurrentDatasetUpload(page)
  await expect(page.getByText('当前数据集有未保存的修改')).toBeVisible()
  await page.getByRole('button', { name: '继续覆盖上传' }).click()
  await chooseUploadFile(page)
  await page.getByRole('button', { name: '确认覆盖上传' }).click()
  await expect.poll(() => ctx.uploads).toEqual(['a'])
  await expect(page.locator('.data-row')).toContainText('上传后问句')
  await expect(page.locator('.data-row')).not.toContainText('A 未保存草稿')
  await expect(page.getByRole('button', { name: '保存当前修改' })).toBeDisabled()
  await page.keyboard.press('Control+s')
  expect(ctx.saves).toHaveLength(0)
  ctx.allowSave()
  await editQuestion(page, '新版本修改')
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0]).toMatchObject({ id: 'a', expectedVersion: 2, rows: [{ question: '新版本修改' }] })
})

test('取消或失败的覆盖上传仍保留 A 草稿', async ({ page }) => {
  const ctx = await setup(page)
  await editQuestion(page, 'A 未保存草稿')
  await openCurrentDatasetUpload(page)
  await page.getByRole('button', { name: '取消' }).click()
  await expect(page.locator('.data-row')).toContainText('A 未保存草稿')
  await openCurrentDatasetUpload(page)
  await page.getByRole('button', { name: '继续覆盖上传' }).click()
  ctx.failNextUpload()
  await chooseUploadFile(page)
  await page.getByRole('button', { name: '确认覆盖上传' }).click()
  await expect.poll(() => ctx.uploads).toEqual(['a'])
  await expect(page.locator('.data-row')).toContainText('A 未保存草稿')
  const uploadCancel = page.getByRole('button', { name: '取消' }).last()
  await expect(uploadCancel).toBeEnabled()
  await uploadCancel.click()
  await expect(page.getByRole('button', { name: '保存当前修改' })).toBeEnabled()
})

test('A 保存尚未完成时不能开始覆盖上传', async ({ page }) => {
  const ctx = await setup(page)
  ctx.allowSave()
  await editQuestion(page, 'A 正在保存')
  ctx.holdNextSave()
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(ctx.isSaveHeld).toBe(true)
  await openCurrentDatasetUpload(page)
  await expect(page.getByText('当前修改正在保存，请稍后再覆盖上传')).toBeVisible()
  await expect(page.getByRole('button', { name: '确认覆盖上传' })).toHaveCount(0)
  await ctx.releaseSave()
  await expect(page.getByRole('button', { name: '保存当前修改' })).toBeDisabled()
})

test('覆盖上传尚未完成时不能关闭弹窗或保存旧草稿', async ({ page }) => {
  const ctx = await setup(page)
  await editQuestion(page, 'A 待覆盖草稿')
  await openCurrentDatasetUpload(page)
  await page.getByRole('button', { name: '继续覆盖上传' }).click()
  await chooseUploadFile(page)
  ctx.holdNextUpload()
  await page.getByRole('button', { name: '确认覆盖上传' }).click()
  await expect.poll(ctx.isUploadHeld).toBe(true)
  await expect(page.getByRole('button', { name: '取消' }).last()).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(page.getByText('覆盖上传「数据集A」')).toBeVisible()
  await page.keyboard.press('Control+s')
  expect(ctx.saves).toHaveLength(0)
  await ctx.releaseUpload()
  await expect(page.locator('.data-row')).toContainText('上传后问句')
})

test('其他标签页覆盖上传后，旧草稿保存被拒且仍留在页面', async ({ page }) => {
  const ctx = await setup(page)
  ctx.allowSave()
  await editQuestion(page, '当前页旧草稿')
  ctx.overwriteOutsidePage()
  // 新建其他数据集触发列表刷新，仍必须用草稿原本的版本校验。
  await page.getByRole('button', { name: '上传数据集文件' }).click()
  await page.getByPlaceholder('例如：smoke-20 或 支付问答集').fill('新上传数据集')
  await chooseUploadFile(page)
  await page.getByRole('button', { name: '上传并创建' }).click()
  await expect.poll(() => ctx.uploads).toEqual(['new'])
  await expect(page.locator('.file-node').filter({ hasText: '新上传数据集' })).toBeVisible()
  await expect(page.locator('.data-row')).toContainText('当前页旧草稿')
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].expectedVersion).toBe(1)
  expect(ctx.serverRows('a')[0].question).toBe('外部上传问句')
  await expect(page.locator('.data-row')).toContainText('当前页旧草稿')
  await expect(page.getByRole('button', { name: '保存当前修改' })).toBeEnabled()
  await expect(page.getByText('数据集已由其他操作更新，草稿仍保留')).toBeVisible()
})

test('脏草稿修改评分指标后仍沿用旧版本，不能覆盖外部新行', async ({ page }) => {
  const ctx = await setup(page)
  ctx.allowSave()
  await editQuestion(page, 'A 元信息前草稿')
  ctx.overwriteOutsidePage()
  await page.getByLabel('选择主评分指标').selectOption('exact')
  await expect.poll(() => ctx.metadataUpdates).toEqual(['a'])
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].expectedVersion).toBe(1)
  expect(ctx.serverRows('a')[0].question).toBe('外部上传问句')
  await expect(page.locator('.data-row')).toContainText('A 元信息前草稿')
})

test('未编辑的旧行在元信息更新后仍用行版本校验', async ({ page }) => {
  const ctx = await setup(page)
  ctx.allowSave()
  ctx.overwriteOutsidePage()
  await page.getByLabel('选择主评分指标').selectOption('exact')
  await expect.poll(() => ctx.metadataUpdates).toEqual(['a'])
  await editQuestion(page, 'A 元信息后旧行编辑')
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].expectedVersion).toBe(1)
  expect(ctx.serverRows('a')[0].question).toBe('外部上传问句')
  await expect(page.locator('.data-row')).toContainText('A 元信息后旧行编辑')
})

test('活动数据集被外部删除后刷新列表仍保留旧草稿，保存不误写其他集', async ({ page }) => {
  const ctx = await setup(page)
  ctx.allowSave()
  await editQuestion(page, 'A 删除前草稿')
  ctx.deleteOutsidePage()
  await page.getByRole('button', { name: '上传数据集文件' }).click()
  await page.getByPlaceholder('例如：smoke-20 或 支付问答集').fill('新上传数据集')
  await chooseUploadFile(page)
  await page.getByRole('button', { name: '上传并创建' }).click()
  await expect(page.locator('.file-node').filter({ hasText: '新上传数据集' })).toBeVisible()
  await expect(page.locator('.main-dataset-title')).toContainText('数据集A（已删除，草稿待导出）')
  await expect(page.locator('.data-row')).toContainText('A 删除前草稿')
  await expect(page.getByText('当前数据集已被删除，草稿仍保留')).toBeVisible()
  await page.getByRole('button', { name: '保存当前修改' }).click()
  await expect.poll(() => ctx.saves.length).toBe(1)
  expect(ctx.saves[0].id).toBe('a')
  expect(ctx.serverRows('b')[0].question).toBe('B 原始问句')
  await expect(page.locator('.data-row')).toContainText('A 删除前草稿')
  await expect(page.getByRole('button', { name: '保存当前修改' })).toBeEnabled()
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
