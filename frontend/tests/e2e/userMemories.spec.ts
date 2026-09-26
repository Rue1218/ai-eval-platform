import { test, expect, type Page, type Route } from '@playwright/test'
import type { AgentMemory } from '../../src/api/agentMemories'

/** 仅模拟业务 HTTP，页面、路由、HTTP 客户端与乐观锁交互都使用真实实现。 */
async function setup(page: Page, initial?: AgentMemory[]) {
  const ctx = {
    rows: initial || [
      memory('c02e1970-45cb-496c-8f3f-7bf3e39b2d51', '回答格式', '请先给结论，再列出验证步骤。', 'preference'),
      memory('6bbcaf75-9ad9-4a1c-b779-113f602e7425', '评测项目背景', '默认比较准确率、延迟和 token 预算。', 'fact', 'w1'),
      memory('fa9d6677-545d-4b43-aeae-3b54d23b7782', '旧项目资料', '历史范围不会自动转为全局。', 'fact', 'deleted-workspace'),
    ],
    writes: [] as { method: string; body: any; url: string }[],
    queries: [] as URL[],
    holdSave: false,
    held: null as Route | null,
    conflict: false,
    workspaceDeleted: false,
    workspaceFailed: false,
    workspaceReads: 0,
    memoryUnavailable: false,
  }
  await page.route('https://fonts.googleapis.com/**', route => route.fulfill({ contentType: 'text/css', body: '' }))
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const method = route.request().method()
    if (url.pathname === '/api/auth/me') return route.fulfill({ json: { id: 'u', username: '测试成员', role: 'member' } })
    if (url.pathname === '/api/workspaces') {
      ctx.workspaceReads++
      if (ctx.workspaceFailed) return route.fulfill({ status: 503, json: { code: 'UPSTREAM', message: '目录暂时不可用' } })
      const items = ctx.workspaceDeleted ? [] : [{ id: 'w1', name: '评测项目', owner_id: 'u', deleted: false, folder: null }]
      return route.fulfill({ json: { items, total: items.length } })
    }
    if (!url.pathname.startsWith('/api/agent/memories')) return route.fulfill({ json: {} })
    if (method === 'GET') {
      ctx.queries.push(url)
      const q = url.searchParams.get('q') || ''
      const scope = url.searchParams.get('workspace_id')
      const rows = ctx.rows.filter(item => (item.title + item.content).includes(q) && (scope === null || (item.workspace_id || '') === scope))
      const offset = Number(url.searchParams.get('offset'))
      return route.fulfill({ json: { items: rows.slice(offset, offset + 50), total: rows.length } })
    }
    const body = method === 'DELETE' ? null : route.request().postDataJSON()
    ctx.writes.push({ method, body, url: url.toString() })
    if (ctx.holdSave) { ctx.held = route; return }
    const id = url.pathname.split('/').at(-1)
    if (ctx.workspaceDeleted && body?.workspace_id === 'w1') {
      return route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: '所选范围不可用' } })
    }
    if (ctx.memoryUnavailable) {
      ctx.rows = ctx.rows.filter(item => item.id !== id)
      return route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: '记录不可访问' } })
    }
    if (ctx.conflict) {
      ctx.rows = ctx.rows.map(item => item.id === id ? { ...item, title: '其他窗口已更正', version: item.version + 1 } : item)
      return route.fulfill({ status: 409, json: { code: 'CONCURRENCY', message: '记忆已更新，请刷新' } })
    }
    if (method === 'DELETE') {
      ctx.rows = ctx.rows.filter(item => item.id !== id)
      return route.fulfill({ status: 204 })
    }
    const saved = { ...memory(id === 'memories' ? `new-${ctx.writes.length}` : id!, body.title, body.content, body.category, body.workspace_id), version: (body.version || 0) + 1 }
    ctx.rows = method === 'POST' ? [saved, ...ctx.rows] : ctx.rows.map(item => item.id === id ? saved : item)
    return route.fulfill({ json: saved })
  })
  await page.goto('/memories')
  await expect(page.getByRole('heading', { name: '我的记忆', exact: true })).toBeVisible()
  await expect(page.locator('.memory-item')).toHaveCount(Math.min(ctx.rows.length, 50))
  await expect(page.locator('.n-spin-body')).toHaveCount(0)
  return ctx
}

