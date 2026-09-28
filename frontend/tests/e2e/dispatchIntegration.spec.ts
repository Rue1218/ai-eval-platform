import { expect, test } from '@playwright/test'

/** 大队列只取有限星图样本，旧运行任务按状态独立查询，未展示数量使用服务端总量。 */
test('调度大盘在两万条队列下保持有界请求和真实状态计数', async ({ page }) => {
  const task = (id: string, status: string, index: number) => ({
    id, kind: 'testcase', status, config: { kind: 'testcase' },
    created_at: new Date(Date.UTC(2026, 8, 28) - index * 1000).toISOString(),
  })
  const recent = Array.from({ length: 50 }, (_, i) => task(`done-${i}`, 'succeeded', i))
  const queued = Array.from({ length: 20_000 }, (_, i) => task(`queued-${i}`, 'queued', i + 50))
  const awaiting = Array.from({ length: 400 }, (_, i) => task(`awaiting-${i}`, 'awaiting_case_confirm', i + 20_050))
  const running = task('old-running', 'running', 20_450)
  const taskQueries: Array<{ status: string | null; offset: number; limit: number }> = []

  await page.route('**/api/**', route => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (url.pathname === '/api/tasks') {
      const status = url.searchParams.get('status')
      const offset = Number(url.searchParams.get('offset') || 0)
      const limit = Number(url.searchParams.get('limit') || 50)
      taskQueries.push({ status, offset, limit })
      const rows = status === 'queued' ? queued : status === 'running' ? [running]
        : status === 'awaiting_case_confirm' ? awaiting : recent
      return route.fulfill({ json: { items: rows.slice(offset, offset + Math.min(limit, 200)), total: rows.length } })
    }
    if (url.pathname === '/api/dispatch/overview') {
      return route.fulfill({ json: { online_workers: 0, total_workers: 0, queue_depth: 20_000,
        avg_dispatch_cost_ms: 0, assigned_today: 0, strategy: '负载均衡', max_running_tasks: 3, heartbeat_interval_ms: 500 } })
    }
    if (url.pathname === '/api/dispatch/workers') return route.fulfill({ json: [] })
    if (url.pathname === '/api/dispatch/events') return route.fulfill({ json: { items: [], next_after_id: 0 } })
    return route.fulfill({ json: {} })
  })

  await page.goto('/tests/dispatch-integration-fixture.html')
  await expect(page.locator('.task-chip.running')).toContainText('old-runn')
  await expect(page.locator('.task-chip.awaiting_case_confirm')).toHaveCount(2)
  await expect(page.locator('.kpi').filter({ hasText: '排队队列深度' }).locator('.kpi-num')).toHaveText('20000')
  await expect(page.locator('.kpi').filter({ hasText: '运行中任务' }).locator('.kpi-num')).toHaveText('1')
  await expect(page.getByText('星图仅展示代表任务')).toContainText('排队 19994、运行中 0、待确认 398')
  await expect.poll(() => taskQueries.length, { timeout: 10_000 }).toBeGreaterThanOrEqual(8)
  expect(taskQueries).toHaveLength(8)
  expect(taskQueries.every(query => query.offset === 0)).toBe(true)
  expect(taskQueries.filter(query => query.status === 'queued').map(query => query.limit)).toEqual([8, 8])
  expect(taskQueries.filter(query => query.status === 'running').map(query => query.limit)).toEqual([64, 64])
  expect(taskQueries.filter(query => query.status === 'awaiting_case_confirm').map(query => query.limit)).toEqual([8, 8])
})
