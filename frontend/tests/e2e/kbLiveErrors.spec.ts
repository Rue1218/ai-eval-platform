import { expect, test, type Page } from '@playwright/test'

/** 真实页面保持 live 模式；只拦截接口响应以复现知识库后端缺失。 */
async function setupLiveFailure(page: Page) {
  let kbReads = 0
  await page.addInitScript(() => {
    localStorage.setItem('ae_mode', 'rag')
    localStorage.removeItem('ae_data_mode')
  })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/auth/me') {
      return route.fulfill({ json: { id: 'u', username: '联调成员', role: 'member' } })
    }
    if (path.startsWith('/api/kb')) {
      kbReads++
      return route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: '知识库接口不可用' } })
    }
    return route.fulfill({ json: {} })
  })
  await page.goto('/kb')
  await expect.poll(() => kbReads).toBeGreaterThan(0)
  return { getKbReads: () => kbReads }
}

test('实时知识库接口 404 显示错误，不展示示例资产', async ({ page }) => {
  const ctx = await setupLiveFailure(page)
  await expect(page.getByText('知识库接口不可用')).toBeVisible()
  await expect(page.locator('.kb-bar .chip')).toHaveCount(0)
  await expect(page.getByText('product-manual.pdf')).toHaveCount(0)
  await expect(page.getByText('qa-v1')).toHaveCount(0)

  const results = await page.evaluate(async () => {
    const { api } = await import('/src/api/http.ts')
    const calls = [
      () => api.kb.list(),
      () => api.kb.get('kb-default'),
      () => api.kb.listDocs('kb-default'),
      () => api.kb.getDocChunks('kb-default', 'd-01', { chunk_size: 512, overlap: 64 }),
      () => api.kb.query('kb-default', { query: '测试' }),
      () => api.kb.getGoldQA('kb-default'),
    ]
    return Promise.all(calls.map(async call => {
      try {
        await call()
        return 'unexpected success'
      } catch (error) {
        return error instanceof Error ? error.message : String(error)
      }
    }))
  })
  expect(results).toEqual(Array(6).fill('知识库接口不可用'))
  expect(ctx.getKbReads()).toBe(7)
})

test('显式 Mock 模式仍展示示例知识库', async ({ page }) => {
  let kbReads = 0
  await page.addInitScript(() => localStorage.setItem('ae_mode', 'rag'))
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path.startsWith('/api/kb')) kbReads++
    return route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: '知识库接口不可用' } })
  })
  await page.goto('/kb?data=mock')
  const sample = await page.evaluate(async () => {
    const { api } = await import('/src/api/http.ts')
    return { mode: api.getDataMode(), kbs: await api.kb.list(), docs: await api.kb.listDocs('kb-default') }
  })
  expect(sample.mode).toBe('mock')
  expect(sample.kbs.some(kb => kb.name === 'default')).toBe(true)
  expect(sample.docs.some(doc => doc.filename === 'product-manual.pdf')).toBe(true)
  expect(kbReads).toBe(0)
})
