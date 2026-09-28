import { expect, test } from '@playwright/test'

const tasks = Array.from({ length: 60 }, (_, index) => ({
  id: `task-${String(index + 1).padStart(3, '0')}`,
  kind: 'testcase',
  status: 'succeeded',
  creator: 'tester',
  created_by: 'u',
  created_at: '2026-09-28T00:00:00Z',
  config: { kind: 'testcase' },
  events: [],
}))

test.beforeEach(async ({ page }) => {
  page.on('pageerror', error => console.log('页面异常：', error.message))
  page.on('console', entry => { if (entry.type() === 'error') console.log('浏览器错误：', entry.text()) })
  await page.route('https://fonts.googleapis.com/**', route => route.fulfill({ contentType: 'text/css', body: '' }))
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) { await route.continue(); return }
    if (url.pathname === '/api/auth/me') {
      await route.fulfill({ json: { id: 'u', username: 'tester', role: 'admin' } })
    } else if (url.pathname === '/api/tasks') {
      const offset = Number(url.searchParams.get('offset') || 0)
      const limit = Number(url.searchParams.get('limit') || 50)
      await route.fulfill({ json: { items: tasks.slice(offset, offset + limit), total: tasks.length } })
    } else if (url.pathname.startsWith('/api/tasks/')) {
      const id = url.pathname.split('/')[3]
      const task = tasks.find(item => item.id === id)
      await route.fulfill({ status: task ? 200 : 404, json: task || { code: 'NOT_FOUND', message: '任务不存在' } })
    } else {
      await route.fulfill({ json: {} })
    }
  })
})

test('任务列表按服务端分页显示历史任务，不展示虚构巡检数据', async ({ page }) => {
  await page.goto('/tasks')
  await expect(page.getByText('第 1 页 · 共 60 项')).toBeVisible()
  await expect(page.getByText('task-060', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.getByText('第 2 页 · 共 60 项')).toBeVisible()
  await expect(page.getByText('task-060', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('Worker 节点在线 8/10')).toHaveCount(0)
  await expect(page.getByText('AI 巡检诊断')).toHaveCount(0)
})

test('不在当前分页的任务深链仍可直读详情', async ({ page }) => {
  await page.goto('/tasks?id=task-060')
  await expect(page.getByText('第 1 页 · 共 60 项')).toBeVisible()
  await expect(page.getByText('ID: task-060', { exact: false })).toBeVisible()
})