/** 来源、版本和范围均接近真实返回值，包含失效工作区的保留记录。 */
function memory(id: string, title: string, content: string, category: AgentMemory['category'] = 'fact', workspace: string | null = null): AgentMemory {
  return { id, title, content, category, workspace_id: workspace, workspace_name: workspace === 'w1' ? '评测项目' : null, version: 1, source_id: `manual:${id}`, created_at: '2026-09-26T02:00:00Z', updated_at: '2026-09-26T02:00:00Z' }
}

/** 使用固定字段标签访问真实 Naive UI 控件。 */
function editor(page: Page) { return page.locator('.memory-modal').filter({ has: page.locator('.n-form') }) }

test('主路由入口及宽窄屏展示正常，资料保留失效范围', async ({ page }, testInfo) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width: 1440, height: 1000 })
  await setup(page)
  await expect(page.getByRole('link', { name: '我的记忆', exact: true })).toHaveAttribute('href', '/memories')
  await expect(page.getByText('仅本人私有对话使用', { exact: true })).toBeVisible()
  await expect(page.locator('.memory-item').filter({ hasText: '旧项目资料' })).toContainText('工作区：已不可用')
  await page.screenshot({ path: testInfo.outputPath('memories-wide.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.locator('.sidebar').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
  await expect(page.getByRole('heading', { name: '我的记忆', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(await page.locator('.memory-source').evaluateAll(elements => elements.every(element => element.getBoundingClientRect().right <= innerWidth && element.scrollWidth <= element.clientWidth))).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('memories-narrow.png'), fullPage: true })
  expect(errors).toEqual([])
})

test('用户主动创建、更正、按版本删除完整闭环', async ({ page }) => {
  const ctx = await setup(page)
  await page.getByRole('button', { name: '新建记忆', exact: true }).click()
  await editor(page).getByPlaceholder('为这条记忆起一个清楚的名字').fill('接口规范')
  await editor(page).getByPlaceholder('写下希望在以后对话中使用的偏好或事实').fill('token 预算按输入和输出分开记录。')
  await expect(editor(page)).toContainText('未经系统核实')
  await page.getByRole('button', { name: '保存记忆', exact: true }).click()
  await expect(page.locator('.memory-item').filter({ hasText: '接口规范' })).toBeVisible()
  expect(ctx.writes[0].body).toEqual({ title: '接口规范', content: 'token 预算按输入和输出分开记录。', category: 'fact', workspace_id: null })
  await page.locator('.memory-item').filter({ hasText: '接口规范' }).getByRole('button', { name: '查看 / 更正' }).click()
  await editor(page).getByPlaceholder('写下希望在以后对话中使用的偏好或事实').fill('更正后的接口约定')
  await page.getByRole('button', { name: '保存更正', exact: true }).click()
  await expect(page.locator('.memory-item').filter({ hasText: '接口规范' })).toContainText('更正后的接口约定')
  expect(ctx.writes[1].body.version).toBe(1)
  await page.locator('.memory-item').filter({ hasText: '接口规范' }).getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.locator('.delete-modal')).toContainText('不会改写已有聊天记录')
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.locator('.memory-item').filter({ hasText: '接口规范' })).toHaveCount(0)
  expect(new URL(ctx.writes[2].url).searchParams.get('version')).toBe('2')
})

test('搜索、全局筛选和后续分页都由接口查询', async ({ page }) => {
  const ctx = await setup(page, Array.from({ length: 51 }, (_, index) => memory(`m${index}`, `资料${index}`, '分页内容')))
  await page.locator('.n-pagination-item').filter({ hasText: /^2$/ }).click()
  await expect(page.locator('.memory-item')).toHaveCount(1)
  expect(ctx.queries.at(-1)!.searchParams.get('offset')).toBe('50')
  await page.getByPlaceholder('搜索标题或内容').fill('资料50')
  await page.locator('[aria-label="筛选工作区"]').click()
  await page.locator('.n-base-select-option').filter({ hasText: '仅全局记忆' }).click()
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await expect.poll(() => ctx.queries.at(-1)!.searchParams.get('q')).toBe('资料50')
  expect(ctx.queries.at(-1)!.searchParams.get('workspace_id')).toBe('')
  expect(ctx.queries.at(-1)!.searchParams.get('offset')).toBe('0')
  await expect(page.locator('.memory-item')).toContainText('资料50')
})

