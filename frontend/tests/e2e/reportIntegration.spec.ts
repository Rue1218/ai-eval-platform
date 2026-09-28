import { expect, test, type Page, type Route } from '@playwright/test'
import { readFile } from 'node:fs/promises'

/** 使用真实页面和 HTTP 层验证列表导航及迟到详情响应。 */
async function setup(page: Page) {
  const reports = Array.from({ length: 21 }, (_, i) => ({
    id: `report-${i + 1}`, title: `报告 ${i + 1}`, task_id: `task-${i + 1}`,
    kind: 'benchmark', created_at: new Date(Date.UTC(2026, 8, 28, 0, 0, 21 - i)).toISOString(),
  }))
  const listRequests: number[] = []
  let holdFirstDetail = false
  let heldDetail: Route | null = null
  await page.route(/^http:\/\/127\.0\.0\.1:5273\/api\/reports(?:\/|\?|$)/, async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/reports') {
      const offset = Number(url.searchParams.get('offset') || 0)
      const limit = Number(url.searchParams.get('limit') || 20)
      listRequests.push(offset)
      return route.fulfill({ json: { items: reports.slice(offset, offset + limit), total: reports.length } })
    }
    const id = url.pathname.split('/')[3]
    if (holdFirstDetail && id === 'report-1') {
      heldDetail = route
      return
    }
    return route.fulfill({ json: { ...reports.find(item => item.id === id), scores: [], sample_items: [] } })
  })
  await page.goto('/tests/report-integration-fixture.html')
  await expect(page.getByText('共 21 份报告')).toBeVisible()
  return { listRequests, holdFirstDetail: () => { holdFirstDetail = true }, heldDetail: () => heldDetail,
    releaseDetail: async () => {
      if (heldDetail) await heldDetail.fulfill({ json: { ...reports[0], scores: [], sample_items: [] } })
    },
  }
}

test('历史报告列表读取真实分页接口并可进入详情', async ({ page }) => {
  const ctx = await setup(page)
  await expect(page.locator('.report-list-item')).toHaveCount(20)
  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.locator('.report-list-item')).toHaveCount(1)
  expect(ctx.listRequests).toEqual([0, 20])
  await page.getByRole('link', { name: /报告 21/ }).click()
  await expect(page.getByText('报告 ID: report-21', { exact: false })).toBeVisible()
})

test('旧详情迟到时不能覆盖新路由的报告', async ({ page }) => {
  const ctx = await setup(page)
  ctx.holdFirstDetail()
  await page.evaluate(() => (window as any).__reportRouter.push('/reports/report-1'))
  await expect.poll(() => !!ctx.heldDetail()).toBe(true)
  await page.evaluate(() => (window as any).__reportRouter.push('/reports/report-2'))
  await expect(page.getByText('报告 ID: report-2', { exact: false })).toBeVisible()
  const oldResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/reports/report-1')
  await ctx.releaseDetail()
  await oldResponse
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await expect(page.getByText('报告 ID: report-2', { exact: false })).toBeVisible()
  await expect(page.getByText('报告 ID: report-1', { exact: false })).toHaveCount(0)
})

test('切换报告后取消旧 Markdown 导出，当前报告下载名与内容一致', async ({ page }) => {
  await setup(page)
  await page.evaluate(() => (window as any).__reportRouter.push('/reports/report-1'))
  await expect(page.getByText('报告 ID: report-1', { exact: false })).toBeVisible()

  let heldMarkdown: Route | null = null
  await page.route(url => url.pathname === '/api/reports/report-1' && url.searchParams.get('fmt') === 'md', route => {
    heldMarkdown = route
  })
  const downloads: string[] = []
  page.on('download', download => downloads.push(download.suggestedFilename()))
  await page.getByRole('button', { name: '导出 Markdown' }).click()
  await expect.poll(() => heldMarkdown !== null).toBe(true)

  await page.evaluate(() => (window as any).__reportRouter.push('/reports/report-2'))
  await expect(page.getByText('报告 ID: report-2', { exact: false })).toBeVisible()
  const oldResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/reports/report-1' && new URL(response.url()).searchParams.get('fmt') === 'md')
  await heldMarkdown!.fulfill({ body: '# 报告 A', contentType: 'text/markdown' })
  await oldResponse
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  expect(downloads).toEqual([])

  await page.route(url => url.pathname === '/api/reports/report-2' && url.searchParams.get('fmt') === 'md', route =>
    route.fulfill({ body: '# 报告 B', contentType: 'text/markdown' }))
  const currentDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出 Markdown' }).click()
  const download = await currentDownload
  expect(download.suggestedFilename()).toBe('Report-report-2.md')
  expect(await readFile(await download.path(), 'utf8')).toBe('# 报告 B')
})
