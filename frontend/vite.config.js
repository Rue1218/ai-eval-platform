import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { execSync } from 'node:child_process'

// 获取当前构建对应的 Git 提交 ID（短 hash）
// 优先级：构建环境变量（docker build arg）> CI 环境变量 > 本地 git 命令
function getGitCommit() {
  if (process.env.BUILD_VERSION) {
    return process.env.BUILD_VERSION
  }
  if (process.env.GITHUB_SHA) {
    return process.env.GITHUB_SHA.slice(0, 8)
  }
  try {
    return execSync('git rev-parse --short HEAD', { encoding: 'utf8' }).trim()
  } catch {
    return 'unknown'
  }
}

const buildTime = process.env.BUILD_TIME || new Date().toISOString()
const gitCommit = getGitCommit()

// 本地联调可指向已有 API；REST 与 WS 必须使用同一后端，避免静态预览服务误接消息。
export default defineConfig(({ mode }) => {
  const apiTarget = loadEnv(mode, process.cwd(), '').API_PROXY_TARGET || 'http://localhost:8000'
  return {
  plugins: [vue()],
  resolve: {
    alias: {
      mermaid: 'mermaid/dist/mermaid.esm.min.mjs',
    },
  },
  build: {
    // 大依赖手动分包：mermaid/echarts/katex 均为低频更新的大体积库，
    // 拆分后业务代码改动不会使其缓存失效，显著改善构建产物缓存命中率
    rollupOptions: {
      output: {
        manualChunks(rawId) {
          const id = rawId.replace(/\\/g, '/')
          if (!id.includes('/node_modules/')) {
            // Vite 动态导入预加载 helper（虚拟模块 \0vite/preload-helper.js）必须
            // 单独成块：否则 Rollup 会把它并入唯一动态导入目标 vendor-mermaid，
            // 使所有含动态导入的页面反向静态引用 3.5MB 的 mermaid 块。
            if (id.includes('vite/preload-helper')) return 'vendor-vite'
            return
          }
          // 精确匹配包目录，避免 `d3-`/`mermaid` 这类宽泛子串误吞无关模块
          if (
            id.includes('/node_modules/mermaid/') ||
            id.includes('/node_modules/@mermaid-js/') ||
            id.includes('/node_modules/cytoscape/') ||
            id.includes('/node_modules/dagre/') ||
            /\/node_modules\/d3-[^/]+\//.test(id)
          ) {
            return 'vendor-mermaid'
          }
          if (id.includes('/node_modules/echarts/') || id.includes('/node_modules/zrender/')) {
            return 'vendor-echarts'
          }
          if (id.includes('/node_modules/katex/')) {
            return 'vendor-katex'
          }
          if (id.includes('/node_modules/naive-ui/')) {
            return 'vendor-naive'
          }
        },
      },
    },
  },
  define: {
    __BUILD_VERSION__: JSON.stringify(gitCommit),
    __BUILD_TIME__: JSON.stringify(buildTime),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: apiTarget.replace(/^http/, 'ws'),
        changeOrigin: true,
        ws: true,
      },
    },
  },
  }
})