test('旧版本更正冲突保留草稿、刷新列表且不能重试覆盖', async ({ page }) => {
  const ctx = await setup(page)
  ctx.conflict = true
  await page.locator('.memory-item').first().getByRole('button', { name: '查看 / 更正' }).click()
  await editor(page).getByPlaceholder('写下希望在以后对话中使用的偏好或事实').fill('当前未提交草稿')
  await page.getByRole('button', { name: '保存更正', exact: true }).click()
  await expect(editor(page)).toContainText('当前草稿仍保留')
  await expect(editor(page).getByPlaceholder('写下希望在以后对话中使用的偏好或事实')).toHaveValue('当前未提交草稿')
  await expect(page.getByRole('button', { name: '保存更正', exact: true })).toBeDisabled()
  await expect(page.locator('.memory-item').first()).toContainText('其他窗口已更正')
  expect(ctx.writes).toHaveLength(1)
})

test('删除遇到版本冲突刷新列表，不自动删除新版本', async ({ page }) => {
  const ctx = await setup(page)
  ctx.conflict = true
  await page.locator('.memory-item').first().getByRole('button', { name: '删除', exact: true }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.locator('.delete-modal')).toHaveCount(0)
  await expect(page.locator('.memory-item').first()).toContainText('其他窗口已更正')
  await expect(page.getByText('记忆已更新或删除，请查看刷新后的列表再操作', { exact: true })).toBeVisible()
  expect(ctx.writes).toHaveLength(1)
  expect(new URL(ctx.writes[0].url).searchParams.get('version')).toBe('1')
})

test('失效工作区阻止保存，只有明确选择全局才发送 null', async ({ page }) => {
  const ctx = await setup(page)
  await page.locator('.memory-item').filter({ hasText: '旧项目资料' }).getByRole('button', { name: '查看 / 更正' }).click()
  await expect(editor(page)).toContainText('不会自动转为全局')
  await expect(page.getByRole('button', { name: '保存更正', exact: true })).toBeDisabled()
  await editor(page).locator('[aria-label="记忆使用范围"]').click()
  await page.locator('.n-base-select-option').filter({ hasText: '全局 · 本人的私有对话' }).click()
  await page.getByRole('button', { name: '保存更正', exact: true }).click()
  await expect.poll(() => ctx.writes.length).toBe(1)
  expect(ctx.writes[0].body.workspace_id).toBeNull()
})

for (const creating of [false, true]) {
  test(`${creating ? '新建' : '更正'}时工作区动态失效后保留草稿，当前编辑器可明确改选范围重试`, async ({ page }) => {
    const ctx = await setup(page)
    if (creating) {
      await page.getByRole('button', { name: '新建记忆', exact: true }).click()
      await editor(page).getByPlaceholder('为这条记忆起一个清楚的名字').fill('新建草稿')
      await editor(page).locator('[aria-label="记忆使用范围"]').click()
      await page.locator('.n-base-select-option').filter({ hasText: '评测项目' }).click()
    } else {
      await page.locator('.memory-item').filter({ hasText: '评测项目背景' }).getByRole('button', { name: '查看 / 更正' }).click()
    }
    const content = editor(page).getByPlaceholder('写下希望在以后对话中使用的偏好或事实')
    await content.fill('注销后仍应保留的草稿')
    ctx.workspaceDeleted = true
    const submit = editor(page).locator('button').filter({ hasText: creating ? '保存记忆' : '保存更正' })
    await submit.click()
    await expect(editor(page)).toContainText('原工作区已不可用')
    await expect(editor(page)).not.toContainText('这条记忆已被更新或删除')
    await expect(content).toHaveValue('注销后仍应保留的草稿')
    await expect(submit).toBeDisabled()
    expect(ctx.workspaceReads).toBe(2)
    expect(ctx.writes.map(write => write.body.workspace_id)).toEqual(['w1'])
    await editor(page).locator('[aria-label="记忆使用范围"]').click()
    await page.locator('.n-base-select-option').filter({ hasText: '全局 · 本人的私有对话' }).click()
    await expect(submit).toBeEnabled()
    await submit.click()
    await expect(editor(page)).toHaveCount(0)
    expect(ctx.writes.map(write => write.body.workspace_id)).toEqual(['w1', null])
    expect(ctx.writes[1].body.content).toBe('注销后仍应保留的草稿')
    if (!creating) expect(ctx.writes[1].body.version).toBe(1)
  })
}

