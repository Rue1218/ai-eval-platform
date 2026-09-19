import { test, expect, type Page, type Route } from '@playwright/test'

/** 工作区 HTTP 夹具；不连接真实账号、磁盘或后端。 */
async function setup(page: Page) {
  const saves: { workspace: string; content: string }[] = []
  const held: Record<string, Route> = {}
  const holds = new Set<string>()
  const names = ['one.txt', 'two.txt']
  await page.route(/\/api\/workspaces(?:\/|\?|$)/, async route => {
    const url = new URL(route.request().url())
    const parts = url.pathname.split('/')
    if (url.pathname === '/api/workspaces') {
      const ids = url.searchParams.get('offset') === '2' ? ['w3'] : ['w1', 'w2']
      return route.fulfill({ json: { items: ids.map(id => ({ id, name: id, deleted: false, quota_bytes: 1024 ** 3, folder: { total_bytes: 1024 ** 2, file_count: 2 } })), total: 3 } })
    }
    if (url.pathname.endsWith('/tree')) return route.fulfill({ json: { tree: names.map(name => ({ name, path: name, kind: 'file', size: 8 })) } })
    if (url.pathname.endsWith('/content')) {
      if (route.request().method() === 'PUT') {
        saves.push({ workspace: parts[3], content: route.request().postDataJSON().content })
        if (holds.has('save')) { held.save = route; return }
        return route.fulfill({ json: { ok: true } })
      }
      const name = url.searchParams.get('path')!
      if (holds.has(name)) { held[name] = route; return }
      return route.fulfill({ json: file(name) })
    }
    return route.fulfill({ json: {} })
  })
  await page.goto('/tests/workspace-audit-fixture.html')
  await expect(page.locator('.workspace-select')).toHaveValue('w1')
  return { saves, holds, held }
}

/** 文件读取响应包含与文件名可区分的内容，便于验证异步覆盖。 */
function file(name: string) { return { path: name, name, content: `body:${name}`, size: 8, is_binary: false, is_large: false } }

/** 等待网络回调后的 Vue 渲染，避免在迟到响应尚未处理时提前通过断言。 */
async function settled(page: Page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}

test('取消工作区切换后保存仍写原工作区，并保留未保存内容', async ({ page }) => {
  const ctx = await setup(page)
  await page.locator('.tree-node-row').filter({ hasText: 'one.txt' }).click()
  await page.locator('.editor-textarea').fill('edited')
  await page.locator('.workspace-select').selectOption('w2')
  await page.getByRole('button', { name: '留在当前', exact: true }).click()
  await expect(page.locator('.workspace-select')).toHaveValue('w1')
  await expect(page.locator('.editor-textarea')).toHaveValue('edited')
  await page.locator('.editor-textarea').press('Control+s')
  await expect.poll(() => ctx.saves).toEqual([{ workspace: 'w1', content: 'edited' }])
})

test('先发后到的文件读取不能覆盖后选文件', async ({ page }) => {
  const ctx = await setup(page)
  ctx.holds.add('one.txt')
  await page.locator('.tree-node-row').filter({ hasText: 'one.txt' }).click()
  await expect.poll(() => !!ctx.held['one.txt']).toBe(true)
  await page.locator('.tree-node-row').filter({ hasText: 'two.txt' }).click()
  await expect(page.locator('.editor-textarea')).toHaveValue('body:two.txt')
  await ctx.held['one.txt'].fulfill({ json: file('one.txt') })
  await settled(page)
  await expect(page.locator('.editor-textarea')).toHaveValue('body:two.txt')
})

test('保存期间的新编辑仍标记未保存', async ({ page }) => {
  const ctx = await setup(page)
  await page.locator('.tree-node-row').filter({ hasText: 'one.txt' }).click()
  await page.locator('.editor-textarea').fill('first edit')
  ctx.holds.add('save')
  await page.locator('.editor-textarea').press('Control+s')
  await expect.poll(() => !!ctx.held.save).toBe(true)
  await page.locator('.editor-textarea').fill('second edit')
  await ctx.held.save.fulfill({ json: { ok: true } })
  await settled(page)
  await expect(page.locator('.dirty-badge')).toBeVisible()
  ctx.holds.delete('save')
  await page.locator('.editor-textarea').press('Control+s')
  await expect.poll(() => ctx.saves.length).toBe(2)
  expect(ctx.saves[1]).toEqual({ workspace: 'w1', content: 'second edit' })
})

test('工作区选择器继续加载后续分页', async ({ page }) => {
  await setup(page)
  await expect(page.locator('.workspace-select option')).toHaveCount(3)
  await expect(page.locator('.meter-value')).not.toContainText('100 MB')
  await expect(page.locator('.meter-value')).toContainText('1.0 GB')
})

test('确认切换清除旧文件，下一次保存归属新工作区', async ({ page }) => {
  const ctx = await setup(page)
  await page.locator('.tree-node-row').filter({ hasText: 'one.txt' }).click()
  await page.locator('.editor-textarea').fill('discarded')
  await page.locator('.workspace-select').selectOption('w2')
  await page.getByRole('button', { name: '放弃修改并切换', exact: true }).click()
  await expect(page.locator('.workspace-select')).toHaveValue('w2')
  await expect(page.locator('.editor-textarea')).toHaveCount(0)
  await page.locator('.tree-node-row').filter({ hasText: 'two.txt' }).click()
  await page.locator('.editor-textarea').fill('new workspace edit')
  await page.locator('.editor-textarea').press('Control+s')
  await expect.poll(() => ctx.saves).toEqual([{ workspace: 'w2', content: 'new workspace edit' }])
})
