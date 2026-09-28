import { expect, test } from '@playwright/test'

/** 50 条较新终态任务之外保留旧 running，并跨页读完 201 条 queued。 */
test('真实调度页完整展示活跃任务，不受近期终态任务首屏限制', async ({ page }) => {
  page.on('pageerror', error => console.log('调度页异常：', error.message))
  page.on('console', entry => { if (entry.type() === 'error') console.log('浏览器错误：', entry.text()) })
  const task = (id: string, status: string, index: number) => ({
    id, kind: 'benchmark', status, config: { kind: 'benchmark' },
    created_at: new Date(Date.UTC(2026, 8, 28) - index * 1000).toISOString(),
  })
  const recent = Array.from({ length: 50 }, (_, i) => task(`done-${i}`, 'succeeded', i))
  const queued = Array.from({ length: 201 }, (_, i) => task(`queued-${i}`, 'queued', i + 50))
  const running = task('old-running', 'running', 251)
  const all = [...recent, ...queued, running]
  const taskQueries: Array<{ status: string | null; offset: number; limit: number }> = []

  await page.route('**/api/**', route => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (url.pathname === '/api/tasks') {
      const status = url.searchParams.get('status')
      const offset = Number(url.searchParams.get('offset') || 0)
      const limit = Number(url.searchParams.get('limit') || 50)
      taskQueries.push({ status, offset, limit })
      const rows = status ? all.filter(item => item.status === status) : all
      return route.fulfill({ json: { items: rows.slice(offset, offset + Math.min(limit, 200)), total: rows.length } })
    }
    if (url.pathname === '/api/dispatch/overview') {
      return route.fulfill({ json: { online_workers: 0, total_workers: 0, queue_depth: 201,
        avg_dispatch_cost_ms: 0, assigned_today: 0, strategy: '负载均衡', max_running_tasks: 3, heartbeat_interval_ms: 500 } })
    }
    if (url.pathname === '/api/dispatch/workers') return route.fulfill({ json: [] })
    if (url.pathname === '/api/dispatch/events') return route.fulfill({ json: { items: [], next_after_id: 0 } })
    return route.fulfill({ json: {} })
  })

  await page.goto('/tests/dispatch-integration-fixture.html')
  await expect(page.locator('.task-chip.running')).toContainText('old-runn')
  await expect(page.locator('.kpi').filter({ hasText: '排队队列深度' }).locator('.kpi-num')).toHaveText('201')
  expect(taskQueries).toContainEqual({ status: null, offset: 0, limit: 12 })
  expect(taskQueries).toContainEqual({ status: 'queued', offset: 200, limit: 200 })
  expect(taskQueries).toContainEqual({ status: 'running', offset: 0, limit: 200 })
})