test('真正记忆不可访问的404继续保护旧版本，不误判为范围失效', async ({ page }) => {
  const ctx = await setup(page)
  await page.locator('.memory-item').filter({ hasText: '评测项目背景' }).getByRole('button', { name: '查看 / 更正' }).click()
  const content = editor(page).getByPlaceholder('写下希望在以后对话中使用的偏好或事实')
  await content.fill('不可访问后仍保留的草稿')
  ctx.memoryUnavailable = true
  await page.getByRole('button', { name: '保存更正', exact: true }).click()
  await expect(editor(page)).toContainText('这条记忆已被更新或删除')
  await expect(editor(page)).not.toContainText('原工作区已不可用')
  await expect(content).toHaveValue('不可访问后仍保留的草稿')
  await editor(page).locator('[aria-label="记忆使用范围"]').click()
  await page.locator('.n-base-select-option').filter({ hasText: '全局 · 本人的私有对话' }).click()
  await expect(page.getByRole('button', { name: '保存更正', exact: true })).toBeDisabled()
  expect(ctx.writes).toHaveLength(1)
})

test('范围复验遇到网络故障时可在编辑器重试且保留草稿和版本', async ({ page }) => {
  const ctx = await setup(page)
  await page.locator('.memory-item').filter({ hasText: '评测项目背景' }).getByRole('button', { name: '查看 / 更正' }).click()
  const content = editor(page).getByPlaceholder('写下希望在以后对话中使用的偏好或事实')
  await content.fill('网络故障期间保留的草稿')
  ctx.workspaceDeleted = true
  ctx.workspaceFailed = true
  await page.getByRole('button', { name: '保存更正', exact: true }).click()
  await expect(editor(page)).toContainText('工作区加载失败')
  await expect(page.getByRole('button', { name: '保存更正', exact: true })).toBeDisabled()
  await expect(content).toHaveValue('网络故障期间保留的草稿')
  ctx.workspaceFailed = false
  await editor(page).getByRole('button', { name: '重试加载工作区', exact: true }).click()
  await expect(editor(page)).toContainText('原工作区已不可用')
  await expect(editor(page)).not.toContainText('工作区加载失败')
  await expect(content).toHaveValue('网络故障期间保留的草稿')
  expect(ctx.writes).toHaveLength(1)
  await editor(page).locator('[aria-label="记忆使用范围"]').click()
  await page.locator('.n-base-select-option').filter({ hasText: '全局 · 本人的私有对话' }).click()
  await page.getByRole('button', { name: '保存更正', exact: true }).click()
  await expect(editor(page)).toHaveCount(0)
  expect(ctx.writes[1].body).toMatchObject({ content: '网络故障期间保留的草稿', version: 1, workspace_id: null })
})

test('保存等待期间禁用提交、输入和关闭，避免重复或目标变化', async ({ page }) => {
  const ctx = await setup(page)
  ctx.holdSave = true
  await page.getByRole('button', { name: '新建记忆', exact: true }).click()
  await editor(page).getByPlaceholder('为这条记忆起一个清楚的名字').fill('待保存')
  await editor(page).getByPlaceholder('写下希望在以后对话中使用的偏好或事实').fill('固定提交快照')
  await page.getByRole('button', { name: '保存记忆', exact: true }).click()
  await expect.poll(() => !!ctx.held).toBe(true)
  await expect(editor(page).locator('button').filter({ hasText: '保存记忆' })).toBeDisabled()
  await expect(editor(page).getByPlaceholder('为这条记忆起一个清楚的名字')).toBeDisabled()
  await expect(editor(page).getByRole('button', { name: '取消', exact: true })).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(editor(page)).toBeVisible()
  expect(ctx.writes).toHaveLength(1)
  await ctx.held!.fulfill({ json: memory('new', '待保存', '固定提交快照') })
  await expect(editor(page)).toHaveCount(0)
})
