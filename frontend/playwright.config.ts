import { defineConfig } from '@playwright/test'

/** 浏览器契约夹具隔离于真实服务器；真实 PG/供应商结果另行登记。 */
export default defineConfig({
  testDir: './tests/e2e', workers: 1, timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:5273', headless: true, screenshot: 'only-on-failure',
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
  },
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 5273', url: 'http://127.0.0.1:5273', reuseExistingServer: false },
})
